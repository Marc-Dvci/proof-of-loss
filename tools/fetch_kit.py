"""Download the official UGREEN Skill Developer Package next to this folder, where the tools and the tests expect it.

    python tools/fetch_kit.py

It holds the capability catalog the stand-in serves and the official checker. Nothing happens when it is already there.
"""

import io
import os
import shutil
import urllib.request
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
URL = "https://cdn.shopify.com/s/files/1/0630/9416/1602/files/uliya-skill-kit-0.7.3-en.zip"
DEST = os.path.normpath(os.path.join(ROOT, "..", "uliya-skill-kit-0.7.3"))


def main():
    if os.path.isdir(DEST):
        print("already there:", DEST)
        return
    with urllib.request.urlopen(URL, timeout=120) as r:
        archive = zipfile.ZipFile(io.BytesIO(r.read()))
    parent = os.path.dirname(DEST)
    archive.extractall(parent)
    shutil.move(os.path.join(parent, "uliya-skill-kit"), DEST)
    print("fetched:", DEST)


if __name__ == "__main__":
    main()
