"""Generate the household photos with Qwen-Image 2.1 through a local ComfyUI API, then write them as JPEG
files with the EXIF a phone or camera would record.

    python testdata/gen_photos.py --url http://127.0.0.1:8288 [--only A-T1,A-B4] [--household household_a]

Raw PNGs go to testdata/raw/<household>/<photo id>.png (generation is resumable: an existing PNG is reused).
Final JPEGs go to testdata/archive/<household>/<folder>/<year>/<file name>.
Shots with "text_shot": true (box labels, stamped serials, engravings) use the base model at 30 steps, because
the few-step sampler loses small text; every other shot uses the 6-step turbo LoRA.
"""

import argparse
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid
import zlib

import piexif
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "spec")
RAW = os.path.join(HERE, "raw")
ARCHIVE = os.path.join(HERE, "archive")

UNET = "qwen-image-2.1-Q8_0.gguf"
CLIP = "qwen3vl_8b_int8_convrot.safetensors"
VAE = "QwenImage21\\qwen_image_2.1_vae_bf16.safetensors"
TURBO_LORA = "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors"
SIZES = {"4:3": (1280, 960), "3:4": (960, 1280)}


def graph(prompt, seed, width, height, turbo, prefix):
    g = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET}},
        "2": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "5": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {"clip": ["3", 0], "prompt": prompt, "negative_prompt": "", "resolution": 1024},
        },
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["4", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }
    if turbo:
        g["2"]["inputs"]["model"] = ["30", 0]
        g["30"] = {
            "class_type": "ViggleTurboLora",
            "inputs": {"model": ["1", 0], "lora_name": TURBO_LORA, "strength": 1.0},
        }
        g["31"] = {"class_type": "BasicGuider", "inputs": {"model": ["2", 0], "conditioning": ["5", 0]}}
        g["32"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}}
        g["33"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}}
        g["34"] = {
            "class_type": "ViggleTurboSigmas",
            "inputs": {"latent": ["6", 0], "nodes": "1.0, 0.9375, 0.875, 0.75, 0.5, 0.25"},
        }
        g["7"] = {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["32", 0],
                "guider": ["31", 0],
                "sampler": ["33", 0],
                "sigmas": ["34", 0],
                "latent_image": ["6", 0],
            },
        }
    else:
        g["7"] = {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 0],
                "positive": ["5", 0],
                "negative": ["5", 1],
                "latent_image": ["6", 0],
                "seed": seed,
                "steps": 30,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        }
    return g


class Comfy:
    def __init__(self, url):
        self.url = url.rstrip("/")
        self.client_id = "pol-" + uuid.uuid4().hex[:8]

    def _json(self, method, path, payload=None, timeout=60):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.url + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def run_many(self, g, saves, timeout=3600):
        r = self._json("POST", "/prompt", {"prompt": g, "client_id": self.client_id})
        if r.get("node_errors"):
            raise RuntimeError(json.dumps(r["node_errors"])[:1500])
        pid, start = r["prompt_id"], time.time()
        while time.time() - start < timeout:
            try:
                h = self._json("GET", f"/history/{pid}")
            except OSError as err:
                raise RuntimeError("engine stopped responding") from err
            if h and pid in h:
                entry = h[pid]
                if entry.get("status", {}).get("status_str") == "error":
                    raise RuntimeError(json.dumps(entry["status"])[:1500])
                out = {}
                for key, node in saves.items():
                    im = entry["outputs"][node]["images"][0]
                    q = urllib.parse.urlencode(
                        {
                            "filename": im["filename"],
                            "subfolder": im.get("subfolder", ""),
                            "type": im.get("type", "output"),
                        }
                    )
                    with urllib.request.urlopen(f"{self.url}/view?{q}", timeout=120) as resp:
                        out[key] = resp.read()
                return out
            time.sleep(2.0)
        raise TimeoutError(pid)

    def run(self, g, timeout=1800):
        r = self._json("POST", "/prompt", {"prompt": g, "client_id": self.client_id})
        if r.get("node_errors"):
            raise RuntimeError(json.dumps(r["node_errors"])[:1500])
        pid, start = r["prompt_id"], time.time()
        while time.time() - start < timeout:
            h = self._json("GET", f"/history/{pid}")
            if h and pid in h:
                entry = h[pid]
                if entry.get("status", {}).get("status_str") == "error":
                    raise RuntimeError(json.dumps(entry["status"])[:1500])
                for out in entry.get("outputs", {}).values():
                    for im in out.get("images", []):
                        q = urllib.parse.urlencode(
                            {
                                "filename": im["filename"],
                                "subfolder": im.get("subfolder", ""),
                                "type": im.get("type", "output"),
                            }
                        )
                        with urllib.request.urlopen(f"{self.url}/view?{q}", timeout=120) as resp:
                            return resp.read()
                raise RuntimeError("no image in outputs")
            time.sleep(1.0)
        raise TimeoutError(pid)


def batch_graph(shots, turbo):
    """One prompt for several photos: the text encoder runs once for all of them, then the denoiser samples all of
    them, then the VAE decodes all of them. Gate nodes (XCharWaitFor / XCharWaitLatent, pass-through nodes in the
    engine's custom_nodes) enforce that order, so no model is swapped back to CPU inside a prompt.
    shots: list of (key, prompt, seed, width, height). Returns (graph, {key: SaveImage node id})."""
    g = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "2": {
            "class_type": "QwenImage21Cache",
            "inputs": {"model": ["30", 0] if turbo else ["1", 0], "device": "auto", "dtype": "default"},
        },
    }
    if turbo:
        g["30"] = {
            "class_type": "ViggleTurboLora",
            "inputs": {"model": ["1", 0], "lora_name": TURBO_LORA, "strength": 1.0},
        }
        g["33"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}}
    enc = [f"e{i}" for i in range(len(shots))]
    saves = {}
    for i, (_key, prompt, seed, w, h) in enumerate(shots):
        g[f"e{i}"] = {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {"clip": ["3", 0], "prompt": prompt, "negative_prompt": "", "resolution": 1024},
        }
        g[f"l{i}"] = {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
        g[f"w{i}"] = {
            "class_type": "XCharWaitFor",
            "inputs": {"value": [f"e{i}", 0], **{f"after_{j + 1}": [e, 0] for j, e in enumerate(enc)}},
        }
        if turbo:
            g[f"b{i}"] = {"class_type": "BasicGuider", "inputs": {"model": ["2", 0], "conditioning": [f"w{i}", 0]}}
            g[f"n{i}"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}}
            g[f"s{i}"] = {
                "class_type": "ViggleTurboSigmas",
                "inputs": {"latent": [f"l{i}", 0], "nodes": "1.0, 0.9375, 0.875, 0.75, 0.5, 0.25"},
            }
            g[f"k{i}"] = {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {
                    "noise": [f"n{i}", 0],
                    "guider": [f"b{i}", 0],
                    "sampler": ["33", 0],
                    "sigmas": [f"s{i}", 0],
                    "latent_image": [f"l{i}", 0],
                },
            }
        else:
            g[f"k{i}"] = {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["2", 0],
                    "positive": [f"w{i}", 0],
                    "negative": [f"e{i}", 1],
                    "latent_image": [f"l{i}", 0],
                    "seed": seed,
                    "steps": 30,
                    "cfg": 1.0,
                    "sampler_name": "euler",
                    "scheduler": "simple",
                    "denoise": 1.0,
                },
            }
    ks = [f"k{i}" for i in range(len(shots))]
    for i, (key, *_rest) in enumerate(shots):
        g[f"wl{i}"] = {
            "class_type": "XCharWaitLatent",
            "inputs": {"value": [f"k{i}", 0], **{f"after_{j + 1}": [k, 0] for j, k in enumerate(ks)}},
        }
        # tiled decode keeps the VAE's VRAM need small, so the denoiser is never pushed back to CPU mid-prompt
        g[f"d{i}"] = {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": [f"wl{i}", 0],
                "vae": ["4", 0],
                "tile_size": 512,
                "overlap": 64,
                "temporal_size": 64,
                "temporal_overlap": 8,
            },
        }
        g[f"v{i}"] = {"class_type": "SaveImage", "inputs": {"images": [f"d{i}", 0], "filename_prefix": f"pol/{key}"}}
        saves[key] = f"v{i}"
    return g, saves


class Engine:
    """Start and stop the ComfyUI engine around each batch (POL_ENGINE_CMD is the full launch command line)."""

    def __init__(self, url, cmd, log_path):
        self.url, self.cmd, self.log_path, self.proc = url, cmd, log_path, None

    def up(self):
        try:
            urllib.request.urlopen(self.url + "/system_stats", timeout=2).read()
            return True
        except Exception:
            return False

    def start(self):
        import shlex
        import subprocess

        args = shlex.split(self.cmd, posix=False)
        self.proc = subprocess.Popen(
            [a.strip('"') for a in args],
            stdout=open(self.log_path, "a"),
            stderr=subprocess.STDOUT,
            cwd=os.path.dirname(args[1].strip('"')),
        )
        for _ in range(200):
            if self.up():
                return
            if self.proc.poll() is not None:
                raise RuntimeError("engine exited during start")
            time.sleep(2)
        raise TimeoutError("engine did not start")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=60)
        self.proc = None
        time.sleep(3)


def run_batches(comfy, engine, household, pending, size):
    groups = {}
    for p in pending:
        groups.setdefault(not p["text_shot"], []).append(p)
    for turbo, rows in groups.items():
        for start in range(0, len(rows), size):
            chunk = rows[start : start + size]
            shots = [
                (p["id"], p["prompt"], zlib.crc32(p["id"].encode()) % (2**31), *SIZES[p.get("aspect", "4:3")])
                for p in chunk
            ]
            g, saves = batch_graph(shots, turbo)
            engine.start()
            t0 = time.time()
            try:
                images = comfy.run_many(g, saves, timeout=3600)
            finally:
                engine.stop()
            for key, png in images.items():
                with open(os.path.join(RAW, household, f"{key}.png"), "wb") as f:
                    f.write(png)
            print(
                f"batch {'turbo' if turbo else 'base'} {len(chunk)} photos {time.time() - t0:5.1f}s: "
                f"{', '.join(images)}",
                flush=True,
            )


def _rational(x, den=10000):
    return (int(round(x * den)), den)


def _dms(value):
    value = abs(value)
    d = int(value)
    m = int((value - d) * 60)
    s = (value - d - m / 60) * 3600
    return ((d, 1), (m, 1), _rational(s, 100))


def exif_bytes(p):
    taken = dt.datetime.fromisoformat(p["taken"])
    stamp = taken.strftime("%Y:%m:%d %H:%M:%S").encode()
    dev = p["device"]
    zeroth = {
        piexif.ImageIFD.Make: dev["make"].encode(),
        piexif.ImageIFD.Model: dev["model"].encode(),
        piexif.ImageIFD.DateTime: stamp,
        piexif.ImageIFD.Software: b"1.0",
    }
    exif = {
        piexif.ExifIFD.DateTimeOriginal: stamp,
        piexif.ExifIFD.DateTimeDigitized: stamp,
        piexif.ExifIFD.LensModel: dev["lens"].encode(),
    }
    if dev.get("body_serial"):
        exif[piexif.ExifIFD.BodySerialNumber] = dev["body_serial"].encode()
    gps = {}
    if p.get("gps"):
        lat, lon = p["gps"]
        gps = {
            piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude: _dms(lat),
            piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude: _dms(lon),
        }
    return piexif.dump({"0th": zeroth, "Exif": exif, "GPS": gps, "1st": {}, "thumbnail": None})


def file_name(p):
    taken = dt.datetime.fromisoformat(p["taken"])
    if p["device"]["make"] == "Orvane":
        return f"OXV_{zlib.crc32(p['id'].encode()) % 10000:04d}.JPG"
    return taken.strftime("IMG_%Y%m%d_%H%M%S.jpg")


def archive_path(household, p):
    taken = dt.datetime.fromisoformat(p["taken"])
    return os.path.join(ARCHIVE, household, p["folder"], str(taken.year), file_name(p))


def write_jpeg(png_bytes, p, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    im.save(dest, "JPEG", quality=88, exif=exif_bytes(p))
    ts = dt.datetime.fromisoformat(p["taken"]).timestamp()
    os.utime(dest, (ts, ts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8288")
    ap.add_argument("--household", action="append")
    ap.add_argument("--only", default="")
    ap.add_argument("--exif-only", action="store_true", help="rewrite JPEGs from existing PNGs without generating")
    ap.add_argument(
        "--batch",
        type=int,
        default=0,
        help="generate missing photos in merged prompts of this size, restarting the engine between "
        "batches (needs POL_ENGINE_CMD)",
    )
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    comfy = Comfy(args.url)
    index = {}
    for household in args.household or ["household_a", "household_b"]:
        spec = json.load(open(os.path.join(SPEC, f"{household}.json"), encoding="utf-8"))
        os.makedirs(os.path.join(RAW, household), exist_ok=True)
        if args.batch and not args.exif_only:
            pending = [
                p
                for p in spec["photos"]
                if (not only or p["id"] in only) and not os.path.exists(os.path.join(RAW, household, f"{p['id']}.png"))
            ]
            engine = Engine(args.url, os.environ["POL_ENGINE_CMD"], os.path.join(HERE, "..", "runs", "engine.log"))
            run_batches(comfy, engine, household, pending, args.batch)
        rows = []
        for p in spec["photos"]:
            if only and p["id"] not in only:
                continue
            raw = os.path.join(RAW, household, f"{p['id']}.png")
            if not os.path.exists(raw) and not args.exif_only:
                w, h = SIZES[p.get("aspect", "4:3")]
                seed = zlib.crc32(p["id"].encode()) % (2**31)
                t0 = time.time()
                png = comfy.run(graph(p["prompt"], seed, w, h, turbo=not p["text_shot"], prefix=f"pol/{p['id']}"))
                with open(raw, "wb") as f:
                    f.write(png)
                print(f"{p['id']:8s} {'base' if p['text_shot'] else 'turbo'} {time.time() - t0:5.1f}s", flush=True)
            if os.path.exists(raw):
                dest = archive_path(household, p)
                write_jpeg(open(raw, "rb").read(), p, dest)
                rows.append(
                    {
                        "id": p["id"],
                        "path": os.path.relpath(dest, os.path.join(ARCHIVE, household)).replace("\\", "/"),
                        "items": p["items"],
                        "taken": p["taken"],
                        "gps": p["gps"],
                        "device": p["device"],
                    }
                )
        index[household] = rows
        if not only:
            with open(os.path.join(SPEC, f"{household}_photo_index.json"), "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=1)
        print(household, len(rows), "photos written", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
