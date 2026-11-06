"""Score every case of a finished run folder again with the current scorer, from what each run left behind
(the mock NAS, actions.jsonl and events.json), and rewrite score.json and summary.json.

    python tools/rescore.py runs/<name>

Run time, model call counts and the case outcome recorded by the run are kept.
"""

import glob
import json
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "harness"))
import score as scoring  # noqa: E402
from cases import CASES, by_id  # noqa: E402

KEPT = ("seconds", "llm_calls", "cli_calls", "approval_requests", "delegations", "error", "text_model", "vision_model")


def main():
    run_dir = sys.argv[1]
    results = []
    for path in sorted(glob.glob(os.path.join(run_dir, "*", "score.json"))):
        case_dir = os.path.dirname(path)
        old = json.load(open(path, encoding="utf-8"))
        actions = [json.loads(ln) for ln in open(os.path.join(case_dir, "actions.jsonl"), encoding="utf-8")]
        events = json.load(open(os.path.join(case_dir, "events.json"), encoding="utf-8"))
        res = scoring.score(by_id(old["case"]), case_dir, events, actions)
        res.update({k: old[k] for k in KEPT if k in old})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1, ensure_ascii=False)
        results.append(res)
        print("rescored", old["case"])
    order = {c["id"]: i for i, c in enumerate(CASES)}
    results.sort(key=lambda r: order[r["case"]])
    summary = {
        "stamp": os.path.basename(os.path.normpath(run_dir)),
        "cases": [r["case"] for r in results],
        "totals": scoring.summarize(results),
        "dev": scoring.summarize([r for r in results if r["split"] == "dev"]),
        "held_out": scoring.summarize([r for r in results if r["split"] == "held-out"]),
    }
    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)


if __name__ == "__main__":
    main()
