"""Build the AI index of one household archive, the way the NAS album indexes photos on upload.

Every image under the home folder gets objects, scene, colours and visible text from a vision model. Every
document gets its text (PDF text layer, or OCR for photographed receipts). The index is what photo search and
evidence collection read; visual checks still look at the image itself at run time.

    python harness/build_index.py --household household_a --vlm-url http://127.0.0.1:8098
"""
import argparse
import json
import os
import sys

import piexif
from pypdf import PdfReader

sys.path.insert(0, os.path.dirname(__file__))
from llm import LLM  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TESTDATA = os.path.join(HERE, "..", "testdata")

TAG_PROMPT = ("Index this photo for a photo library search engine. Reply with one JSON object: "
              "{\"objects\": [up to 12 short nouns for the visible objects, most important first], "
              "\"scene\": \"one sentence describing the scene\", \"colors\": \"main colours of the main objects\", "
              "\"text\": \"all legible text in the image, exactly as written, or empty\"}")


def exif_row(path):
    ex = piexif.load(path)
    dec = lambda v: v.decode(errors="replace") if isinstance(v, bytes) else v
    taken = dec(ex.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal))
    gps = ex.get("GPS", {})
    row = {"make": dec(ex.get("0th", {}).get(piexif.ImageIFD.Make)),
           "model": dec(ex.get("0th", {}).get(piexif.ImageIFD.Model)),
           "taken": taken.replace(":", "-", 2).replace(" ", "T") if taken else None}
    if gps.get(piexif.GPSIFD.GPSLatitude):
        conv = lambda d: d[0][0] / d[0][1] + d[1][0] / d[1][1] / 60 + d[2][0] / d[2][1] / 3600
        row["gps"] = [round(conv(gps[piexif.GPSIFD.GPSLatitude]), 5), round(conv(gps[piexif.GPSIFD.GPSLongitude]), 5)]
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--household", required=True)
    ap.add_argument("--vlm-url", default="http://127.0.0.1:8098")
    args = ap.parse_args()
    root = os.path.join(TESTDATA, "archive", args.household)
    out_path = os.path.join(TESTDATA, "index", f"{args.household}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    index = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {"photos": {}, "docs": {}}
    vlm = LLM(args.vlm_url, max_tokens=500)
    for dirpath, _, files in os.walk(root):
        for n in sorted(files):
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, root).replace("\\", "/")
            low = n.lower()
            if low.endswith((".jpg", ".jpeg", ".png")) and rel not in index["photos"]:
                raw = vlm.vision(full, TAG_PROMPT, max_tokens=500)
                try:
                    tags = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
                except json.JSONDecodeError:
                    tags = {"objects": [], "scene": raw[:300], "colors": "", "text": ""}
                tags.update(exif_row(full))
                index["photos"][rel] = tags
                print("photo", rel, tags.get("objects", [])[:5], flush=True)
            if rel.startswith("Documents/") and rel not in index["docs"]:
                if low.endswith(".pdf"):
                    text = "\n".join(p.extract_text() or "" for p in PdfReader(full).pages)
                elif low.endswith((".jpg", ".jpeg", ".png")):
                    text = vlm.vision(full, "Transcribe all text in this image exactly, line by line, keeping each "
                                            "amount on the line it belongs to.", max_tokens=800)
                else:
                    continue
                index["docs"][rel] = text
                print("doc  ", rel, len(text), flush=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=1, ensure_ascii=False)
    print(len(index["photos"]), "photos,", len(index["docs"]), "documents indexed ->", out_path)


if __name__ == "__main__":
    main()
