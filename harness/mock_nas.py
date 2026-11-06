"""A stand-in for the UGOS CLI layer, used to rehearse the Skill before NAS access.

It serves the subset of catalog actions that the proof-of-loss experts call, over a per-run copy of a
synthetic household archive. Each action returns the catalog envelope {"ok": true, "data": ...} or
{"ok": false, "error": ...}. State-change actions pass through an approval gate driven by the catalog's own
"approval" field, and every call is appended to an action log that the scorer reads.

Photo search runs over an AI index (objects, scene, visible text) built once per household by a vision model,
the way the NAS album indexes photos on upload. Visual checks and OCR call the vision model live.
"""

import datetime as dt
import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import time
import uuid

import piexif

KIT_DIR = os.environ.get("POL_KIT_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "uliya-skill-kit-0.7.3"))
CATALOG_PATH = os.path.join(KIT_DIR, "data", "capability-catalog.json")

STOP = set(
    "a an and the of for to in on at by with from this that these those is are was were be it its as or "
    "any all each one per into only your user their there here find look search show return photo photos "
    "image images file files household item".split()
)
SYNONYMS = {
    "tv": ["television", "screen", "tv"],
    "television": ["tv", "television", "screen"],
    "bike": ["bicycle", "bike", "cycle"],
    "bicycle": ["bike", "bicycle"],
    "watch": ["wristwatch", "watch"],
    "wristwatch": ["watch", "wristwatch"],
    "sofa": ["couch", "sofa"],
    "couch": ["sofa", "couch"],
    "laptop": ["laptop", "notebook", "computer"],
    "camera": ["camera"],
    "guitar": ["guitar"],
    "rug": ["rug", "carpet"],
    "carpet": ["rug", "carpet"],
    "espresso": ["espresso", "coffee machine"],
    "headphones": ["headphones", "headset"],
}


def tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in STOP and len(t) > 1]


def load_catalog():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        cat = json.load(f)
    actions = {}
    for c in cat["clis"]:
        for a in c["actions"]:
            actions[(c["name"], a["name"])] = {
                "agent": c["agent"],
                "effect": a.get("effect"),
                "approval": a.get("approval"),
                "params": {p["name"]: p for p in a.get("parameters", [])},
            }
    return actions


class Gate:
    """Platform approval. policy(op) -> 'approve' | 'deny' | 'defer'. A deferred op is approved the next time."""

    def __init__(self, policy):
        self.policy = policy
        self.deferred = set()
        self.requests = []

    def check(self, op):
        key = json.dumps([op["cli"], op["action"], op["args"]], sort_keys=True)
        if key in self.deferred:
            decision = "approve"
        else:
            decision = self.policy(op)
            if decision == "defer":
                self.deferred.add(key)
        self.requests.append({"op": op, "decision": decision, "t": time.time()})
        return decision


class MockNAS:
    def __init__(self, spec, archive_dir, run_dir, index, llm, gate, log, vlm=None):
        self.spec = spec
        self.llm = llm
        self.vlm = vlm or llm
        self.gate = gate
        self.log = log
        self.catalog = load_catalog()
        self.user = "claire" if "Varga" in json.dumps(spec) or spec["name"].startswith("Household A") else "jonas"
        self.home = f"/home/{self.user}"
        self.root = os.path.join(run_dir, "nas")
        home_real = self._real(self.home)
        if os.path.exists(self.root):
            shutil.rmtree(self.root)
        shutil.copytree(archive_dir, home_real)
        self.index = index  # {"photos": {rel: {...}}, "docs": {rel: text}}
        self.cache_path = os.path.join(
            os.path.dirname(archive_dir), f"{os.path.basename(archive_dir)}_vision_cache.json"
        )
        self.cache = {}
        if os.path.exists(self.cache_path):
            with open(self.cache_path, encoding="utf-8") as f:
                self.cache = json.load(f)
        self.albums = []
        self.cams = {c["camera_id"]: c for c in spec.get("cameras", [])}

    # ------------------------------------------------------------------ paths
    def _real(self, vpath):
        vpath = "/" + vpath.strip().lstrip("/") if vpath else self.home
        if vpath in ("/current", "/~"):
            vpath = self.home
        real = os.path.normpath(os.path.join(self.root, vpath.lstrip("/")))
        if not real.startswith(os.path.normpath(self.root)):
            raise PermissionError(f"path outside the NAS: {vpath}")
        return real

    def _virtual(self, real):
        rel = os.path.relpath(real, self.root).replace("\\", "/")
        return "/" + rel

    def _rel_home(self, vpath):
        return os.path.relpath(self._real(vpath), self._real(self.home)).replace("\\", "/")

    def _vision_cached(self, key, fn):
        if key not in self.cache:
            self.cache[key] = fn()
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=0)
        return self.cache[key]

    # ------------------------------------------------------------------ dispatch
    def invoke(self, agent, cli, action, args):
        args = args or {}
        meta = self.catalog.get((cli, action))
        entry = {"t": time.time(), "agent": agent, "cli": cli, "action": action, "args": args}
        if meta is None:
            result = {"ok": False, "error": {"code": "UNKNOWN_ACTION", "message": f"{cli} has no action {action}"}}
        elif meta["agent"] != agent:
            result = {"ok": False, "error": {"code": "FORBIDDEN", "message": f"{cli} is owned by {meta['agent']}"}}
        elif self._bad_args(meta, args):
            result = {"ok": False, "error": {"code": "INVALID_ARGUMENT", "message": self._bad_args(meta, args)}}
        else:
            args = entry["args"] = self._normalise_args(meta, args)
            entry["effect"], entry["approval"] = meta["effect"], meta["approval"]
            if meta["effect"] == "state-change" or (
                meta["effect"] == "mixed" and meta["approval"] != "none" and action in ("translate", "writing")
            ):
                decision = self.gate.check({"agent": agent, "cli": cli, "action": action, "args": args})
                entry["decision"] = decision
                if decision == "deny":
                    result = {
                        "ok": False,
                        "error": {"code": "APPROVAL_DENIED", "message": "the user declined this operation"},
                    }
                    return self._done(entry, result)
                if decision == "defer":
                    result = {
                        "ok": False,
                        "error": {
                            "code": "APPROVAL_PENDING",
                            "message": "waiting for the user to approve this operation",
                        },
                    }
                    return self._done(entry, result)
            fn = getattr(self, "_" + (cli + "_" + action).replace("-", "_"), None)
            if fn is None:
                result = {
                    "ok": False,
                    "error": {"code": "UNSUPPORTED", "message": f"{cli} {action} is not served here"},
                }
            else:
                try:
                    result = {"ok": True, "data": fn(args)}
                except FileNotFoundError as e:
                    result = {"ok": False, "error": {"code": "NOT_FOUND", "message": str(e)}}
                except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
                    result = {"ok": False, "error": {"code": "BAD_REQUEST", "message": f"{type(e).__name__}: {e}"}}
        return self._done(entry, result)

    @staticmethod
    def _bad_args(meta, args):
        """Reject what the CLI parser would reject: unknown parameters, missing required ones, values outside an enum."""
        spec = meta.get("params") or {}
        if not spec:
            return None
        valid = ", ".join(f"--{n}{' (required)' if p.get('required') else ''}" for n, p in spec.items())
        unknown = [k for k in args if k not in spec]
        if unknown:
            return f"unknown parameter {', '.join('--' + k for k in unknown)}; this action takes {valid}"
        missing = [n for n, p in spec.items() if p.get("required") and args.get(n) in (None, "", [])]
        if missing:
            return f"missing required parameter {', '.join('--' + n for n in missing)}; this action takes {valid}"
        for n, v in args.items():
            enum = spec[n].get("enum")
            vals = v if isinstance(v, list) else [v]
            if enum and any(str(x) not in enum for x in vals):
                return f"--{n} must be one of {', '.join(enum)}"
            if isinstance(v, list) and len(v) > 1 and not spec[n].get("repeatable"):
                return f"--{n} takes one value"
        return None

    @staticmethod
    def _normalise_args(meta, args):
        """A one-element list given to a flag that is not repeatable is that single value."""
        spec = meta.get("params") or {}
        return {
            k: (v[0] if isinstance(v, list) and len(v) == 1 and k in spec and not spec[k].get("repeatable") else v)
            for k, v in args.items()
        }

    def _done(self, entry, result):
        entry["ok"] = result["ok"]
        if not result["ok"]:
            entry["error"] = result["error"]
        self.log(entry)
        return result

    @staticmethod
    def _list(v):
        if v is None:
            return []
        if isinstance(v, list):
            out = []
            for x in v:
                out.extend(MockNAS._list(x))
            return out
        if isinstance(v, str) and v.strip().startswith("["):
            try:
                return MockNAS._list(json.loads(v))
            except json.JSONDecodeError:
                pass
        if isinstance(v, dict):
            return [v.get("path") or v.get("value") or json.dumps(v)]
        return [v]

    # ------------------------------------------------------------------ file-workflow / ug-filesystem
    def _file_workflow_get_user_dir(self, a):
        real = self._real(self.home)
        return {
            "path": self.home,
            "fileId": "dir:home",
            "children": sorted(n for n in os.listdir(real) if os.path.isdir(os.path.join(real, n))),
        }

    def _entry(self, real):
        st = os.stat(real)
        return {
            "name": os.path.basename(real),
            "path": self._virtual(real),
            "type": "dir" if os.path.isdir(real) else "file",
            "size": st.st_size,
            "mtime": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "fileId": "file:" + hashlib.md5(self._virtual(real).encode()).hexdigest()[:12],
        }

    def _ug_filesystem_ls(self, a):
        real = self._real(a.get("path"))
        if not os.path.isdir(real):
            raise FileNotFoundError(a.get("path"))
        out = []
        depth = int(a.get("max-depth") or (5 if str(a.get("recursive")).lower() == "true" else 1))
        for dirpath, dirs, files in os.walk(real):
            level = os.path.relpath(dirpath, real).count(os.sep) + (0 if dirpath == real else 1)
            if level >= depth:
                dirs[:] = []
            for n in sorted(dirs) + sorted(files):
                out.append(self._entry(os.path.join(dirpath, n)))
        return {"items": out[: int(a.get("limit") or 200)]}

    KIND_EXT = {
        "image": (".jpg", ".jpeg", ".png", ".heic"),
        "video": (".mp4", ".mov"),
        "documents": (".pdf", ".docx", ".txt", ".md", ".jpg"),
        "audio": (".m4a", ".mp3"),
    }

    def _ug_filesystem_find(self, a):
        real = self._real(a.get("path"))
        pattern = a.get("pattern") or "*"
        kind = a.get("type") or "all"
        start, end = a.get("start-timestamp"), a.get("end-timestamp")
        out = []
        for dirpath, _dirs, files in os.walk(real):
            for n in files:
                p = os.path.join(dirpath, n)
                if not fnmatch.fnmatch(n.lower(), pattern.lower()):
                    continue
                if kind in self.KIND_EXT and not n.lower().endswith(self.KIND_EXT[kind]):
                    continue
                mt = os.stat(p).st_mtime
                if start and mt < float(start):
                    continue
                if end and mt > float(end):
                    continue
                out.append(self._entry(p))
        return {"items": out[: int(a.get("limit") or 200)], "total": len(out)}

    def _ug_filesystem_stat(self, a):
        real = self._real(a["path"])
        if not os.path.exists(real):
            raise FileNotFoundError(a["path"])
        return self._entry(real)

    def _ug_filesystem_cat(self, a):
        real = self._real(a["path"])
        with open(real, "rb") as f:
            f.seek(int(a.get("offset") or 0))
            raw = f.read(int(a.get("length") or 4096))
        try:
            return {"path": a["path"], "content": raw.decode("utf-8")}
        except UnicodeDecodeError as err:
            raise ValueError("binary file; use a document or photo action to read it") from err

    def _hash(self, a, algo):
        real = self._real(a["path"])
        if not os.path.isfile(real):
            raise FileNotFoundError(a["path"])
        h = hashlib.new(algo)
        with open(real, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return {"path": a["path"], algo: h.hexdigest(), "size": os.path.getsize(real)}

    def _ug_filesystem_sha256sum(self, a):
        return self._hash(a, "sha256")

    def _ug_filesystem_md5sum(self, a):
        return self._hash(a, "md5")

    def _ug_filesystem_mkdir(self, a):
        real = self._real(a["path"])
        os.makedirs(real, exist_ok=True)
        return {"path": self._virtual(real)}

    def _ug_filesystem_cpmv(self, a):
        src, dst = self._real(a["src"]), self._real(a["dst"])
        if not os.path.exists(src):
            raise FileNotFoundError(a["src"])
        if os.path.isdir(dst) or a["dst"].endswith("/"):
            os.makedirs(dst, exist_ok=True)
            dst = os.path.join(dst, os.path.basename(src))
        if os.path.exists(dst) and str(a.get("overwrite")).lower() != "true":
            raise ValueError(f"destination exists: {self._virtual(dst)}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if (a.get("type") or "move") == "copy":
            shutil.copy2(src, dst)
        else:
            shutil.move(src, dst)
        return {"src": a["src"], "dst": self._virtual(dst), "type": a.get("type") or "move"}

    def _ug_filesystem_echo(self, a):
        real = self._real(a["path"])
        os.makedirs(os.path.dirname(real), exist_ok=True)
        mode = "a" if a.get("write-mode") == "append" else "w"
        with open(real, mode, encoding="utf-8") as f:
            f.write(a.get("content") or "")
        return {"path": self._virtual(real), "size": os.path.getsize(real)}

    def _ug_filesystem_touch(self, a):
        return self._ug_filesystem_echo({"path": a["path"], "content": a.get("content") or ""})

    def _ug_filesystem_chtimes(self, a):
        real = self._real(a["path"])
        os.utime(real, (float(a.get("atime") or time.time()), float(a.get("mtime") or time.time())))
        return {"path": a["path"]}

    def _ug_filesystem_del(self, a):
        real = self._real(a["path"])
        os.remove(real)
        return {"path": a["path"], "final_path": "#recycle/" + os.path.basename(real)}

    # ------------------------------------------------------------------ ug-photo
    def _photo_rows(self):
        for rel, row in self.index["photos"].items():
            yield rel, row

    def _photo_item(self, rel, row):
        return {
            "path": f"{self.home}/{rel}",
            "file_name": os.path.basename(rel),
            "taken": row.get("taken"),
            "camera_model": row.get("model"),
            "gps": row.get("gps"),
        }

    @staticmethod
    def _expand(words):
        out = set()
        for w in words:
            out.update(SYNONYMS.get(w, [w]))
        return out

    def _match_score(self, row, query_words):
        def flat(v):
            return " ".join(map(str, v)) if isinstance(v, list) else str(v or "")

        hay = " ".join(flat(row.get(k)) for k in ("objects", "scene", "colors")).lower()
        hay_tokens = set(tokens(hay))
        score = 0.0
        for w in query_words:
            alts = self._expand([w])
            if any(x in hay_tokens or (" " in x and x in hay) for x in alts):
                score += 1.0
        return score

    def _time_ok(self, row, a):
        t = row.get("taken") or ""
        s, e = a.get("start-time"), a.get("end-time")
        if s and t and t[: len(str(s))] < str(s)[:19]:
            return False
        if e and t and t[:19] > str(e)[:19]:
            return False
        return True

    def _dir_ok(self, rel, a):
        dirs = [str(d) for d in self._list(a.get("dir")) + self._list(a.get("path"))]
        if not dirs:
            return True
        full = f"{self.home}/{rel}"
        return any(full.startswith(d.rstrip("/")) or d.strip("/") in full for d in dirs)

    def _ug_photo_search_picture(self, a):
        objs = [str(x) for x in self._list(a.get("ai-object-name"))]
        ocr = [str(x).lower() for x in self._list(a.get("ocr-contains"))]
        names = [str(x).lower() for x in self._list(a.get("file-name-contains"))]
        cams = [str(x).lower() for x in self._list(a.get("camera-model"))]
        hits = []
        for rel, row in self._photo_rows():
            if not self._time_ok(row, a) or not self._dir_ok(rel, a):
                continue
            score = 0.0
            if objs:
                s = self._match_score(row, tokens(" ".join(objs)))
                if s <= 0:
                    continue
                score += s
            if ocr:
                text = " ".join(map(str, row["text"])) if isinstance(row.get("text"), list) else (row.get("text") or "")
                text = text.lower().replace(" ", "")
                if not any(o.replace(" ", "") in text for o in ocr):
                    continue
                score += 2
            if names and not any(n in rel.lower() for n in names):
                continue
            if cams:
                if not any(
                    c in (row.get("model") or "").lower()
                    or c in f"{row.get('make', '')} {row.get('model', '')}".lower()
                    for c in cams
                ):
                    continue
                score += 1
            hits.append((score, row.get("taken") or "", rel, row))
        hits.sort(key=lambda h: (-h[0], h[1]), reverse=False)
        size = int(a.get("page-size") or 20)
        return {"items": [self._photo_item(rel, row) for _, _, rel, row in hits[:size]], "total": len(hits)}

    def _ug_photo_search_screen(self, a):
        q = tokens(a.get("keyword") or "")
        if not q:
            raise ValueError("keyword is required")
        cat = a.get("category") or "scene"
        hits = []
        for rel, row in self._photo_rows():
            if not self._dir_ok(rel, a):
                continue
            if cat == "ocr":
                text = (
                    " ".join(map(str, row["text"])) if isinstance(row.get("text"), list) else (row.get("text") or "")
                ).lower()
                s = sum(1 for w in q if w in text)
            else:
                s = self._match_score(row, q)
            if s >= max(1.0, 0.5 * len(set(q))):
                hits.append((s, rel, row))
        hits.sort(key=lambda h: -h[0])
        size = int(a.get("page-size") or 20)
        return {"items": [self._photo_item(rel, row) for _, rel, row in hits[:size]], "total": len(hits)}

    def _exif(self, real):
        ex = piexif.load(real)

        def g(ifd, tag):
            return ex.get(ifd, {}).get(tag)

        def dec(v):
            return v.decode(errors="replace") if isinstance(v, bytes) else v

        out = {
            "DateTimeOriginal": dec(g("Exif", piexif.ExifIFD.DateTimeOriginal)),
            "Make": dec(g("0th", piexif.ImageIFD.Make)),
            "Model": dec(g("0th", piexif.ImageIFD.Model)),
            "LensModel": dec(g("Exif", piexif.ExifIFD.LensModel)),
            "BodySerialNumber": dec(g("Exif", piexif.ExifIFD.BodySerialNumber)),
        }
        lat, lon = g("GPS", piexif.GPSIFD.GPSLatitude), g("GPS", piexif.GPSIFD.GPSLongitude)
        if lat and lon:

            def conv(dms):
                return dms[0][0] / dms[0][1] + dms[1][0] / dms[1][1] / 60 + dms[2][0] / dms[2][1] / 3600

            la, lo = conv(lat), conv(lon)
            if g("GPS", piexif.GPSIFD.GPSLatitudeRef) == b"S":
                la = -la
            if g("GPS", piexif.GPSIFD.GPSLongitudeRef) == b"W":
                lo = -lo
            out["GPS"] = {"latitude": round(la, 6), "longitude": round(lo, 6)}
        return {k: v for k, v in out.items() if v is not None}

    def _ug_photo_meta(self, a):
        out = []
        for p in self._list(a.get("path")):
            real = self._real(p)
            if not os.path.isfile(real):
                out.append({"path": p, "error": "not found"})
                continue
            out.append({"path": p, "exif": self._exif(real)})
        return {"items": out}

    def _ug_photo_vision_ocr(self, a):
        p = self._list(a.get("path"))[0]
        real = self._real(p)
        if not os.path.isfile(real):
            raise FileNotFoundError(p)
        rel = self._rel_home(p)
        text = self._vision_cached(
            "ocr::" + rel,
            lambda: self.vlm.vision(
                real,
                "Transcribe all text visible in this image exactly, line by line. If there is no text, reply NO TEXT.",
            ),
        )
        return {"path": p, "text": text}

    def _ug_photo_vision_vlm(self, a):
        p = self._list(a.get("path"))[0]
        real = self._real(p)
        if not os.path.isfile(real):
            raise FileNotFoundError(p)
        prompt = a.get("prompt") or "Describe this image."
        rel = self._rel_home(p)
        key = "vlm::" + rel + "::" + hashlib.sha1(prompt.encode()).hexdigest()[:16]
        return {"path": p, "answer": self._vision_cached(key, lambda: self.vlm.vision(real, prompt))}

    def _ug_photo_create_album(self, a):
        items = [str(x) for x in self._list(a.get("add-item"))]
        missing = [p for p in items if not os.path.isfile(self._real(p))]
        if missing:
            raise FileNotFoundError(", ".join(missing))
        album = {"album_uuid": "alb_" + uuid.uuid4().hex[:10], "album_name": a.get("album-name"), "items": items}
        self.albums.append(album)
        return {"status": "completed", "album_uuid": album["album_uuid"], "photo_count": len(items)}

    def _ug_photo_albums(self, a):
        return {
            "items": [
                {"album_uuid": x["album_uuid"], "name": x["album_name"], "count": len(x["items"])} for x in self.albums
            ]
        }

    # ------------------------------------------------------------------ ug-document
    def _doc_text(self, p):
        rel = self._rel_home(p)
        if rel in self.index["docs"]:
            return self.index["docs"][rel]
        real = self._real(p)
        if not os.path.isfile(real):
            raise FileNotFoundError(p)
        if real.lower().endswith((".jpg", ".jpeg", ".png")):
            return self._ug_photo_vision_ocr({"path": p})["text"]
        if real.lower().endswith(".pdf"):
            from pypdf import PdfReader

            return "\n".join(page.extract_text() or "" for page in PdfReader(real).pages)
        with open(real, encoding="utf-8", errors="replace") as f:
            return f.read()

    EXTRACT_PROMPT = (
        "You extract purchase facts from one document. Use only text that appears in the document. "
        "Copy amounts, dates, document numbers and serial numbers exactly as printed. Use null for anything absent. "
        'Reply with one JSON object: {"document_type": str, "merchant": str|null, "document_number": str|null, '
        '"date": str|null, "currency": str|null, "total": str|null, "line_items": [{"description": str, '
        '"quantity": str|null, "unit_price": str|null, "amount": str|null, "serial_number": str|null}], '
        '"warranty_end": str|null, "delivery_date": str|null, "tracking_number": str|null, '
        '"other_text": str|null}. Put any line that is not a purchase fact in other_text.'
    )

    def _ug_document_extract(self, a):
        files = [str(x) for x in self._list(a.get("file"))]
        schema = a.get("schema") or "auto"
        out, failures = [], []
        for p in files:
            try:
                text = self._doc_text(p)
            except FileNotFoundError:
                failures.append({"file": p, "error": "not found"})
                continue
            rel = self._rel_home(p)
            key = "extract::" + rel
            fields = self._vision_cached(
                key,
                lambda: self.llm.chat_json(
                    [
                        {"role": "system", "content": self.EXTRACT_PROMPT},
                        {
                            "role": "user",
                            "content": f"Schema hint: {schema}\n\nDocument {os.path.basename(p)}:\n{text[:6000]}",  # noqa: B023 (called at once by _vision_cached)
                        },
                    ]
                ),
            )
            out.append({"file": p, "fields": fields})
        return {"items": out, "coverage": {"requested": len(files), "read": len(out)}, "failures": failures}

    def _ug_document_qa(self, a):
        files = [str(x) for x in self._list(a.get("file"))]
        ctx = "\n\n".join(f"[{os.path.basename(p)}]\n{self._doc_text(p)[:4000]}" for p in files)
        ans = self.llm.chat(
            [
                {"role": "system", "content": "Answer from the documents only and cite the file name."},
                {"role": "user", "content": f"{ctx}\n\nQuestion: {a.get('query')}"},
            ],
            json_mode=False,
        )
        return {"answer": ans, "sources": files}

    def _ug_document_metadata(self, a):
        out = []
        for p in self._list(a.get("file")):
            real = self._real(p)
            out.append(
                {
                    "file": p,
                    "size": os.path.getsize(real),
                    "mtime": dt.datetime.fromtimestamp(os.stat(real).st_mtime).isoformat(timespec="seconds"),
                }
            )
        return {"items": out}

    def _ug_document_writing(self, a):
        content = a.get("content") or ""
        if not content and a.get("file"):
            content = "\n\n".join(self._doc_text(p) for p in self._list(a.get("file")))
        draft = self.llm.chat(
            [
                {
                    "role": "system",
                    "content": "You write documents. Use only the facts given. Keep every number, date and "
                    "identifier exactly as given.",
                },
                {
                    "role": "user",
                    "content": f"Task: {a.get('task') or 'draft'}. Style: {a.get('style') or 'formal'}.\n"
                    f"Request: {a.get('query') or ''}\n\nFacts:\n{content}",
                },
            ],
            json_mode=False,
        )
        return {"mode": "draft", "draft": draft, "task": a.get("task") or "draft"}

    # ------------------------------------------------------------------ ug-knowledge
    def _ug_knowledge_collect_evidence(self, a):
        q = tokens(a.get("query") or "")
        roots = [str(x) for x in self._list(a.get("path"))] or [self.home]
        exts = tuple("." + str(e).lower().lstrip(".") for e in self._list(a.get("extension"))) or None
        docs = []
        for rel, text in self.index["docs"].items():
            full = f"{self.home}/{rel}"
            if not any(full.startswith(r.rstrip("/")) for r in roots):
                continue
            if exts and not rel.lower().endswith(exts):
                continue
            docs.append((rel, text))
        if not docs:
            return {"evidence": [], "coverage": {"files_scanned": 0}}
        df: dict = {}
        for _, text in docs:
            for t in set(tokens(text) + tokens(_)):
                df[t] = df.get(t, 0) + 1
        scored = []
        for rel, text in docs:
            toks = set(tokens(text) + tokens(rel))
            words = self._expand(q)
            hit = [w for w in words if w in toks]
            score = sum(math.log((len(docs) + 1) / (df.get(w, 0) + 0.5)) for w in hit)
            if score > 0:
                lines = [ln.strip() for ln in text.splitlines() if any(w in ln.lower() for w in hit)]
                scored.append((score, rel, " | ".join(lines[:4])[:400]))
        scored.sort(key=lambda s: -s[0])
        top = scored[0][0] if scored else 0
        keep = [s for s in scored if s[0] >= 0.45 * top][:8]
        return {
            "evidence": [
                {"path": f"{self.home}/{rel}", "passage": passage, "score": round(score, 2)}
                for score, rel, passage in keep
            ],
            "coverage": {"files_scanned": len(docs)},
        }

    def _ug_knowledge_save_text(self, a):
        folder = a.get("path") or f"{self.home}/Documents"
        name = a.get("filename-hint") or "note"
        if not os.path.splitext(name)[1]:
            name += ".md"
        real = os.path.join(self._real(folder), os.path.basename(name))
        os.makedirs(os.path.dirname(real), exist_ok=True)
        if os.path.exists(real):
            stem, ext = os.path.splitext(real)
            real = f"{stem}-{uuid.uuid4().hex[:4]}{ext}"
        with open(real, "w", encoding="utf-8") as f:
            f.write(a.get("content") or "")
        return {"verified": True, "outputFile": self._virtual(real), "contentBytes": os.path.getsize(real)}

    # ------------------------------------------------------------------ ug-surveillance
    def _ug_surveillance_cameras(self, a):
        return {"items": list(self.cams.values())}

    @staticmethod
    def _ts(s):
        s = str(s).replace("Z", "+00:00")
        t = dt.datetime.fromisoformat(s)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone(dt.timedelta(hours=1)))
        return t

    def _ug_surveillance_event_timeline(self, a):
        if not self.cams:
            return {"items": [], "summary": "no camera registered"}
        start, end = self._ts(a["start-time"]), self._ts(a["end-time"])
        topics = {str(t) for t in self._list(a.get("topic"))}
        ident = a.get("identity-type") or "all"
        cams = {str(c) for c in self._list(a.get("camera-id"))}
        out = []
        for e in self.spec.get("events", []):
            t = self._ts(e["time"])
            if not (start <= t <= end):
                continue
            if topics and e["topic"] not in topics:
                continue
            if cams and e["camera_id"] not in cams:
                continue
            if ident != "all" and e["identity"] != ident:
                continue
            row = {
                "event_id": e["event_id"],
                "time": e["time"],
                "camera_id": e["camera_id"],
                "camera_name": self.cams[e["camera_id"]]["name"],
                "topic": e["topic"],
                "identity": e["identity"],
                "summary": e["note"],
            }
            if e.get("person"):
                row["person_name"] = e["person"]
            if e.get("plate"):
                row["plate_id"] = "plate_" + e["plate"].replace("-", "")
            out.append(row)
        return {"items": out[: int(a.get("limit") or 100)], "summary": f"{len(out)} events"}

    def _ug_surveillance_event_evidence(self, a):
        ids = {str(x) for x in self._list(a.get("event-id"))}
        known = {e["event_id"] for e in self.spec.get("events", [])}
        return {
            "items": [
                {
                    "event_id": i,
                    "evidence_type": "snapshot",
                    "reference": f"snapshot://{i}/1",
                    "expires_in_sec": int(a.get("ttl-sec") or 3600),
                }
                for i in sorted(ids)
                if i in known
            ],
            "missing": sorted(ids - known),
        }

    def _ug_surveillance_vehicle_plates(self, a):
        ident = a.get("identity-type") or "all"
        plates = [e for e in self.spec.get("events", []) if e.get("plate")]
        return {
            "items": [
                {
                    "plate_id": "plate_" + e["plate"].replace("-", ""),
                    "plate": e["plate"],
                    "identity": e["identity"],
                    "last_seen": e["time"],
                }
                for e in plates
                if ident == "all" or e["identity"] == ident
            ]
        }

    def _ug_surveillance_identity_resolve(self, a):
        ids = {str(x) for x in self._list(a.get("event-id"))}
        out = []
        for e in self.spec.get("events", []):
            if e["event_id"] in ids:
                out.append(
                    {
                        "event_id": e["event_id"],
                        "identity": e["identity"],
                        "person_name": e.get("person"),
                        "confidence": 0.93 if e["identity"] == "known" else None,
                    }
                )
        return {"items": out}
