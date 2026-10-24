"""Zip each test household for upload to the NAS home folder on test day.

    python testdata/make_upload_pack.py      # build/testdata-household_a.zip, build/testdata-household_b.zip

Each ZIP holds Photos/ and Documents/ exactly as they should sit in the user's home folder. File times are
kept, so the NAS sees the same modification times as the EXIF capture times.
"""
import os
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def main():
    out_dir = os.path.join(ROOT, "build")
    os.makedirs(out_dir, exist_ok=True)
    for household in ("household_a", "household_b"):
        src = os.path.join(ROOT, "testdata", "archive", household)
        out = os.path.join(out_dir, f"testdata-{household}.zip")
        n = 0
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
            for dirpath, _, files in os.walk(src):
                for f in sorted(files):
                    full = os.path.join(dirpath, f)
                    z.write(full, os.path.relpath(full, src).replace("\\", "/"))
                    n += 1
        print(out, n, "files", os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    main()
