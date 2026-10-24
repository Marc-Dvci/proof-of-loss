"""Render docs/figures/src/*.html to 2400 x 1600 PNG files (1200 x 800 CSS px at 2x) with headless Chrome,
and check docs/figures/CAPTIONS.md: one caption per figure, 140 characters or fewer.

    python tools/render_figures.py [name ...]
"""
import os
import re
import subprocess
import sys

from PIL import Image

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC = os.path.join(ROOT, "docs", "figures", "src")
OUT = os.path.join(ROOT, "docs", "figures")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def render(name):
    src = os.path.join(SRC, f"{name}.html")
    out = os.path.join(OUT, f"{name}.png")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                    "--window-size=1200,800", f"--screenshot={out}", "file:///" + src.replace("\\", "/")],
                   check=True, capture_output=True)
    w, h = Image.open(out).size
    ok = (w, h) == (2400, 1600)
    print(f"{name}.png {w}x{h} {'ok' if ok else 'WRONG SIZE'}")
    return ok


def check_captions(names):
    path = os.path.join(OUT, "CAPTIONS.md")
    if not os.path.exists(path):
        print("CAPTIONS.md missing")
        return False
    caps = dict(re.findall(r"^- `([a-z0-9-]+)\.png`: (.+)$", open(path, encoding="utf-8").read(), re.M))
    ok = True
    for n in names:
        c = caps.get(n)
        if not c:
            print(f"no caption for {n}")
            ok = False
        elif len(c) > 140:
            print(f"caption for {n} is {len(c)} characters")
            ok = False
    return ok


def main():
    names = sys.argv[1:] or sorted(f[:-5] for f in os.listdir(SRC) if f.endswith(".html"))
    results = [render(n) for n in names]
    caps = check_captions(names)
    sys.exit(0 if all(results) and caps else 1)


if __name__ == "__main__":
    main()
