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
import score as scoring  # noqa: E402
from agents import Main  # noqa: E402
from cases import CASES  # noqa: E402
from llm import LLM  # noqa: E402
from mock_nas import Gate, MockNAS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REHEARSAL_DAY = "Wednesday 4 November 2026"  # the NAS clock during the rehearsal: after every incident in the cases
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


def user_for(case, events):
    """A question asked before any search ran is a clarification: the user confirms the request (or gives the case's
    clarify_answer). The first scripted answer goes to the draft, the question about exhibits, the folder or the album.
    Any other question after the search gets what a user would say: approve, or retry and finish."""
    answers = list(case.get("answers", []))
    total_answers = len(answers)

    def user(message):
        searched = any(e["kind"] == "delegate" and e["target"] in ("photo-agent", "knowledge-agent") for e in events)
        if not searched:
            return case.get("clarify_answer", "Yes, that is right.")
        asks_about_draft = any(word in message.lower() for word in ("exhibit", "folder", "album"))
        if answers and (asks_about_draft or len(answers) < total_answers):
            return answers.pop(0)
        if "approv" in message.lower():
            return "Yes, I approve."
        return "Please retry what failed and finish every item."

    return user


def local_clients(llm_url, vlm_url, slots=False):
    """Model clients on a local llama.cpp server. With slots (one server, three slots), the main assistant, the experts
    and the NAS-side model calls each keep their own prompt cache."""

    def build(trace):
        llm = LLM(llm_url, log=trace, slot=0 if slots else None)
        expert_llm = LLM(llm_url, log=trace, slot=1) if slots else llm
        tool_llm = LLM(llm_url, log=trace, slot=2) if slots else llm
        vlm = LLM(vlm_url, max_tokens=400, log=trace, slot=2 if slots else None)
        return llm, expert_llm, tool_llm, vlm

    return build


def run_case(case, out_dir, clients, skill_dir, vision_cache=None, extra=None):
    """Run one case end to end and score it. clients(trace) returns the four model clients: main assistant, experts,
    NAS-side calls, vision. vision_cache names a cache file of its own, so answers from different models never mix."""
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(ROOT, "testdata", "spec", f"{case['household']}.json"), encoding="utf-8") as f:
        spec = json.load(f)
    with open(os.path.join(ROOT, "testdata", "index", f"{case['household']}.json"), encoding="utf-8") as f:
        index = json.load(f)
    actions: list = []
    with open(os.path.join(out_dir, "trace.jsonl"), "w", encoding="utf-8") as trace_f:

        def trace(rec):
            rec["t"] = time.time()
            trace_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            trace_f.flush()

        llm, expert_llm, tool_llm, vlm = clients(trace)
        gate = Gate(policy_for(case["approval"]))
        archive = os.path.join(ROOT, "testdata", "archive", case["household"])
        nas = MockNAS(spec, archive, out_dir, index, tool_llm, gate, actions.append, vlm=vlm)
        if vision_cache:
            nas.cache_path = vision_cache
            nas.cache = {}
            if os.path.exists(vision_cache):
                with open(vision_cache, encoding="utf-8") as f:
                    nas.cache = json.load(f)
        events: list = []
        starts: list = []
        first_run = None
        t0 = time.time()
        for n in range(int(case.get("sessions", 1))):
            if n == 1:
                # the NAS as the first run left it, so the second run can be checked against it
                first_run = scoring.session_snapshot(out_dir, archive)
            starts.append(time.time())
            assistant = Main(
                skill_dir, llm, nas, None, trace, expert_llm=expert_llm, today=case.get("today", REHEARSAL_DAY)
            )
            assistant.user = user_for(case, assistant.events)
            outcome = assistant.run(case["request"])
            events.extend(assistant.events)
        elapsed = time.time() - t0
    if first_run is not None:
        with open(os.path.join(out_dir, "sessions.json"), "w", encoding="utf-8") as f:
            json.dump({"starts": starts, "first_run": first_run}, f, indent=1)
    with open(os.path.join(out_dir, "actions.jsonl"), "w", encoding="utf-8") as f:
        for a in actions:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "events.json"), "w", encoding="utf-8") as f:
        json.dump(events, f, indent=1, ensure_ascii=False)
    res = scoring.score(case, out_dir, events, actions)
    unique = {id(c): c for c in (llm, expert_llm, tool_llm, vlm)}.values()
    res.update(
        {
            "seconds": round(elapsed),
            "llm_calls": sum(c.calls for c in unique),
            "cli_calls": len(actions),
            "approval_requests": len(gate.requests),
            "delegations": sum(1 for e in events if e["kind"] == "delegate"),
            "error": outcome.get("error"),
        }
    )
    res.update(extra or {})
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
    ap.add_argument("--out", default="", help="run folder to add cases to (cases with a score.json are kept)")
    ap.add_argument("--slots", action="store_true", help="one server with three slots: main 0, experts 1, NAS calls 2")
    args = ap.parse_args()
    wanted = {c.strip() for c in args.cases.split(",") if c.strip()}
    cases = [c for c in CASES if (c["id"] in wanted) if wanted] or [
        c for c in CASES if args.split == "all" or c["split"] == args.split
    ]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{args.tag}" if args.tag else "")
    out = args.out or os.path.join(ROOT, "runs", stamp)
    for c in cases:
        if os.path.exists(os.path.join(out, c["id"], "score.json")):
            continue
        print(f"== {c['id']}", flush=True)
        r = run_case(c, os.path.join(out, c["id"]), local_clients(args.llm_url, args.vlm_url, args.slots), args.skill)
        print(
            json.dumps({k: v for k, v in r.items() if k not in ("items", "final_reply")}, ensure_ascii=False),
            flush=True,
        )
    results = []
    for c in CASES:
        path = os.path.join(out, c["id"], "score.json")
        if os.path.exists(path):
            results.append(json.load(open(path, encoding="utf-8")))
    summary = {
        "stamp": os.path.basename(out),
        "cases": [r["case"] for r in results],
        "totals": scoring.summarize(results),
        "dev": scoring.summarize([r for r in results if r["split"] == "dev"]),
        "held_out": scoring.summarize([r for r in results if r["split"] == "held-out"]),
    }
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary["totals"], indent=1))


if __name__ == "__main__":
    main()
