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
from run import REHEARSAL_DAY, policy_for, user_for  # noqa: E402

import score as scoring  # noqa: E402
from agents import Main  # noqa: E402
from cases import by_id  # noqa: E402
from llm import LLM  # noqa: E402
from mock_nas import Gate, MockNAS  # noqa: E402

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


def run_case(case, out_dir, text_model, vision_model, skill_dir):
    os.makedirs(out_dir, exist_ok=True)
    key, base = credentials()
    household = case["household"]
    with open(os.path.join(ROOT, "testdata", "spec", f"{household}.json"), encoding="utf-8") as f:
        spec = json.load(f)
    with open(os.path.join(ROOT, "testdata", "index", f"{household}.json"), encoding="utf-8") as f:
        index = json.load(f)
    actions = []
    with open(os.path.join(out_dir, "trace.jsonl"), "w", encoding="utf-8") as trace_f:

        def trace(rec):
            rec["t"] = time.time()
            trace_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            trace_f.flush()

        llm = CloudLLM(base, key, text_model, log=trace)
        vlm = CloudLLM(base, key, vision_model, max_tokens=400, log=trace)
        gate = Gate(policy_for(case["approval"]))
        archive = os.path.join(ROOT, "testdata", "archive", household)
        nas = MockNAS(spec, archive, out_dir, index, llm, gate, actions.append, vlm=vlm)
        nas.cache_path = os.path.join(out_dir, "vision_cache.json")
        nas.cache = {}
        main = Main(skill_dir, llm, nas, None, trace, expert_llm=llm, today=case.get("today", REHEARSAL_DAY))
        main.user = user_for(case, main.events)
        started = time.time()
        outcome = main.run(case["request"])
        elapsed = time.time() - started
    with open(os.path.join(out_dir, "actions.jsonl"), "w", encoding="utf-8") as f:
        for a in actions:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "events.json"), "w", encoding="utf-8") as f:
        json.dump(main.events, f, indent=1, ensure_ascii=False)
    res = scoring.score(case, out_dir, main.events, actions)
    res.update(
        {
            "seconds": round(elapsed),
            "llm_calls": llm.calls + vlm.calls,
            "cli_calls": len(actions),
            "approval_requests": len(gate.requests),
            "delegations": sum(1 for e in main.events if e["kind"] == "delegate"),
            "error": outcome.get("error"),
            "text_model": text_model,
            "vision_model": vision_model,
        }
    )
    with open(os.path.join(out_dir, "score.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text-model", required=True)
    ap.add_argument("--vision-model", default="qwen3-vl-plus")
    ap.add_argument("--cases", default="A1-burglary")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skill", default=os.path.join(ROOT, "skill", "proof-of-loss"))
    args = ap.parse_args()
    for case_id in [c.strip() for c in args.cases.split(",") if c.strip()]:
        res = run_case(by_id(case_id), os.path.join(args.out, case_id), args.text_model, args.vision_model, args.skill)
        print(json.dumps({k: v for k, v in res.items() if k not in ("items", "final_reply")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
