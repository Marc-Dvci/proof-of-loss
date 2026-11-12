"""Print the rehearsal results as Markdown, straight from a finished run folder.

    python tools/results_table.py runs/<name>

One row per case, then the totals per household: evidence over the cases that save a dossier, safety over every
case. The README, the
write-up and the test plan quote these tables.
"""

import glob
import json
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "harness"))
import score as scoring  # noqa: E402
from cases import CASES  # noqa: E402


def frac(ok, n):
    return f"{ok}/{n}" if n else "n/a"


def outcome(s, case):
    if case.get("expect_refusal"):
        return "declined, nothing written" if s.get("refused") and not s["state_changes_ok"] else "check"
    if not case["expect_written"]:
        return "approval declined, nothing written" if not s["state_changes_ok"] else "check"
    return "dossier saved" if s["dossier_written"] else "no dossier"


def wrong(s):
    """Files in the claim folder that are not evidence for any claimed item: look-alike photos and unrelated receipts."""
    return s.get("wrong_exhibits_copied", s["decoys_copied"])


def row(s, case):
    if not case["expect_written"]:
        return (
            f"| {case['id']} | {outcome(s, case)} | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | {wrong(s)} | "
            f"{s['writes_before_confirmation']} | {round(s['seconds'] / 60)} min |"
        )
    items = s["items"].values()
    item_sections = frac(sum(1 for i in items if i.get("section_found")), len(items))
    device = frac(
        sum(i.get("device_photos_copied", 0) for i in items), sum(i.get("device_photos_expected", 0) for i in items)
    )
    photos = frac(sum(i.get("photos_copied_ok", 0) for i in items), sum(i["photos_expected"] for i in items))
    receipts = frac(sum(i.get("receipts_copied_ok", 0) for i in items), sum(i["receipts_expected"] for i in items))
    serials = [i for i in items if "serial_expected" in i]
    prices = [i for i in items if "price_expected" in i]
    hashes = frac(s["hashes_listed"] - s["hashes_wrong"], s["hashes_listed"])
    events = frac(s["events_cited_ok"], s["events_expected"])
    return (
        f"| {case['id']} | {outcome(s, case)} | {item_sections} | {photos} | {device} | {receipts} | "
        f"{frac(sum(1 for i in serials if i['serial_found']), len(serials))} | "
        f"{frac(sum(1 for i in prices if i['price_found']), len(prices))} | {events} | {hashes} | "
        f"{wrong(s)} | {s['writes_before_confirmation']} | {round(s['seconds'] / 60)} min |"
    )


def load(run_dir):
    results = {}
    for path in glob.glob(os.path.join(run_dir, "*", "score.json")):
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        results[s["case"]] = s
    return results


def table_lines(results):
    """The Markdown table, one row per case that has a score, in the order of the case list."""
    lines = [
        "| Case | Outcome | Item sections | Photos in folder | Device photos | Receipts in folder | Serials | Prices "
        "| Camera events | Hashes match | Wrong exhibits | Writes before the answer | Run time |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines.extend(row(scoring.as_reported(results[case["id"]]), case) for case in CASES if case["id"] in results)
    return lines


def main():
    results = load(sys.argv[1])
    print("\n".join(table_lines(results)))
    expect = {c["id"]: c["expect_written"] for c in CASES}
    for split in ("dev", "held-out"):
        reported = [scoring.as_reported(r) for r in results.values()]
        writing = [r for r in reported if r["split"] == split and expect[r["case"]]]
        every = [r for r in reported if r["split"] == split]
        if every:
            print(
                f"\n{split} evidence ({len(writing)} cases that save a dossier): "
                + json.dumps(scoring.summarize(writing))
            )
            print(f"{split} safety ({len(every)} cases): " + json.dumps(scoring.summarize(every)))
    missing = [c["id"] for c in CASES if c["id"] not in results]
    if missing:
        print("\nnot scored yet:", ", ".join(missing))


if __name__ == "__main__":
    main()
