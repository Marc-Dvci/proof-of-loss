"""Rehearse cases on models served by Alibaba Cloud Model Studio instead of a local llama.cpp server.

    python tools/cloud_rehearsal.py --text-model qwen-plus-2025-04-28 --vision-model qwen3-vl-plus \
        --cases A1-burglary --out runs/cloud-qwen3

The key comes from DASHSCOPE_API_KEY or from the `bl` CLI config (~/.bailian/config.json). The agent loops, the stand-in
CLI layer and the scorer are the same code as the local rehearsal; only the model behind them changes. Each run keeps
its own vision cache, so answers from different models never mix.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "harness"))

from run import run_case  # noqa: E402

from cases import by_id  # noqa: E402
from llm import LLM  # noqa: E402

RETRIES = 9
RETRY_CODES = {429, 500, 502, 503, 504}


def credentials():
    key = os.environ.get("DASHSCOPE_API_KEY")
    base = os.environ.get("DASHSCOPE_BASE_URL")
    if not key or not base:
        path = os.path.expanduser(os.path.join("~", ".bailian", "config.json"))
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        key = key or cfg["api_key"]
        base = base or cfg["base_url"]
    return key, base.rstrip("/")


class CloudLLM(LLM):
    """The local client's interface over Model Studio's OpenAI-compatible endpoint, with thinking off as in the local runs."""

    def __init__(self, base_url, api_key, model, **kw):
        super().__init__(url=base_url + "/compatible-mode", model=model, **kw)
        self.api_key = api_key

    def _post(self, payload, timeout=600):
        payload.pop("chat_template_kwargs", None)
        payload["enable_thinking"] = False
        req = urllib.request.Request(
            self.url + "/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key},
            method="POST",
        )
        started = time.time()
        for attempt in range(RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    out = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:400]
                if e.code not in RETRY_CODES or attempt == RETRIES - 1:
                    raise RuntimeError(f"{self.model}: HTTP {e.code}: {body}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == RETRIES - 1:
                    raise RuntimeError(f"{self.model}: {e}") from e
            time.sleep(min(2**attempt, 60))
        seconds = time.time() - started
        self.calls += 1
        self.seconds += seconds
        if self.log:
            usage = out.get("usage", {})
            self.log(
                {
                    "kind": "llm",
                    "seconds": round(seconds, 2),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "model": self.model,
                }
            )
        return out["choices"][0]["message"].get("content") or ""


def cloud_clients(text_model, vision_model):
    key, base = credentials()

    def build(trace):
        llm = CloudLLM(base, key, text_model, log=trace)
        vlm = CloudLLM(base, key, vision_model, max_tokens=400, log=trace)
        return llm, llm, llm, vlm

    return build


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text-model", required=True)
    ap.add_argument("--vision-model", default="qwen3-vl-plus")
    ap.add_argument("--cases", default="A1-burglary")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skill", default=os.path.join(ROOT, "skill", "proof-of-loss"))
    args = ap.parse_args()
    for case_id in [c.strip() for c in args.cases.split(",") if c.strip()]:
        out_dir = os.path.join(args.out, case_id)
        res = run_case(
            by_id(case_id),
            out_dir,
            cloud_clients(args.text_model, args.vision_model),
            args.skill,
            vision_cache=os.path.join(out_dir, "vision_cache.json"),
            extra={"text_model": args.text_model, "vision_model": args.vision_model},
        )
        print(json.dumps({k: v for k, v in res.items() if k not in ("items", "final_reply")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
