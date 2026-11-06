"""Specification tests for harness/mock_nas.py, driven through MockNAS.invoke.

Only the model (FakeLLM) and the platform's approval answer (the Gate policy) are faked. Tests that only read use the
shared ro_nas fixture and never look at its log; tests that write use make_nas, which copies the light archive into
tmp_path. Expected values come from testdata/spec and testdata/index, or from hashlib and os.
"""

import datetime as dt
import hashlib
import json
import os

import pytest
from conftest import FakeLLM

from mock_nas import MockNAS, load_catalog, tokens

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
HOME = "/home/claire"
BILL = f"{HOME}/Documents/Bills/2026-10_Fibra_bill.pdf"
OTHER_BILL = f"{HOME}/Documents/Bills/2026-09_Energie-Rhone_bill.pdf"
PHOTOQUAI = f"{HOME}/Documents/Purchases/2022-06-30_PhotoQuai_invoice_F22-0631.pdf"
PURCHASES = f"{HOME}/Documents/Purchases"
RECEIPT = f"{HOME}/Documents/Receipts/2021-03-04_Cyclonord_receipt.jpg"
PHOTO = f"{HOME}/Photos/2021/IMG_20210306_110218.jpg"
PHOTO_2 = f"{HOME}/Photos/2021/IMG_20210117_140000.jpg"
ORVANE = f"{HOME}/Photos/2022/OXV_8616.JPG"
MISSING_PDF = f"{HOME}/Documents/Bills/none.pdf"
DAY_START = "2026-11-03T00:00:00+01:00"
DAY_END = "2026-11-03T23:59:00+01:00"
MTIME = 1_800_000_000


def _load(*parts):
    with open(os.path.join(ROOT, "testdata", *parts), encoding="utf-8") as f:
        return json.load(f)


SPEC = _load("spec", "household_a.json")
TRUTH = _load("spec", "household_a_photo_index.json")
INDEX = _load("index", "household_a.json")
CATALOG = load_catalog()

OWNER = {
    "file-workflow": "file-agent",
    "ug-filesystem": "file-agent",
    "ug-photo": "photo-agent",
    "ug-document": "document-agent",
    "ug-knowledge": "knowledge-agent",
    "ug-surveillance": "security-monitor-agent",
}


def call(nas, cli, action, args=None, agent=None):
    """One call through the public entry point, as the owning agent unless another agent is named."""
    return nas.invoke(agent or OWNER[cli], cli, action, args or {})


def real(nas, vpath):
    return os.path.join(nas.root, vpath.lstrip("/"))


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def put(nas, vpath, text):
    path = real(nas, vpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def tree(root):
    """Every folder, and every file's bytes and mtime, under root: what a write would change."""
    seen = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            seen[os.path.relpath(os.path.join(dirpath, name), root)] = "folder"
        for name in filenames:
            path = os.path.join(dirpath, name)
            seen[os.path.relpath(path, root)] = (read_bytes(path), os.path.getmtime(path))
    return seen


def served(cli, action):
    return hasattr(MockNAS, "_" + f"{cli}_{action}".replace("-", "_"))


SERVED_READS = {k for k, m in CATALOG.items() if served(*k) and m["effect"] == "read"}
GATED_WRITES = {
    k
    for k, m in CATALOG.items()
    if served(*k) and (m["effect"] == "state-change" or (m["effect"] == "mixed" and m["approval"] != "none"))
}

# One call per served read action, each valid against the archive.
READ_CASES = {
    ("file-workflow", "get-user-dir"): {},
    ("ug-filesystem", "ls"): {"path": HOME},
    ("ug-filesystem", "find"): {"path": HOME, "pattern": "*.pdf"},
    ("ug-filesystem", "stat"): {"path": BILL},
    ("ug-filesystem", "cat"): {"path": BILL, "length": 8},
    ("ug-filesystem", "sha256sum"): {"path": BILL},
    ("ug-filesystem", "md5sum"): {"path": BILL},
    ("ug-photo", "search-picture"): {"ai-object-name": ["sofa"]},
    ("ug-photo", "search-screen"): {"category": "scene", "keyword": "sofa"},
    ("ug-photo", "meta"): {"path": [ORVANE]},
    ("ug-photo", "vision-ocr"): {"path": RECEIPT},
    ("ug-photo", "vision-vlm"): {"path": RECEIPT},
    ("ug-photo", "albums"): {},
    ("ug-document", "extract"): {"query": "purchase facts", "file": [PHOTOQUAI]},
    ("ug-document", "qa"): {"query": "What is the total?", "file": [PHOTOQUAI]},
    ("ug-document", "metadata"): {"file": [BILL]},
    ("ug-knowledge", "collect-evidence"): {"query": "Cyclonord receipt"},
    ("ug-surveillance", "cameras"): {},
    ("ug-surveillance", "event-timeline"): {"start-time": DAY_START, "end-time": DAY_END},
    ("ug-surveillance", "event-evidence"): {"event-id": "evt_20261103_1451"},
    ("ug-surveillance", "vehicle-plates"): {},
    ("ug-surveillance", "identity-resolve"): {"event-id": "evt_20261103_0812"},
}

# One valid call per served write action (state-change, or mixed and gated), valid so that approving it succeeds.
WRITE_CASES = {
    ("ug-filesystem", "mkdir"): {"path": f"{HOME}/Claim"},
    ("ug-filesystem", "cpmv"): {"src": BILL, "dst": f"{HOME}/Claim/bill.pdf", "type": "copy"},
    ("ug-filesystem", "echo"): {"path": f"{HOME}/Claim/note.txt", "content": "x"},
    ("ug-filesystem", "touch"): {"path": f"{HOME}/Claim/touched.txt"},
    ("ug-filesystem", "chtimes"): {"path": BILL, "mtime": "1700000000"},
    ("ug-filesystem", "del"): {"path": BILL},
    ("ug-photo", "create-album"): {"album-name": "Receipts", "add-item": [RECEIPT]},
    ("ug-knowledge", "save-text"): {"path": f"{HOME}/Claim", "content": "x", "filename-hint": "note.md"},
    ("ug-document", "writing"): {"task": "draft", "query": "a letter", "content": "facts"},
}

REFUSED_READS = [
    ("file-agent", "ug-filesystem", "nope", {}, "UNKNOWN_ACTION"),
    ("file-agent", "no-such-cli", "ls", {"path": HOME}, "UNKNOWN_ACTION"),
    ("photo-agent", "ug-filesystem", "ls", {"path": HOME}, "FORBIDDEN"),
    ("file-agent", "ug-filesystem", "ls", {"path": HOME, "bogus": "1"}, "INVALID_ARGUMENT"),
    ("knowledge-agent", "ug-knowledge", "collect-evidence", {}, "INVALID_ARGUMENT"),
    ("file-agent", "ug-filesystem", "getfattr", {"path": HOME}, "UNSUPPORTED"),
    ("file-agent", "ug-filesystem", "stat", {"path": MISSING_PDF}, "NOT_FOUND"),
    ("file-agent", "ug-filesystem", "cat", {"path": RECEIPT}, "BAD_REQUEST"),
]

MISSING_OR_WRONG_TYPE_READS = [
    ("ug-filesystem", "stat", {"path": MISSING_PDF}),
    ("ug-filesystem", "cat", {"path": MISSING_PDF}),
    ("ug-filesystem", "sha256sum", {"path": MISSING_PDF}),
    ("ug-filesystem", "md5sum", {"path": f"{HOME}/Documents/Bills"}),
    ("ug-filesystem", "ls", {"path": f"{HOME}/Documents/Nope"}),
    ("ug-filesystem", "ls", {"path": BILL}),
    ("ug-document", "metadata", {"file": [MISSING_PDF]}),
    ("ug-document", "qa", {"query": "What is the total?", "file": [MISSING_PDF]}),
    ("ug-photo", "vision-ocr", {"path": f"{HOME}/Photos/none.jpg"}),
    ("ug-photo", "vision-vlm", {"path": f"{HOME}/Photos/none.jpg"}),
]

ESCAPES_READ = [
    ("ug-filesystem", "stat", {"path": "/home/claire/../../../../windows"}),
    ("ug-filesystem", "ls", {"path": "/home/claire/../../../.."}),
    ("ug-filesystem", "find", {"path": "/home/claire/../../../..", "pattern": "*"}),
    ("ug-filesystem", "cat", {"path": "/home/claire/../../../../windows/win.ini"}),
    ("ug-filesystem", "sha256sum", {"path": "/home/claire/../../../../windows/win.ini"}),
]

ESCAPES_WRITE = [
    ("ug-filesystem", "mkdir", {"path": "/home/claire/../../../escape-dir"}),
    ("ug-filesystem", "echo", {"path": "/home/claire/../../../escape.txt", "content": "x"}),
    ("ug-filesystem", "touch", {"path": "/home/claire/../../../escape.txt"}),
    ("ug-filesystem", "cpmv", {"src": BILL, "dst": "/home/claire/../../../escape.pdf", "type": "copy"}),
    ("ug-filesystem", "cpmv", {"src": "/home/claire/../../../../windows/win.ini", "dst": f"{HOME}/win.ini"}),
    ("ug-filesystem", "chtimes", {"path": "/home/claire/../../../escape.txt", "mtime": "1700000000"}),
    ("ug-filesystem", "del", {"path": "/home/claire/../../../../windows/win.ini"}),
    ("ug-knowledge", "save-text", {"path": "/home/claire/../../../escape-dir", "content": "x"}),
]


# ---------------------------------------------------------------- envelope and error codes


@pytest.mark.parametrize(
    "agent, cli, action, args, code",
    REFUSED_READS,
    ids=[
        "unknown-action",
        "unknown-cli",
        "forbidden",
        "unknown-parameter",
        "missing-required",
        "unsupported",
        "not-found",
        "bad-request",
    ],
)
def test_a_refused_read_answers_with_an_error_envelope(ro_nas, agent, cli, action, args, code):
    r = call(ro_nas, cli, action, args, agent=agent)
    assert set(r) == {"ok", "error"} and r["ok"] is False
    assert r["error"]["code"] == code and isinstance(r["error"]["message"], str)


@pytest.mark.parametrize(
    "cli, action, args",
    [
        ("ug-filesystem", "stat", {"path": BILL}),
        ("ug-photo", "albums", {}),
        ("ug-surveillance", "cameras", {}),
    ],
    ids=["stat", "albums", "cameras"],
)
def test_a_served_read_answers_with_ok_and_data_only(ro_nas, cli, action, args):
    r = call(ro_nas, cli, action, args)
    assert set(r) == {"ok", "data"} and r["ok"] is True


@pytest.mark.parametrize(
    "decision, code",
    [("deny", "APPROVAL_DENIED"), ("defer", "APPROVAL_PENDING")],
    ids=["denied", "pending"],
)
def test_a_write_the_user_has_not_approved_answers_with_the_gate_code(make_nas, decision, code):
    nas, _ = make_nas(decision=decision)
    before = tree(nas.root)
    r = call(nas, "ug-filesystem", "mkdir", {"path": f"{HOME}/Claim"})
    assert set(r) == {"ok", "error"} and r["ok"] is False and r["error"]["code"] == code
    assert tree(nas.root) == before


@pytest.mark.parametrize(
    "args, message",
    [
        ({"src": BILL, "dst": f"{HOME}/Claim", "mode": "x"}, "unknown parameter --mode"),
        ({"src": BILL}, "missing required parameter --dst"),
        ({"src": BILL, "dst": f"{HOME}/Claim", "type": "zip"}, "--type must be one of move, copy"),
        ({"src": [BILL, OTHER_BILL], "dst": f"{HOME}/Claim"}, "--src takes one value"),
    ],
    ids=["unknown-parameter", "missing-required", "value-outside-enum", "two-values-for-one"],
)
def test_invalid_write_arguments_are_refused_before_the_gate_is_asked(make_nas, args, message):
    nas, _ = make_nas(decision="deny")
    r = call(nas, "ug-filesystem", "cpmv", args)
    assert r["ok"] is False and r["error"]["code"] == "INVALID_ARGUMENT" and message in r["error"]["message"]
    assert nas.gate.requests == []


# ---------------------------------------------------------------- the home folder and listings


def test_the_user_home_lists_the_two_top_level_folders(ro_nas):
    r = call(ro_nas, "file-workflow", "get-user-dir")
    assert r == {"ok": True, "data": {"path": HOME, "fileId": "dir:home", "children": ["Documents", "Photos"]}}


def test_household_b_is_jonas_at_home(make_nas):
    nas, _ = make_nas(household="household_b")
    assert call(nas, "file-workflow", "get-user-dir")["data"]["path"] == "/home/jonas"


@pytest.mark.parametrize("alias", ["/current", "/~"])
def test_the_home_aliases_resolve_to_the_user_home(ro_nas, alias):
    stat = call(ro_nas, "ug-filesystem", "stat", {"path": alias})
    assert stat["ok"] and stat["data"]["path"] == HOME and stat["data"]["type"] == "dir"
    listed = call(ro_nas, "ug-filesystem", "ls", {"path": alias})
    assert listed["data"] == call(ro_nas, "ug-filesystem", "ls", {"path": HOME})["data"]


def test_listing_a_folder_returns_its_direct_files(ro_nas):
    r = call(ro_nas, "ug-filesystem", "ls", {"path": PURCHASES})
    assert sorted(i["name"] for i in r["data"]["items"]) == sorted(os.listdir(real(ro_nas, PURCHASES)))
    assert {i["type"] for i in r["data"]["items"]} == {"file"}


def test_listing_stops_at_the_limit(ro_nas):
    r = call(ro_nas, "ug-filesystem", "ls", {"path": PURCHASES, "limit": "3"})
    assert len(r["data"]["items"]) == 3


def test_listing_an_empty_folder_returns_no_items(make_nas):
    nas, _ = make_nas()
    os.makedirs(real(nas, f"{HOME}/Empty"))
    assert call(nas, "ug-filesystem", "ls", {"path": f"{HOME}/Empty"}) == {"ok": True, "data": {"items": []}}


@pytest.mark.parametrize(
    "vpath, kind",
    [(BILL, "file"), (f"{HOME}/Documents/Bills", "dir")],
    ids=["file", "folder"],
)
def test_stat_describes_a_file_or_a_folder(ro_nas, vpath, kind):
    r = call(ro_nas, "ug-filesystem", "stat", {"path": vpath})
    assert r["ok"] is True
    assert r["data"]["name"] == os.path.basename(vpath) and r["data"]["type"] == kind
    assert r["data"]["size"] == os.path.getsize(real(ro_nas, vpath))


@pytest.mark.parametrize("cli, action, args", MISSING_OR_WRONG_TYPE_READS)
def test_a_missing_or_wrong_type_target_is_not_found(ro_nas, cli, action, args):
    r = call(ro_nas, cli, action, args)
    assert r["ok"] is False and r["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------- find


def test_find_matches_a_name_pattern_under_the_folder(ro_nas):
    r = call(ro_nas, "ug-filesystem", "find", {"path": f"{HOME}/Documents", "pattern": "*.pdf"})
    on_disk = {
        n for _dir, _sub, names in os.walk(real(ro_nas, f"{HOME}/Documents")) for n in names if n.endswith(".pdf")
    }
    assert {i["name"] for i in r["data"]["items"]} == on_disk
    assert r["data"]["total"] == len(on_disk)


def test_find_limit_cuts_the_items_but_not_the_total(ro_nas):
    r = call(ro_nas, "ug-filesystem", "find", {"path": f"{HOME}/Documents", "pattern": "*.pdf", "limit": "3"})
    assert len(r["data"]["items"]) == 3
    assert r["data"]["total"] == 12


def test_find_by_kind_image_keeps_only_images(ro_nas):
    r = call(ro_nas, "ug-filesystem", "find", {"path": HOME, "type": "image"})
    images = [n for _dir, _sub, names in os.walk(real(ro_nas, HOME)) for n in names if n.lower().endswith(".jpg")]
    assert r["data"]["total"] == len(images)
    assert all(i["name"].lower().endswith(".jpg") for i in r["data"]["items"])


def test_find_with_no_match_is_an_empty_list(ro_nas):
    r = call(ro_nas, "ug-filesystem", "find", {"path": HOME, "pattern": "*.xyz"})
    assert r == {"ok": True, "data": {"items": [], "total": 0}}


@pytest.mark.parametrize(
    "start, end, found",
    [
        (MTIME, None, True),
        (MTIME + 1, None, False),
        (None, MTIME, True),
        (None, MTIME - 1, False),
        (MTIME - 60, MTIME + 60, True),
    ],
    ids=["start-equal", "start-one-second-later", "end-equal", "end-one-second-earlier", "window-around"],
)
def test_find_date_window_is_inclusive_at_both_ends(make_nas, start, end, found):
    nas, _ = make_nas()
    os.utime(real(nas, BILL), (MTIME, MTIME))
    args = {"path": f"{HOME}/Documents/Bills", "pattern": os.path.basename(BILL)}
    if start is not None:
        args["start-timestamp"] = str(start)
    if end is not None:
        args["end-timestamp"] = str(end)
    r = call(nas, "ug-filesystem", "find", args)
    assert r["ok"] is True and (r["data"]["total"] == 1) is found


# ---------------------------------------------------------------- cat, hashes


def test_cat_returns_the_text_of_a_utf8_file(make_nas):
    nas, _ = make_nas()
    put(nas, f"{HOME}/Notes/todo.txt", "Décision\nsecond line\n")
    r = call(nas, "ug-filesystem", "cat", {"path": f"{HOME}/Notes/todo.txt"})
    assert r == {"ok": True, "data": {"path": f"{HOME}/Notes/todo.txt", "content": "Décision\nsecond line\n"}}


@pytest.mark.parametrize(
    "offset, length, expected",
    [(0, 3, "abc"), (3, 4, "defg"), (8, None, "ij"), (10, 5, "")],
    ids=["first-bytes", "middle-bytes", "to-the-end", "offset-at-the-end"],
)
def test_cat_offset_and_length_select_a_byte_range(make_nas, offset, length, expected):
    nas, _ = make_nas()
    put(nas, f"{HOME}/Notes/letters.txt", "abcdefghij")
    args = {"path": f"{HOME}/Notes/letters.txt", "offset": offset}
    if length is not None:
        args["length"] = length
    assert call(nas, "ug-filesystem", "cat", args)["data"]["content"] == expected


def test_cat_of_a_binary_file_is_refused(ro_nas):
    r = call(ro_nas, "ug-filesystem", "cat", {"path": RECEIPT})
    assert r["ok"] is False and r["error"]["code"] == "BAD_REQUEST" and "binary file" in r["error"]["message"]


def test_cat_of_an_empty_file_is_empty_text(make_nas):
    nas, _ = make_nas()
    put(nas, f"{HOME}/Notes/empty.txt", "")
    assert call(nas, "ug-filesystem", "cat", {"path": f"{HOME}/Notes/empty.txt"})["data"]["content"] == ""


@pytest.mark.parametrize(
    "action, algo, vpath",
    [
        ("sha256sum", "sha256", BILL),
        ("sha256sum", "sha256", RECEIPT),
        ("md5sum", "md5", BILL),
        ("md5sum", "md5", RECEIPT),
    ],
    ids=["sha256-pdf", "sha256-jpg", "md5-pdf", "md5-jpg"],
)
def test_a_hash_matches_hashlib_and_is_lowercase_hex(ro_nas, action, algo, vpath):
    data = read_bytes(real(ro_nas, vpath))
    r = call(ro_nas, "ug-filesystem", action, {"path": vpath})
    digest = r["data"][algo]
    assert digest == hashlib.new(algo, data).hexdigest() == digest.lower()
    assert set(digest) <= set("0123456789abcdef")
    assert r["data"]["size"] == len(data)


@pytest.mark.parametrize("action, algo", [("sha256sum", "sha256"), ("md5sum", "md5")], ids=["sha256", "md5"])
def test_a_hash_of_an_empty_file_is_the_hash_of_no_bytes(make_nas, action, algo):
    nas, _ = make_nas()
    put(nas, f"{HOME}/Notes/empty.txt", "")
    r = call(nas, "ug-filesystem", action, {"path": f"{HOME}/Notes/empty.txt"})
    assert r["data"][algo] == hashlib.new(algo, b"").hexdigest() and r["data"]["size"] == 0


# ---------------------------------------------------------------- writes on the file system


def test_mkdir_creates_every_missing_folder_on_the_way(make_nas):
    nas, _ = make_nas()
    r = call(nas, "ug-filesystem", "mkdir", {"path": f"{HOME}/Claim/receipts/2021"})
    assert r == {"ok": True, "data": {"path": f"{HOME}/Claim/receipts/2021"}}
    assert os.path.isdir(real(nas, f"{HOME}/Claim/receipts/2021"))


def test_mkdir_of_an_existing_folder_changes_nothing(make_nas):
    nas, _ = make_nas()
    before = tree(nas.root)
    assert call(nas, "ug-filesystem", "mkdir", {"path": f"{HOME}/Photos"})["ok"] is True
    assert tree(nas.root) == before


def test_a_copy_into_a_folder_keeps_the_source_and_its_bytes(make_nas):
    nas, _ = make_nas()
    original = read_bytes(real(nas, BILL))
    call(nas, "ug-filesystem", "mkdir", {"path": f"{HOME}/Claim"})
    r = call(nas, "ug-filesystem", "cpmv", {"src": BILL, "dst": f"{HOME}/Claim", "type": "copy"})
    copy = f"{HOME}/Claim/2026-10_Fibra_bill.pdf"
    assert r["ok"] is True and r["data"]["dst"] == copy
    assert read_bytes(real(nas, copy)) == original and read_bytes(real(nas, BILL)) == original
    digest = call(nas, "ug-filesystem", "sha256sum", {"path": copy})["data"]["sha256"]
    assert digest == hashlib.sha256(original).hexdigest()


@pytest.mark.parametrize("kind, source_remains", [("copy", True), ("move", False)], ids=["copy", "move"])
def test_copy_keeps_the_source_and_move_removes_it(make_nas, kind, source_remains):
    nas, _ = make_nas()
    original = read_bytes(real(nas, BILL))
    r = call(nas, "ug-filesystem", "cpmv", {"src": BILL, "dst": f"{HOME}/Claim/bill.pdf", "type": kind})
    assert r["ok"] is True and r["data"]["type"] == kind
    assert os.path.exists(real(nas, BILL)) is source_remains
    assert read_bytes(real(nas, f"{HOME}/Claim/bill.pdf")) == original


@pytest.mark.parametrize("kind", ["copy", "move"], ids=["copy", "move"])
def test_without_overwrite_an_existing_destination_is_kept_and_the_source_stays(make_nas, kind):
    nas, _ = make_nas()
    kept = read_bytes(real(nas, OTHER_BILL))
    source = read_bytes(real(nas, BILL))
    r = call(nas, "ug-filesystem", "cpmv", {"src": BILL, "dst": OTHER_BILL, "type": kind})
    assert r["ok"] is False and r["error"]["code"] == "BAD_REQUEST"
    assert "destination exists" in r["error"]["message"]
    assert read_bytes(real(nas, OTHER_BILL)) == kept and read_bytes(real(nas, BILL)) == source


@pytest.mark.parametrize("kind, source_remains", [("copy", True), ("move", False)], ids=["copy", "move"])
def test_with_overwrite_the_existing_destination_is_replaced(make_nas, kind, source_remains):
    nas, _ = make_nas()
    original = read_bytes(real(nas, BILL))
    r = call(nas, "ug-filesystem", "cpmv", {"src": BILL, "dst": OTHER_BILL, "type": kind, "overwrite": True})
    assert r["ok"] is True
    assert read_bytes(real(nas, OTHER_BILL)) == original
    assert os.path.exists(real(nas, BILL)) is source_remains


def test_a_denied_copy_leaves_the_claim_folder_empty(make_nas):
    nas, _ = make_nas(policy=lambda op: "deny" if op["action"] == "cpmv" else "approve")
    assert call(nas, "ug-filesystem", "mkdir", {"path": f"{HOME}/Claim"})["ok"] is True
    r = call(nas, "ug-filesystem", "cpmv", {"src": BILL, "dst": f"{HOME}/Claim", "type": "copy"})
    assert r["error"]["code"] == "APPROVAL_DENIED"
    assert os.listdir(real(nas, f"{HOME}/Claim")) == []
    assert os.path.exists(real(nas, BILL))


@pytest.mark.parametrize(
    "cli, action, args",
    [
        ("ug-filesystem", "cpmv", {"src": MISSING_PDF, "dst": f"{HOME}/Claim", "type": "copy"}),
        ("ug-filesystem", "chtimes", {"path": MISSING_PDF, "mtime": "1700000000"}),
        ("ug-filesystem", "del", {"path": MISSING_PDF}),
        ("ug-photo", "create-album", {"album-name": "Missing", "add-item": [f"{HOME}/Photos/none.jpg"]}),
        ("ug-document", "writing", {"query": "a letter", "file": [MISSING_PDF]}),
    ],
    ids=["copy-source", "chtimes", "del", "album-photo", "writing-source"],
)
def test_a_write_on_a_missing_file_is_not_found_and_changes_nothing(make_nas, cli, action, args):
    nas, _ = make_nas()
    before = tree(nas.root)
    r = call(nas, cli, action, args)
    assert r["ok"] is False and r["error"]["code"] == "NOT_FOUND"
    assert tree(nas.root) == before


@pytest.mark.parametrize(
    "mode, expected",
    [(None, "new"), ("overwrite", "new"), ("append", "oldnew")],
    ids=["default", "overwrite", "append"],
)
def test_echo_replaces_the_file_unless_it_is_asked_to_append(make_nas, mode, expected):
    nas, _ = make_nas()
    put(nas, f"{HOME}/Claim/note.txt", "old")
    args = {"path": f"{HOME}/Claim/note.txt", "content": "new"}
    if mode is not None:
        args["write-mode"] = mode
    assert call(nas, "ug-filesystem", "echo", args)["ok"] is True
    assert read_bytes(real(nas, f"{HOME}/Claim/note.txt")).decode("utf-8") == expected


def test_echo_writes_utf8_and_reports_the_byte_size(make_nas):
    nas, _ = make_nas()
    r = call(nas, "ug-filesystem", "echo", {"path": f"{HOME}/Claim/note.txt", "content": "héllo"})
    assert r == {"ok": True, "data": {"path": f"{HOME}/Claim/note.txt", "size": 6}}
    assert read_bytes(real(nas, f"{HOME}/Claim/note.txt")).decode("utf-8") == "héllo"


@pytest.mark.parametrize(
    "args, expected",
    [({"path": f"{HOME}/Claim/touched.txt"}, ""), ({"path": f"{HOME}/Claim/touched.txt", "content": "seed"}, "seed")],
    ids=["no-content", "with-content"],
)
def test_touch_creates_a_missing_file_with_the_given_content(make_nas, args, expected):
    nas, _ = make_nas()
    assert call(nas, "ug-filesystem", "touch", args)["ok"] is True
    assert read_bytes(real(nas, f"{HOME}/Claim/touched.txt")).decode("utf-8") == expected


def test_chtimes_sets_the_modification_time_and_keeps_the_bytes(make_nas):
    nas, _ = make_nas()
    original = read_bytes(real(nas, BILL))
    r = call(nas, "ug-filesystem", "chtimes", {"path": BILL, "mtime": "1700000000"})
    assert r == {"ok": True, "data": {"path": BILL}}
    assert os.path.getmtime(real(nas, BILL)) == pytest.approx(1700000000, abs=1)
    assert read_bytes(real(nas, BILL)) == original


def test_del_removes_the_named_file_and_nothing_else(make_nas):
    nas, _ = make_nas()
    r = call(nas, "ug-filesystem", "del", {"path": BILL})
    assert r["ok"] is True and r["data"]["path"] == BILL
    assert not os.path.exists(real(nas, BILL))
    assert os.path.exists(real(nas, OTHER_BILL))


# ---------------------------------------------------------------- path safety


@pytest.mark.parametrize(
    "cli, action, args",
    ESCAPES_READ,
    ids=["stat", "ls", "find", "cat", "sha256sum"],
)
def test_a_read_outside_the_nas_is_refused(ro_nas, cli, action, args):
    r = call(ro_nas, cli, action, args)
    assert r["ok"] is False and r["error"]["code"] == "BAD_REQUEST"
    assert "outside the NAS" in r["error"]["message"]


@pytest.mark.parametrize(
    "cli, action, args",
    ESCAPES_WRITE,
    ids=["mkdir", "echo", "touch", "cpmv-dst", "cpmv-src", "chtimes", "del", "save-text"],
)
def test_a_write_outside_the_nas_is_refused_and_the_host_folder_is_untouched(make_nas, cli, action, args):
    nas, _ = make_nas()
    host = os.path.dirname(nas.root)
    before_nas, before_host = tree(nas.root), sorted(os.listdir(host))
    r = call(nas, cli, action, args)
    assert r["ok"] is False and r["error"]["code"] == "BAD_REQUEST"
    assert "outside the NAS" in r["error"]["message"]
    assert tree(nas.root) == before_nas and sorted(os.listdir(host)) == before_host


def test_an_absolute_path_to_a_host_file_is_never_read(ro_nas, tmp_path):
    host_file = tmp_path / "host-note.txt"
    host_file.write_text("PRIVATE-TEXT", encoding="utf-8")
    r = call(ro_nas, "ug-filesystem", "cat", {"path": str(host_file)})
    assert r["ok"] is False and "PRIVATE-TEXT" not in repr(r)


def test_an_absolute_path_to_a_host_file_is_never_written(make_nas, tmp_path):
    nas, _ = make_nas()
    host_file = tmp_path / "host-note.txt"
    host_file.write_text("PRIVATE-TEXT", encoding="utf-8")
    call(nas, "ug-filesystem", "echo", {"path": str(host_file), "content": "OVERWRITTEN"})
    assert host_file.read_text(encoding="utf-8") == "PRIVATE-TEXT"


# ---------------------------------------------------------------- the approval gate and the action log


@pytest.mark.parametrize("cli, action", sorted(WRITE_CASES))
def test_a_denied_write_leaves_the_disk_unchanged_and_reaches_the_gate_once(make_nas, cli, action):
    llm = FakeLLM()
    nas, log = make_nas(decision="deny", llm=llm)
    before = tree(nas.root)
    r = call(nas, cli, action, WRITE_CASES[(cli, action)])
    assert r["ok"] is False and r["error"]["code"] == "APPROVAL_DENIED"
    assert tree(nas.root) == before and nas.albums == [] and llm.asked == []
    assert [q["op"]["action"] for q in nas.gate.requests] == [action]
    assert log[-1]["decision"] == "deny"


@pytest.mark.parametrize("cli, action", sorted(WRITE_CASES))
def test_an_approved_write_succeeds_and_is_logged_with_its_catalog_effect_and_approval(make_nas, cli, action):
    nas, log = make_nas(decision="approve")
    r = call(nas, cli, action, WRITE_CASES[(cli, action)])
    meta = CATALOG[(cli, action)]
    assert r["ok"] is True
    assert (log[-1]["effect"], log[-1]["approval"], log[-1]["decision"]) == (
        meta["effect"],
        meta["approval"],
        "approve",
    )
    assert [q["op"]["action"] for q in nas.gate.requests] == [action]


@pytest.mark.parametrize("cli, action", sorted(READ_CASES))
def test_a_read_never_reaches_the_gate(make_nas, cli, action):
    nas, log = make_nas(decision="deny")
    call(nas, cli, action, READ_CASES[(cli, action)])
    assert nas.gate.requests == []
    assert log[-1]["effect"] == "read" and "decision" not in log[-1]


@pytest.mark.parametrize(
    "decision, code",
    [("approve", None), ("deny", "APPROVAL_DENIED"), ("defer", "APPROVAL_PENDING")],
    ids=["approve", "deny", "defer"],
)
def test_the_action_log_records_the_effect_approval_decision_and_outcome(make_nas, decision, code):
    nas, log = make_nas(decision=decision)
    call(nas, "ug-filesystem", "mkdir", {"path": f"{HOME}/Claim"})
    entry = log[-1]
    assert (entry["effect"], entry["approval"], entry["decision"]) == ("state-change", "gateway", decision)
    assert entry["ok"] is (code is None)
    assert entry.get("error", {}).get("code") == code


def test_a_deferred_write_is_approved_on_the_identical_retry(make_nas):
    asked = []

    def defer(op):
        asked.append(op)
        return "defer"

    nas, log = make_nas(policy=defer)
    args = {"path": f"{HOME}/Claim"}
    first = call(nas, "ug-filesystem", "mkdir", args)
    assert first["error"]["code"] == "APPROVAL_PENDING"
    assert not os.path.exists(real(nas, f"{HOME}/Claim"))
    retry = call(nas, "ug-filesystem", "mkdir", args)
    assert retry["ok"] is True and os.path.isdir(real(nas, f"{HOME}/Claim"))
    assert len(asked) == 1, "the identical retry must not be asked again"
    assert [e["decision"] for e in log] == ["defer", "approve"]


def test_a_different_write_after_a_deferral_is_asked_afresh(make_nas):
    asked = []

    def defer(op):
        asked.append(op)
        return "defer"

    nas, _ = make_nas(policy=defer)
    assert call(nas, "ug-filesystem", "mkdir", {"path": f"{HOME}/Claim"})["error"]["code"] == "APPROVAL_PENDING"
    other = call(nas, "ug-filesystem", "mkdir", {"path": f"{HOME}/Other"})
    assert other["error"]["code"] == "APPROVAL_PENDING"
    assert len(asked) == 2 and asked[1]["args"] == {"path": f"{HOME}/Other"}
    assert not os.path.exists(real(nas, f"{HOME}/Other"))


# ---------------------------------------------------------------- photos: search, EXIF and the vision cache


@pytest.mark.parametrize("obj, item", [("camera", "camera"), ("sofa", "sofa"), ("watch", "watch")])
def test_a_healthy_object_query_returns_exactly_the_photos_of_that_item(ro_nas, obj, item):
    want = {os.path.basename(r["path"]) for r in TRUTH if item in r["items"]}
    r = call(ro_nas, "ug-photo", "search-picture", {"ai-object-name": [obj], "page-size": "50"})
    assert {i["file_name"] for i in r["data"]["items"]} == want


def test_the_page_size_limits_the_items_and_the_total_counts_them_all(ro_nas):
    r = call(ro_nas, "ug-photo", "search-picture", {"ai-object-name": ["sofa"], "page-size": "2"})
    assert len(r["data"]["items"]) == 2 and r["data"]["total"] == 4


@pytest.mark.parametrize(
    "start, end, found",
    [
        ("2021-03-06T11:02:18", None, True),
        ("2021-03-06T11:02:19", None, False),
        (None, "2021-03-06T11:02:18", True),
        (None, "2021-03-06T11:02:17", False),
        ("2021-03-06", None, True),
    ],
    ids=["start-exact", "start-one-second-later", "end-exact", "end-one-second-earlier", "start-day"],
)
def test_a_photo_time_window_is_inclusive_at_the_exact_taken_time(ro_nas, start, end, found):
    args = {"ai-object-name": ["bicycle"], "page-size": "50"}
    if start is not None:
        args["start-time"] = start
    if end is not None:
        args["end-time"] = end
    r = call(ro_nas, "ug-photo", "search-picture", args)
    assert ("IMG_20210306_110218.jpg" in {i["file_name"] for i in r["data"]["items"]}) is found


def test_a_camera_model_filter_returns_the_photos_taken_with_that_body(ro_nas):
    r = call(ro_nas, "ug-photo", "search-picture", {"camera-model": ["X-50"]})
    assert {i["file_name"] for i in r["data"]["items"]} == {"OXV_0116.JPG", "OXV_7394.JPG", "OXV_8616.JPG"}


def test_an_ocr_query_finds_the_photo_with_that_printed_text(ro_nas):
    r = call(ro_nas, "ug-photo", "search-picture", {"ocr-contains": ["Veltra"]})
    assert [i["file_name"] for i in r["data"]["items"]] == ["IMG_20211120_181204.jpg"]


def test_a_query_with_no_match_returns_no_items(ro_nas):
    r = call(ro_nas, "ug-photo", "search-picture", {"ai-object-name": ["spaceship"]})
    assert r == {"ok": True, "data": {"items": [], "total": 0}}


def test_a_scene_keyword_returns_the_photos_of_that_item(ro_nas):
    want = {os.path.basename(r["path"]) for r in TRUTH if "watch" in r["items"]}
    r = call(ro_nas, "ug-photo", "search-screen", {"category": "scene", "keyword": "watch", "page-size": "50"})
    assert {i["file_name"] for i in r["data"]["items"]} == want


def test_the_ocr_category_searches_printed_text_in_documents_too(ro_nas):
    r = call(ro_nas, "ug-photo", "search-screen", {"category": "ocr", "keyword": "Cyclonord"})
    assert [i["path"] for i in r["data"]["items"]] == [RECEIPT]


def test_the_page_size_limits_scene_results(ro_nas):
    r = call(ro_nas, "ug-photo", "search-screen", {"category": "scene", "keyword": "bicycle", "page-size": "3"})
    assert len(r["data"]["items"]) == 3 and r["data"]["total"] == 7


def test_a_scene_keyword_with_no_hits_is_an_empty_list(ro_nas):
    r = call(ro_nas, "ug-photo", "search-screen", {"category": "scene", "keyword": "spaceship"})
    assert r == {"ok": True, "data": {"items": [], "total": 0}}


def test_a_keyword_made_only_of_stop_words_is_refused(ro_nas):
    r = call(ro_nas, "ug-photo", "search-screen", {"category": "scene", "keyword": "the"})
    assert r["ok"] is False and r["error"]["code"] == "BAD_REQUEST"


def test_meta_reads_capture_time_maker_model_lens_serial_and_gps(ro_nas):
    photo = next(p for p in SPEC["photos"] if p["id"] == "A-CX1")
    device = photo["device"]
    r = call(ro_nas, "ug-photo", "meta", {"path": [ORVANE]})
    item = r["data"]["items"][0]
    assert item["path"] == ORVANE
    exif = item["exif"]
    assert exif["DateTimeOriginal"] == photo["taken"].replace("-", ":").replace("T", " ")
    assert (exif["Make"], exif["Model"]) == (device["make"], device["model"])
    assert exif["LensModel"] == device["lens"] and exif["BodySerialNumber"] == device["body_serial"]
    lat, lon = photo["gps"]
    assert exif["GPS"]["latitude"] == pytest.approx(lat, abs=1e-4)
    assert exif["GPS"]["longitude"] == pytest.approx(lon, abs=1e-4)


def test_meta_answers_one_entry_per_path_in_order_and_marks_a_missing_one(ro_nas):
    missing = f"{HOME}/Photos/none.jpg"
    first, second = call(ro_nas, "ug-photo", "meta", {"path": [ORVANE, missing]})["data"]["items"]
    assert first["path"] == ORVANE and "exif" in first
    assert second == {"path": missing, "error": "not found"}


def test_meta_with_no_path_returns_no_items(ro_nas):
    assert call(ro_nas, "ug-photo", "meta", {}) == {"ok": True, "data": {"items": []}}


def test_meta_of_a_document_that_is_not_an_image_is_refused(ro_nas):
    r = call(ro_nas, "ug-photo", "meta", {"path": [BILL]})
    assert r["ok"] is False and r["error"]["code"] == "BAD_REQUEST"


def test_an_album_lists_with_the_photos_it_was_given(make_nas):
    nas, _ = make_nas()
    created = call(nas, "ug-photo", "create-album", {"album-name": "Bike", "add-item": [PHOTO, PHOTO_2]})
    assert created["ok"] is True and created["data"]["status"] == "completed"
    assert created["data"]["photo_count"] == 2
    listed = call(nas, "ug-photo", "albums", {})
    assert listed["data"]["items"] == [{"album_uuid": created["data"]["album_uuid"], "name": "Bike", "count": 2}]


def test_albums_is_empty_before_any_album_is_made(ro_nas):
    assert call(ro_nas, "ug-photo", "albums", {}) == {"ok": True, "data": {"items": []}}


def test_ocr_returns_the_text_the_model_reads_from_the_photo(make_nas):
    llm = FakeLLM(vision="TOTAL 911.00 EUR")
    nas, _ = make_nas(llm=llm)
    r = call(nas, "ug-photo", "vision-ocr", {"path": RECEIPT})
    assert r == {"ok": True, "data": {"path": RECEIPT, "text": "TOTAL 911.00 EUR"}}
    kind, path, prompt = llm.asked[0]
    assert kind == "vision" and path.endswith("2021-03-04_Cyclonord_receipt.jpg")
    assert prompt.startswith("Transcribe all text")


def test_vlm_passes_the_prompt_to_the_model_and_returns_its_answer(make_nas):
    llm = FakeLLM(vision="A receipt for a bicycle.")
    nas, _ = make_nas(llm=llm)
    r = call(nas, "ug-photo", "vision-vlm", {"path": RECEIPT, "prompt": "What was bought?"})
    assert r == {"ok": True, "data": {"path": RECEIPT, "answer": "A receipt for a bicycle."}}
    assert llm.asked[-1][2] == "What was bought?"


def test_vlm_without_a_prompt_asks_for_a_description(make_nas):
    llm = FakeLLM(vision="A receipt.")
    nas, _ = make_nas(llm=llm)
    call(nas, "ug-photo", "vision-vlm", {"path": RECEIPT})
    assert llm.asked[-1][2] == "Describe this image."


CACHED_CALLS = [
    ("ug-photo", "vision-ocr", {"path": RECEIPT}),
    ("ug-photo", "vision-vlm", {"path": RECEIPT, "prompt": "What was bought?"}),
    ("ug-document", "extract", {"query": "purchase facts", "file": [PHOTOQUAI]}),
]


@pytest.mark.parametrize("cli, action, args", CACHED_CALLS, ids=["ocr", "vlm", "extract"])
def test_a_repeated_model_call_is_answered_from_the_cache(make_nas, cli, action, args):
    llm = FakeLLM()
    nas, _ = make_nas(llm=llm)
    first = call(nas, cli, action, args)
    asked_after_first = len(llm.asked)
    second = call(nas, cli, action, args)
    assert first["ok"] is True and first == second
    assert asked_after_first == 1 and len(llm.asked) == 1


def test_a_different_prompt_on_the_same_photo_asks_the_model_again(make_nas):
    llm = FakeLLM()
    nas, _ = make_nas(llm=llm)
    call(nas, "ug-photo", "vision-vlm", {"path": RECEIPT, "prompt": "What was bought?"})
    call(nas, "ug-photo", "vision-vlm", {"path": RECEIPT, "prompt": "Who wrote it?"})
    assert len(llm.asked) == 2


# ---------------------------------------------------------------- documents: extract, metadata, qa, writing


def test_extract_returns_the_fields_the_model_read_from_each_document(make_nas):
    fields = {"document_type": "invoice", "merchant": "PhotoQuai", "total": "1178.00"}
    llm = FakeLLM(fields=fields)
    nas, _ = make_nas(llm=llm)
    r = call(nas, "ug-document", "extract", {"query": "purchase facts", "file": [PHOTOQUAI]})
    assert r["data"]["items"] == [{"file": PHOTOQUAI, "fields": fields}]
    assert r["data"]["coverage"] == {"requested": 1, "read": 1} and r["data"]["failures"] == []
    _system, user = llm.asked[-1][1]
    assert "Schema hint: auto" in user["content"] and "Total: 1178.00 EUR" in user["content"]


def test_extract_lists_a_missing_document_as_a_failure_and_reads_the_rest(make_nas):
    nas, _ = make_nas()
    r = call(nas, "ug-document", "extract", {"query": "q", "file": [MISSING_PDF, PHOTOQUAI]})
    assert r["ok"] is True
    assert r["data"]["coverage"] == {"requested": 2, "read": 1}
    assert r["data"]["failures"] == [{"file": MISSING_PDF, "error": "not found"}]


def test_extract_with_no_files_reads_nothing_and_asks_nothing(make_nas):
    llm = FakeLLM()
    nas, _ = make_nas(llm=llm)
    r = call(nas, "ug-document", "extract", {"query": "purchase facts"})
    assert r == {"ok": True, "data": {"items": [], "coverage": {"requested": 0, "read": 0}, "failures": []}}
    assert llm.asked == []


def test_metadata_reports_size_and_mtime_of_each_document(ro_nas):
    r = call(ro_nas, "ug-document", "metadata", {"file": [BILL, PHOTOQUAI]})
    by_file = {i["file"]: i for i in r["data"]["items"]}
    for vpath in (BILL, PHOTOQUAI):
        path = real(ro_nas, vpath)
        assert by_file[vpath]["size"] == os.path.getsize(path)
        mtime = dt.datetime.fromisoformat(by_file[vpath]["mtime"])
        assert mtime == dt.datetime.fromtimestamp(os.path.getmtime(path)).replace(microsecond=0)


def test_metadata_with_no_files_returns_no_items(ro_nas):
    assert call(ro_nas, "ug-document", "metadata", {}) == {"ok": True, "data": {"items": []}}


def test_qa_answers_from_the_document_text_and_names_its_source(make_nas):
    llm = FakeLLM(text="The total is 1178.00 EUR.")
    nas, _ = make_nas(llm=llm)
    r = call(nas, "ug-document", "qa", {"query": "What was the total?", "file": [PHOTOQUAI]})
    assert r == {"ok": True, "data": {"answer": "The total is 1178.00 EUR.", "sources": [PHOTOQUAI]}}
    _system, user = llm.asked[-1][1]
    assert "Total: 1178.00 EUR" in user["content"] and user["content"].endswith("Question: What was the total?")


def test_qa_over_two_documents_puts_both_in_the_prompt(make_nas):
    llm = FakeLLM()
    nas, _ = make_nas(llm=llm)
    r = call(nas, "ug-document", "qa", {"query": "Which bill is due?", "file": [BILL, OTHER_BILL]})
    assert r["data"]["sources"] == [BILL, OTHER_BILL]
    user = llm.asked[-1][1][1]["content"]
    assert "[2026-10_Fibra_bill.pdf]" in user and "[2026-09_Energie-Rhone_bill.pdf]" in user


def test_writing_drafts_from_the_content_it_is_given(make_nas):
    llm = FakeLLM(text="Dear sir, the total is 1178.00 EUR.")
    nas, _ = make_nas(llm=llm)
    r = call(
        nas,
        "ug-document",
        "writing",
        {"task": "draft", "style": "formal", "query": "a letter", "content": "total 1178.00 EUR"},
    )
    assert r == {
        "ok": True,
        "data": {"mode": "draft", "draft": "Dear sir, the total is 1178.00 EUR.", "task": "draft"},
    }
    user = llm.asked[-1][1][1]["content"]
    assert "Style: formal" in user and "total 1178.00 EUR" in user


def test_writing_takes_its_facts_from_the_files_when_no_content_is_given(make_nas):
    llm = FakeLLM()
    nas, _ = make_nas(llm=llm)
    call(nas, "ug-document", "writing", {"query": "a letter", "file": [PHOTOQUAI]})
    user = llm.asked[-1][1][1]["content"]
    assert "Total: 1178.00 EUR" in user and "PhotoQuai" in user


# ---------------------------------------------------------------- knowledge: evidence and save-text


def test_evidence_ranks_the_named_receipt_first(ro_nas):
    r = call(ro_nas, "ug-knowledge", "collect-evidence", {"query": "Cyclonord receipt"})
    assert r["data"]["evidence"][0]["path"] == RECEIPT


def test_evidence_is_limited_to_the_requested_extension(ro_nas):
    r = call(
        ro_nas,
        "ug-knowledge",
        "collect-evidence",
        {"query": "purchase invoice", "path": [f"{HOME}/Documents"], "extension": ["pdf"]},
    )
    assert r["data"]["evidence"] and all(e["path"].endswith(".pdf") for e in r["data"]["evidence"])
    assert r["data"]["coverage"] == {"files_scanned": 12}


def test_evidence_stays_inside_the_requested_folders(ro_nas):
    r = call(ro_nas, "ug-knowledge", "collect-evidence", {"query": "purchase invoice", "path": ["/home/jonas"]})
    assert r == {"ok": True, "data": {"evidence": [], "coverage": {"files_scanned": 0}}}


def test_evidence_for_stop_words_only_is_empty(ro_nas):
    r = call(ro_nas, "ug-knowledge", "collect-evidence", {"query": "the and of"})
    assert r == {"ok": True, "data": {"evidence": [], "coverage": {"files_scanned": len(INDEX["docs"])}}}


def test_save_text_adds_a_markdown_name_when_none_is_given(make_nas):
    nas, _ = make_nas()
    content = "Décision"
    r = call(nas, "ug-knowledge", "save-text", {"path": f"{HOME}/Claim", "content": content, "filename-hint": "note"})
    assert r["ok"] is True and r["data"]["verified"] is True
    assert r["data"]["outputFile"] == f"{HOME}/Claim/note.md"
    assert r["data"]["contentBytes"] == len(content.encode("utf-8"))
    assert read_bytes(real(nas, f"{HOME}/Claim/note.md")).decode("utf-8") == content


def test_save_text_keeps_an_existing_file_and_writes_beside_it(make_nas):
    nas, _ = make_nas()
    call(nas, "ug-knowledge", "save-text", {"path": f"{HOME}/Claim", "content": "first", "filename-hint": "note.md"})
    r = call(
        nas, "ug-knowledge", "save-text", {"path": f"{HOME}/Claim", "content": "second", "filename-hint": "note.md"}
    )
    assert r["ok"] is True
    out = r["data"]["outputFile"]
    assert out != f"{HOME}/Claim/note.md" and out.startswith(f"{HOME}/Claim/note-") and out.endswith(".md")
    assert read_bytes(real(nas, f"{HOME}/Claim/note.md")) == b"first"
    assert read_bytes(real(nas, out)) == b"second"


def test_save_text_without_a_path_writes_to_the_documents_folder(make_nas):
    nas, _ = make_nas()
    r = call(nas, "ug-knowledge", "save-text", {"content": "x", "filename-hint": "a.txt"})
    assert r["data"]["outputFile"] == f"{HOME}/Documents/a.txt"
    assert read_bytes(real(nas, f"{HOME}/Documents/a.txt")) == b"x"


# ---------------------------------------------------------------- surveillance


def test_cameras_lists_the_registered_cameras_of_household_a(ro_nas):
    assert call(ro_nas, "ug-surveillance", "cameras")["data"]["items"] == SPEC["cameras"]


def test_household_b_has_no_registered_camera(make_nas):
    nas, _ = make_nas(household="household_b")
    assert call(nas, "ug-surveillance", "cameras") == {"ok": True, "data": {"items": []}}


def test_household_b_timeline_returns_nothing_for_any_window(make_nas):
    nas, _ = make_nas(household="household_b")
    r = call(
        nas,
        "ug-surveillance",
        "event-timeline",
        {"start-time": "2026-01-01T00:00:00+01:00", "end-time": "2027-01-01T00:00:00+01:00"},
    )
    assert r == {"ok": True, "data": {"items": [], "summary": "no camera registered"}}


@pytest.mark.parametrize(
    "start, end, ids",
    [
        ("2026-11-03T14:22:31+01:00", "2026-11-03T14:22:31+01:00", ["evt_20261103_1422a"]),
        ("2026-11-03T13:22:31Z", "2026-11-03T13:22:31Z", ["evt_20261103_1422a"]),
        ("2026-11-03T14:22:32+01:00", "2026-11-03T14:22:48+01:00", ["evt_20261103_1422b"]),
        ("2026-11-03T14:22:31+01:00", "2026-11-03T14:22:30+01:00", []),
    ],
    ids=["exact-instant", "same-instant-in-utc", "start-after-first-end-on-second", "end-before-start"],
)
def test_the_timeline_window_is_inclusive_at_both_ends(ro_nas, start, end, ids):
    r = call(ro_nas, "ug-surveillance", "event-timeline", {"start-time": start, "end-time": end})
    assert r["ok"] is True and [i["event_id"] for i in r["data"]["items"]] == ids


@pytest.mark.parametrize(
    "extra, ids",
    [
        ({"topic": ["Vehicle"]}, ["evt_20261103_1451"]),
        ({"identity-type": "known"}, ["evt_20261103_0812", "evt_20261103_1840"]),
        ({"camera-id": ["cam-02"]}, ["evt_20261103_1437"]),
    ],
    ids=["topic", "identity", "camera"],
)
def test_the_timeline_filters_by_topic_identity_and_camera(ro_nas, extra, ids):
    r = call(ro_nas, "ug-surveillance", "event-timeline", {"start-time": DAY_START, "end-time": DAY_END, **extra})
    assert sorted(i["event_id"] for i in r["data"]["items"]) == ids


def test_the_timeline_limit_cuts_items_and_the_summary_counts_all(ro_nas):
    day_events = sum(1 for e in SPEC["events"] if e["time"].startswith("2026-11-03"))
    r = call(ro_nas, "ug-surveillance", "event-timeline", {"start-time": DAY_START, "end-time": DAY_END, "limit": "1"})
    assert len(r["data"]["items"]) == 1 and r["data"]["summary"] == f"{day_events} events"


def test_an_unreadable_timeline_time_is_refused(ro_nas):
    r = call(ro_nas, "ug-surveillance", "event-timeline", {"start-time": "yesterday", "end-time": DAY_END})
    assert r["ok"] is False and r["error"]["code"] == "BAD_REQUEST"


def test_event_evidence_offers_a_snapshot_for_a_known_event_and_lists_the_rest_as_missing(ro_nas):
    r = call(
        ro_nas,
        "ug-surveillance",
        "event-evidence",
        {"event-id": ["evt_20261103_1451", "evt_nope"], "ttl-sec": "120"},
    )
    assert r["data"]["items"] == [
        {
            "event_id": "evt_20261103_1451",
            "evidence_type": "snapshot",
            "reference": "snapshot://evt_20261103_1451/1",
            "expires_in_sec": 120,
        }
    ]
    assert r["data"]["missing"] == ["evt_nope"]


def test_event_evidence_defaults_to_one_hour_of_validity(ro_nas):
    r = call(ro_nas, "ug-surveillance", "event-evidence", {"event-id": "evt_20261103_1451"})
    assert r["data"]["items"][0]["expires_in_sec"] == 3600


def test_event_evidence_for_unknown_events_offers_nothing(ro_nas):
    r = call(ro_nas, "ug-surveillance", "event-evidence", {"event-id": "evt_nope"})
    assert r == {"ok": True, "data": {"items": [], "missing": ["evt_nope"]}}


def test_vehicle_plates_lists_each_plate_the_cameras_saw(ro_nas):
    r = call(ro_nas, "ug-surveillance", "vehicle-plates")
    assert r["data"] == {
        "items": [
            {
                "plate_id": "plate_GK482RT",
                "plate": "GK-482-RT",
                "identity": "stranger",
                "last_seen": "2026-11-03T14:51:19+01:00",
            }
        ]
    }


def test_vehicle_plates_for_known_identities_is_empty(ro_nas):
    assert call(ro_nas, "ug-surveillance", "vehicle-plates", {"identity-type": "known"}) == {
        "ok": True,
        "data": {"items": []},
    }


@pytest.mark.parametrize(
    "event_id, expected",
    [
        (
            "evt_20261103_0812",
            {"event_id": "evt_20261103_0812", "identity": "known", "person_name": "Claire", "confidence": 0.93},
        ),
        (
            "evt_20261103_1422a",
            {"event_id": "evt_20261103_1422a", "identity": "stranger", "person_name": None, "confidence": None},
        ),
    ],
    ids=["known-resident", "stranger"],
)
def test_identity_resolve_names_a_known_person_and_no_one_else(ro_nas, event_id, expected):
    r = call(ro_nas, "ug-surveillance", "identity-resolve", {"event-id": event_id})
    assert r["data"]["items"] == [expected]


def test_identity_resolve_of_unknown_events_is_empty(ro_nas):
    assert call(ro_nas, "ug-surveillance", "identity-resolve", {"event-id": "evt_nope"}) == {
        "ok": True,
        "data": {"items": []},
    }


# ---------------------------------------------------------------- tokens and the catalog


@pytest.mark.parametrize(
    "text, words",
    [
        ("Find all the photos of a bike", ["bike"]),
        ("Search for the receipt in this folder", ["receipt", "folder"]),
        ("Show the TV", ["tv"]),
        ("X-50 x", ["50"]),
        ("Orvane's camera, 2022!", ["orvane", "camera", "2022"]),
        ("the of and a", []),
        ("", []),
        (None, []),
    ],
    ids=["find-all", "search-for", "case-folded", "single-letters", "punctuation", "only-stop-words", "empty", "none"],
)
def test_tokens_drop_stop_words_and_single_letters(text, words):
    assert tokens(text) == words


def test_every_catalog_action_names_an_agent_an_effect_and_an_approval():
    missing = [key for key, meta in CATALOG.items() if not all(meta[f] for f in ("agent", "effect", "approval"))]
    assert missing == []


@pytest.mark.parametrize(
    "key, agent, effect, approval",
    [
        (("ug-filesystem", "ls"), "file-agent", "read", "none"),
        (("ug-filesystem", "mkdir"), "file-agent", "state-change", "gateway"),
        (("ug-document", "writing"), "document-agent", "mixed", "gateway"),
        (("ug-photo", "create-album"), "photo-agent", "state-change", "workflow"),
    ],
    ids=["read", "state-change", "mixed", "workflow"],
)
def test_load_catalog_reads_the_owner_effect_and_approval_of_an_action(key, agent, effect, approval):
    meta = CATALOG[key]
    assert (meta["agent"], meta["effect"], meta["approval"]) == (agent, effect, approval)


def test_load_catalog_keeps_the_enum_of_a_parameter():
    assert CATALOG[("ug-filesystem", "cpmv")]["params"]["type"]["enum"] == ["move", "copy"]


def test_the_cases_here_cover_every_served_read_and_every_write_the_gate_sees():
    assert set(READ_CASES) == SERVED_READS
    assert set(WRITE_CASES) == GATED_WRITES


# One regression test per bug found in the stand-in. A rehearsal once died on the first of these.


def test_creating_a_folder_where_a_file_exists_returns_an_error_instead_of_ending_the_run(make_nas):
    nas, _log = make_nas()
    existing = "/home/claire/Documents/Bills/2026-10_Fibra_bill.pdf"
    res = nas.invoke("file-agent", "ug-filesystem", "mkdir", {"path": existing})
    assert res["ok"] is False and res["error"]["code"] == "BAD_REQUEST"


@pytest.mark.parametrize("action", ["vision-ocr", "vision-vlm"])
def test_a_vision_call_with_no_path_returns_an_error_instead_of_ending_the_run(make_nas, action):
    nas, _log = make_nas()
    assert nas.invoke("photo-agent", "ug-photo", action, {})["ok"] is False


def test_save_text_keeps_a_climbing_file_name_inside_the_named_folder(make_nas, tmp_path):
    nas, _log = make_nas()
    args = {"path": "/home/claire/Documents", "content": "x", "filename-hint": "../../../../evil.md"}
    res = nas.invoke("knowledge-agent", "ug-knowledge", "save-text", args)
    assert res["ok"] and res["data"]["outputFile"] == "/home/claire/Documents/evil.md"
