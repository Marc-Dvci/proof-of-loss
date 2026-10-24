"""Run rehearsal cases end to end and score them.

    python harness/run.py --cases A1-burglary,A4-absent-and-injection [--split dev|held-out|all]
        [--llm-url http://127.0.0.1:8099] [--vlm-url http://127.0.0.1:8098] [--skill skill/proof-of-loss]

Each case gets runs/<stamp>/<case id>/ with the mock NAS after the run, trace.jsonl (every agent action),
actions.jsonl (every CLI call with its approval decision), events.json (what the user saw) and score.json.
runs/<stamp>/summary.json aggregates the scores.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from agents import Main  # noqa: E402
from cases import CASES  # noqa: E402
from llm import LLM  # noqa: E402
from mock_nas import Gate, MockNAS  # noqa: E402
import score as scoring  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))


def policy_for(mode):
    state = {"n": 0}

    def policy(op):
        state["n"] += 1
        if mode == "deny":
            return "deny"
        if mode == "defer-once" and state["n"] == 1:
            return "defer"
        return "approve"
    return policy


def user_for(case):
    answers = list(case.get("answers", []))

    def user(message):
        if answers:
            return answers.pop(0)
        if "approv" in message.lower():
            return "Yes, I approve."
        return "Please continue with what you have."
    return user


def run_case(case, out_dir, llm_url, vlm_url, skill_dir):
    os.makedirs(out_dir, exist_ok=True)
    spec = json.load(open(os.path.join(ROOT, "testdata", "spec", f"{case['household']}.json"), encoding="utf-8"))
    index = json.load(open(os.path.join(ROOT, "testdata", "index", f"{case['household']}.json"), encoding="utf-8"))
    trace_f = open(os.path.join(out_dir, "trace.jsonl"), "w", encoding="utf-8")
    actions = []

    def trace(rec):
        rec["t"] = time.time()
        trace_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        trace_f.flush()

    def log_action(entry):
        actions.append(entry)

    llm = LLM(llm_url, log=trace)
    vlm = LLM(vlm_url, max_tokens=400, log=trace)
    gate = Gate(policy_for(case["approval"]))
    nas = MockNAS(spec, os.path.join(ROOT, "testdata", "archive", case["household"]), out_dir, index, llm, gate,
                  log_action, vlm=vlm)
    main = Main(skill_dir, llm, nas, user_for(case), trace)
    t0 = time.time()
    outcome = main.run(case["request"])
    elapsed = time.time() - t0
    trace_f.close()
    with open(os.path.join(out_dir, "actions.jsonl"), "w", encoding="utf-8") as f:
        for a in actions:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "events.json"), "w", encoding="utf-8") as f:
        json.dump(main.events, f, indent=1, ensure_ascii=False)
    res = scoring.score(case, out_dir, main.events, actions)
    res.update({"seconds": round(elapsed), "llm_calls": llm.calls + vlm.calls, "cli_calls": len(actions),
                "approval_requests": len(gate.requests), "delegations": sum(1 for e in main.events if e["kind"] == "delegate"),
                "error": outcome.get("error")})
    with open(os.path.join(out_dir, "score.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="")
    ap.add_argument("--split", default="dev", choices=["dev", "held-out", "all"])
    ap.add_argument("--llm-url", default="http://127.0.0.1:8099")
    ap.add_argument("--vlm-url", default="http://127.0.0.1:8098")
    ap.add_argument("--skill", default=os.path.join(ROOT, "skill", "proof-of-loss"))
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    wanted = {c.strip() for c in args.cases.split(",") if c.strip()}
    cases = [c for c in CASES if (c["id"] in wanted) if wanted] or \
            [c for c in CASES if args.split == "all" or c["split"] == args.split]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{args.tag}" if args.tag else "")
    out = os.path.join(ROOT, "runs", stamp)
    results = []
    for c in cases:
        print(f"== {c['id']}", flush=True)
        r = run_case(c, os.path.join(out, c["id"]), args.llm_url, args.vlm_url, args.skill)
        results.append(r)
        print(json.dumps({k: v for k, v in r.items() if k not in ("items", "final_reply")}, ensure_ascii=False), flush=True)
    summary = {"stamp": stamp, "cases": [c["id"] for c in cases], "totals": scoring.summarize(results)}
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary["totals"], indent=1))


if __name__ == "__main__":
    main()
