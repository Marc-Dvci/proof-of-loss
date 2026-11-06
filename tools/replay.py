"""Replay recorded rehearsal cases with no model, no GPU and no key, and check that the score comes out the same.

    python tools/replay.py A1-burglary [--out runs/replay] [--quiet]
    python tools/replay.py all [--quiet]

Each case rebuilds its claim folder on disk under --out: real copies, real SHA-256 hashes, a real CLAIM-DOSSIER.md.
Exit code 1 when a score differs from the recorded one.
"""

import argparse
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "harness"))
from replay import EVIDENCE, conversation, replay_case  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case", help="a case id, or all")
    ap.add_argument("--out", default=os.path.join(ROOT, "runs", "replay"))
    ap.add_argument("--quiet", action="store_true", help="print one line per case, without the conversation")
    ap.add_argument("--evidence", default=EVIDENCE, help="folder of recorded runs")
    args = ap.parse_args()
    known = sorted(d for d in os.listdir(args.evidence) if os.path.isdir(os.path.join(args.evidence, d)))
    if args.case != "all" and args.case not in known:
        ap.error(f"unknown case {args.case}; choose all or one of {', '.join(known)}")
    wanted = known if args.case == "all" else [args.case]
    failed = 0
    for case_id in wanted:
        out_dir = os.path.join(args.out, case_id)
        score, _recorded, differences, left = replay_case(case_id, out_dir, args.evidence)
        if not args.quiet:
            print(f"===== {case_id} =====\n{conversation(out_dir)}\n")
        same = not differences and not left
        failed += not same
        print(f"{case_id}: {'same score as the recorded run' if same else 'DIFFERS'}, folder {out_dir}")
        for key, (was, now) in differences.items():
            print(f"  {key}: recorded {was!r}, replay {now!r}")
        if left:
            print(f"  {left} recorded decisions were left over")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
