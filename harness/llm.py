"""Chat client for a local OpenAI-compatible server (llama.cpp llama-server).

Every agent step asks for one JSON object (grammar-constrained by the server), so a step always parses.
Vision calls send the image as a base64 data URI in the same chat endpoint.
"""

import base64
import json
import os
import time
import urllib.request

DEFAULT_URL = os.environ.get("POL_LLM_URL", "http://127.0.0.1:8099")


class LLM:
    def __init__(self, url=DEFAULT_URL, model="local", temperature=0.0, seed=7, max_tokens=2048, log=None, slot=None):
        self.url = url.rstrip("/")
        self.slot = slot  # llama-server slot to pin this client to, so each role keeps its prompt cache
        self.model = model
        self.temperature = temperature
        self.seed = seed
        self.max_tokens = max_tokens
        self.log = log  # callable(dict) for usage accounting
        self.calls = 0
        self.seconds = 0.0
        self.last_text = ""  # raw text of the last JSON reply, sent back verbatim so the server's cache extends
        self.prompt_n = 0  # prompt tokens the server processed on the last call (cache misses)

    def _post(self, payload, timeout=900):
        req = urllib.request.Request(
            self.url + "/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())
        dt = time.time() - t0
        self.calls += 1
        self.seconds += dt
        self.prompt_n = (out.get("timings") or {}).get("prompt_n", 0)
        if self.log:
            usage = out.get("usage", {})
            self.log(
                {
                    "kind": "llm",
                    "seconds": round(dt, 2),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "prompt_processed": self.prompt_n,
                    "completion_tokens": usage.get("completion_tokens"),
                }
            )
        return out["choices"][0]["message"].get("content") or ""

    def chat(self, messages, json_mode=True, max_tokens=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "seed": self.seed,
            "max_tokens": max_tokens or self.max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.slot is not None:
            payload["id_slot"] = self.slot
        return self._post(payload)

    def chat_json(self, messages, max_tokens=None, retries=2):
        last = None
        for _ in range(retries + 1):
            text = self.chat(messages, json_mode=True, max_tokens=max_tokens)
            try:
                parsed = json.loads(text)
                self.last_text = text
                return parsed
            except json.JSONDecodeError as e:
                last = e
                messages = messages + [
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": "That was not one valid JSON object. Reply again with one JSON object only.",
                    },
                ]
        raise ValueError(f"model did not return JSON: {last}")

    def vision(self, image_path, prompt, max_tokens=400):
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        return self.chat(messages, json_mode=False, max_tokens=max_tokens).strip()
