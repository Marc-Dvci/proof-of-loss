"""Render submission/proposal.md to a PDF and check the Round 1 limits.

    python tools/build_proposal.py [--chrome PATH]

The ten answers (sections 1 to 10) must total 500 English words or fewer; the third-party licence section is
excluded from the count, as the rules allow. No {{PLACEHOLDER}} may remain. The PDF must be 1 MB or smaller.
"""
import argparse
import html
import os
import re
import subprocess
import sys

import markdown

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC = os.path.join(ROOT, "submission", "proposal.md")
OUT_HTML = os.path.join(ROOT, "build", "proposal.html")
OUT_PDF = os.path.join(ROOT, "build", "Proof-of-Loss-proposal.pdf")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CSS = """
@page { size: A4; margin: 16mm 17mm 15mm 17mm; }
body { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; color: #1b211e; font-size: 9.6pt;
       line-height: 1.42; }
.title { font-size: 21pt; font-weight: 650; letter-spacing: -0.01em; margin: 0; }
.subtitle { font-size: 12pt; color: #3d4a44; margin: 2px 0 6px 0; }
.meta { font-size: 8.6pt; color: #5d6b64; margin-bottom: 10px; border-bottom: 1px solid #d9e2dd; padding-bottom: 8px; }
h2 { font-size: 10.6pt; font-weight: 650; margin: 9px 0 2px 0; color: #0f7a4b; }
p, li { margin: 2px 0; }
ol, ul { margin: 2px 0 2px 18px; padding: 0; }
table { border-collapse: collapse; margin: 3px 0; font-size: 8.8pt; width: 100%; }
td, th { border-bottom: 1px solid #e3e9e6; padding: 2px 6px 2px 0; text-align: left; vertical-align: top; }
th { color: #5d6b64; font-weight: 600; }
hr { border: none; border-top: 1px solid #d9e2dd; margin: 10px 0 6px 0; }
strong { font-weight: 650; }
.count { font-size: 7.6pt; color: #8a9690; margin-top: 8px; }
"""


def split(text):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    meta = dict(line.split(": ", 1) for line in m.group(1).splitlines())
    return meta, m.group(2)


def answer_words(body):
    answers = body.split("\n---\n")[0]
    words = 0
    for block in re.split(r"^## .*$", answers, flags=re.M)[1:]:
        clean = re.sub(r"[|*`#>-]+", " ", block)
        words += len([w for w in clean.split() if re.search(r"[A-Za-z0-9]", w)])
    return words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome", default=CHROME)
    args = ap.parse_args()
    text = open(SRC, encoding="utf-8").read()
    if "{{" in text:
        print("FAIL: placeholder left:", re.findall(r"\{\{[A-Z_]+\}\}", text))
        sys.exit(1)
    meta, body = split(text)
    n = answer_words(body)
    print("answer words:", n)
    if n > 500:
        print("FAIL: over 500 words")
        sys.exit(1)
    content = markdown.markdown(body, extensions=["tables"])
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(meta['title'])}</title>
<style>{CSS}</style></head><body>
<p class="title">{html.escape(meta['title'])}</p><p class="subtitle">{html.escape(meta['subtitle'])}</p>
<p class="meta">{html.escape(meta['entrant'])} · Track: {html.escape(meta['track'])} · UGREEN Hackathon 2026 on AI NAS</p>
{content}
<p class="count">Answers 1 to 10: {n} words.</p>
</body></html>"""
    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(page)
    subprocess.run([args.chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={OUT_PDF}", "file:///" + OUT_HTML.replace("\\", "/")],
                   check=True, capture_output=True)
    size = os.path.getsize(OUT_PDF)
    print("pdf:", OUT_PDF, size, "bytes")
    if size > 1024 * 1024:
        print("FAIL: PDF over 1 MB")
        sys.exit(1)


if __name__ == "__main__":
    main()
