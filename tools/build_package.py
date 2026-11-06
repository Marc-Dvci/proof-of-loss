"""Build the Skill package ZIP and check it against the Hackathon limits and the official checker.

    python tools/build_package.py [--kit ../uliya-skill-kit-0.7.3] [--out build]

Checks: Markdown files only; at most 100 files; each file at most 1 MB; package and ZIP at most 10 MB each;
every reference linked from SKILL.md; no credential-like strings; the kit's check-skill.mjs returns static-pass
with zero errors and zero warnings. Prints the ZIP path, size and SHA-256.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SKILL = os.path.join(ROOT, "skill", "proof-of-loss")
MB = 1024 * 1024


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default=os.path.join(ROOT, "..", "uliya-skill-kit-0.7.3"))
    ap.add_argument("--out", default=os.path.join(ROOT, "build"))
    args = ap.parse_args()

    files = []
    for dirpath, _, names in os.walk(SKILL):
        for n in names:
            files.append(os.path.join(dirpath, n))
    rel = sorted(os.path.relpath(p, SKILL).replace("\\", "/") for p in files)
    if len(rel) > 100:
        fail(f"{len(rel)} files, limit 100")
    total = 0
    for r in rel:
        p = os.path.join(SKILL, r)
        size = os.path.getsize(p)
        total += size
        if not r.endswith(".md"):
            fail(f"non-Markdown file {r}")
        if size > MB:
            fail(f"{r} is {size} bytes, limit 1 MB")
        text = open(p, encoding="utf-8").read()
        if re.search(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*['\"][^'\"]+['\"]", text):
            fail(f"credential-like string in {r}")
    if total > 10 * MB:
        fail(f"package is {total} bytes, limit 10 MB")
    skill_md = open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8").read()
    for r in rel:
        if r.startswith("references/") and f"({r})" not in skill_md:
            fail(f"{r} is not linked from SKILL.md")

    node = subprocess.run(
        ["node", os.path.join(args.kit, "scripts", "check-skill.mjs"), SKILL],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    try:
        check = json.loads(node.stdout)
    except json.JSONDecodeError:
        fail("checker output was not JSON: " + node.stdout[:500] + node.stderr[:500])
    if check["status"] != "static-pass" or check["summary"]["errors"] or check["summary"]["warnings"]:
        fail("checker: " + json.dumps(check["summary"]) + " " + json.dumps(check["diagnostics"])[:1500])

    os.makedirs(args.out, exist_ok=True)
    version = re.search(r"^version:\s*(\S+)", skill_md, re.M)
    zip_path = os.path.join(args.out, "proof-of-loss.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for r in rel:
            info = zipfile.ZipInfo(f"proof-of-loss/{r}", date_time=(2026, 11, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(os.path.join(SKILL, r), "rb") as f:
                z.writestr(info, f.read())
    zsize = os.path.getsize(zip_path)
    if zsize > 10 * MB:
        fail(f"zip is {zsize} bytes, limit 10 MB")
    digest = hashlib.sha256(open(zip_path, "rb").read()).hexdigest()
    lines = len(skill_md.split("---", 2)[2].splitlines())
    print(
        json.dumps(
            {
                "zip": zip_path,
                "zip_bytes": zsize,
                "package_bytes": total,
                "files": rel,
                "skill_md_body_lines": lines,
                "checker": check["status"],
                "checker_summary": check["summary"],
                "sha256": digest,
                "version": version.group(1) if version else None,
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
