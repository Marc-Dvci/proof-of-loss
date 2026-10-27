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
from cases import CASES  # noqa: E402
import score as scoring  # noqa: E402


def frac(ok, n):
    return f"{ok}/{n}" if n else "n/a"


def outcome(s, case):
    if case.get("expect_refusal"):
        return "declined, nothing written" if s.get("refused") and not s["state_changes_ok"] else "check"
    if not case["expect_written"]:
        return "approval declined, nothing written" if not s["state_changes_ok"] else "check"
    return "dossier saved" if s["dossier_written"] else "no dossier"


def row(s, case):
    if not case["expect_written"]:
        return (f"| {case['id']} | {outcome(s, case)} | n/a | n/a | n/a | n/a | n/a | n/a | n/a | {s['decoys_copied']} | "
                f"{s['writes_before_confirmation']} | {round(s['seconds'] / 60)} min |")
    items = s["items"].values()
    photos = frac(sum(i.get("photos_copied_ok", 0) for i in items), sum(i["photos_expected"] for i in items))
    receipts = frac(sum(i.get("receipts_copied_ok", 0) for i in items), sum(i["receipts_expected"] for i in items))
    serials = [i for i in items if "serial_expected" in i]
    prices = [i for i in items if "price_expected" in i]
    hashes = frac(s["hashes_listed"] - s["hashes_wrong"], s["hashes_listed"])
    events = frac(s["events_cited_ok"], s["events_expected"])
    listed = s.get("exhibits_listed", 0)
    copied = frac(listed - s.get("exhibits_not_copied", 0), listed)
    return (f"| {case['id']} | {outcome(s, case)} | {photos} | {receipts} | "
            f"{frac(sum(1 for i in serials if i['serial_found']), len(serials))} | "
            f"{frac(sum(1 for i in prices if i['price_found']), len(prices))} | {events} | {copied} | {hashes} | "
            f"{s['decoys_copied']} | {s['writes_before_confirmation']} | {round(s['seconds'] / 60)} min |")


def main():
    run_dir = sys.argv[1]
    results = {}
    for path in glob.glob(os.path.join(run_dir, "*", "score.json")):
        s = json.load(open(path, encoding="utf-8"))
        results[s["case"]] = s
    print("| Case | Outcome | Photos in folder | Receipts in folder | Serials | Prices | Camera events "
          "| Exhibits copied | Hashes match | Decoys copied | Writes before the answer | Run time |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for case in CASES:
        if case["id"] in results:
            print(row(results[case["id"]], case))
    expect = {c["id"]: c["expect_written"] for c in CASES}
    for split in ("dev", "held-out"):
        writing = [r for r in results.values() if r["split"] == split and expect[r["case"]]]
        every = [r for r in results.values() if r["split"] == split]
        if every:
            print(f"\n{split} evidence ({len(writing)} cases that save a dossier): "
                  + json.dumps(scoring.summarize(writing)))
            print(f"{split} safety ({len(every)} cases): " + json.dumps(scoring.summarize(every)))
    missing = [c["id"] for c in CASES if c["id"] not in results]
    if missing:
        print("\nnot scored yet:", ", ".join(missing))


if __name__ == "__main__":
    main()
