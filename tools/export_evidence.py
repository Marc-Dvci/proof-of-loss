"""Copy a finished rehearsal from runs/ into evidence/ and examples/, so a clean clone can read and replay it.

    python tools/export_evidence.py runs/cloud-final

evidence/final/<case>/ holds what the replay and the tables read: score.json, trace.jsonl, actions.jsonl, events.json,
the run's vision cache and the saved dossier. examples/A1-burglary/ holds one finished output and the request behind it.
"""

import glob
import json
import os
import shutil
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "harness"))
from replay import conversation  # noqa: E402

import score as scoring  # noqa: E402
from cases import CASES, by_id  # noqa: E402

KEPT = ("score.json", "trace.jsonl", "actions.jsonl", "events.json", "vision_cache.json")
EXAMPLE = "A1-burglary"


def export(run_dir, evidence, examples):
    shutil.rmtree(evidence, ignore_errors=True)
    scores = []
    models: set = set()
    for case in CASES:
        source = os.path.join(run_dir, case["id"])
        if not os.path.exists(os.path.join(source, "score.json")):
            continue
        dest = os.path.join(evidence, case["id"])
        os.makedirs(dest)
        for name in KEPT:
            if os.path.exists(os.path.join(source, name)):
                shutil.copy2(os.path.join(source, name), dest)
        for path in glob.glob(os.path.join(source, "nas", "**", "CLAIM-DOSSIER*.md"), recursive=True):
            shutil.copy2(path, os.path.join(dest, "CLAIM-DOSSIER.md"))
        with open(os.path.join(source, "score.json"), encoding="utf-8") as f:
            scores.append(json.load(f))
        with open(os.path.join(source, "trace.jsonl"), encoding="utf-8") as f:
            models.update(r["model"] for r in map(json.loads, f) if r.get("kind") == "llm" and r.get("model"))
    writing = [s for s in scores if by_id(s["case"])["expect_written"]]
    with open(os.path.join(evidence, "summary.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(
            {
                "cases": [s["case"] for s in scores],
                "models": sorted(models),
                "evidence": scoring.summarize(writing),
                "safety": scoring.summarize(scores),
            },
            f,
            indent=1,
        )
    example = os.path.join(examples, EXAMPLE)
    shutil.rmtree(example, ignore_errors=True)
    os.makedirs(example)
    shutil.copy2(os.path.join(evidence, EXAMPLE, "CLAIM-DOSSIER.md"), example)
    with open(os.path.join(example, "REQUEST.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# The request\n\n> {by_id(EXAMPLE)['request']}\n")
    with open(os.path.join(example, "CONVERSATION.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# The run as the user saw it\n\n```text\n{conversation(os.path.join(evidence, EXAMPLE))}\n```\n")
    return [s["case"] for s in scores]


if __name__ == "__main__":
    print(export(sys.argv[1], os.path.join(ROOT, "evidence", "final"), os.path.join(ROOT, "examples")))
