"""Score a claim folder downloaded from the real NAS against the same ground truth as the rehearsal.

    python harness/score_nas.py <downloaded claim folder> <case id>

The claim folder must contain CLAIM-DOSSIER.md and the photos/, receipts/ and camera/ subfolders as the NAS
wrote them. Write-order checks need the platform log and are left to the transcript review.
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import score  # noqa: E402
from cases import by_id  # noqa: E402


def main():
    folder, case_id = sys.argv[1], sys.argv[2]
    case = by_id(case_id)
    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, "nas", "home", "user", os.path.basename(os.path.normpath(folder)))
        shutil.copytree(folder, dest)
        res = score.score(case, tmp, [], [])
    for k in ("writes_before_confirmation", "state_changes_ok", "write_expectation_met", "refused"):
        res.pop(k, None)
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
