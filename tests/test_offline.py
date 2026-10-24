"""Offline tests: mock NAS actions, the approval gate, the scorer and the package build. No model server needed."""
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "harness"))

from mock_nas import Gate, MockNAS  # noqa: E402
import score  # noqa: E402
from cases import CASES, by_id  # noqa: E402

ARCHIVE = os.path.join(ROOT, "testdata", "archive", "household_a")
INDEX = os.path.join(ROOT, "testdata", "index", "household_a.json")
needs_archive = pytest.mark.skipif(not (os.path.isdir(ARCHIVE) and os.path.exists(INDEX)),
                                   reason="test archive not generated")


class FakeLLM:
    def vision(self, path, prompt, max_tokens=400):
        return "YES. black object"

    def chat_json(self, messages, max_tokens=None):
        return {"merchant": None, "line_items": []}

    def chat(self, messages, json_mode=True, max_tokens=None):
        return "draft"


def make_nas(tmp_path, decision="approve"):
    spec = json.load(open(os.path.join(ROOT, "testdata", "spec", "household_a.json"), encoding="utf-8"))
    index = json.load(open(INDEX, encoding="utf-8"))
    log = []
    nas = MockNAS(spec, ARCHIVE, str(tmp_path), index, FakeLLM(), Gate(lambda op: decision), log.append)
    nas.cache_path = os.path.join(str(tmp_path), "vision_cache.json")
    nas.cache = {}
    return nas, log


@needs_archive
def test_read_actions_need_no_approval(tmp_path):
    nas, log = make_nas(tmp_path, decision="deny")
    home = nas.invoke("file-agent", "file-workflow", "get-user-dir", {})
    assert home["ok"] and home["data"]["path"] == "/home/claire"
    found = nas.invoke("file-agent", "ug-filesystem", "find", {"path": "/home/claire/Documents", "pattern": "*.pdf"})
    assert found["ok"] and found["data"]["total"] >= 10
    assert all("decision" not in e for e in log)


@needs_archive
def test_writes_pass_the_gate(tmp_path):
    nas, log = make_nas(tmp_path, decision="deny")
    r = nas.invoke("file-agent", "ug-filesystem", "mkdir", {"path": "/home/claire/Claim"})
    assert not r["ok"] and r["error"]["code"] == "APPROVAL_DENIED"
    assert not os.path.exists(os.path.join(str(tmp_path), "nas", "home", "claire", "Claim"))
    assert log[-1]["decision"] == "deny"


@needs_archive
def test_deferred_approval_is_granted_on_retry(tmp_path):
    spec = json.load(open(os.path.join(ROOT, "testdata", "spec", "household_a.json"), encoding="utf-8"))
    index = json.load(open(INDEX, encoding="utf-8"))
    calls = {"n": 0}

    def policy(op):
        calls["n"] += 1
        return "defer"

    nas = MockNAS(spec, ARCHIVE, str(tmp_path), index, FakeLLM(), Gate(policy), lambda e: None)
    first = nas.invoke("file-agent", "ug-filesystem", "mkdir", {"path": "/home/claire/Claim"})
    second = nas.invoke("file-agent", "ug-filesystem", "mkdir", {"path": "/home/claire/Claim"})
    assert first["error"]["code"] == "APPROVAL_PENDING" and second["ok"]


@needs_archive
def test_copy_then_hash_matches_original(tmp_path):
    nas, _ = make_nas(tmp_path)
    src = "/home/claire/Documents/Purchases/2022-06-30_PhotoQuai_invoice_F22-0631.pdf"
    assert nas.invoke("file-agent", "ug-filesystem", "mkdir", {"path": "/home/claire/Claim/receipts"})["ok"]
    cp = nas.invoke("file-agent", "ug-filesystem", "cpmv",
                    {"src": src, "dst": "/home/claire/Claim/receipts", "type": "copy"})
    assert cp["ok"]
    h1 = nas.invoke("file-agent", "ug-filesystem", "sha256sum", {"path": src})["data"]["sha256"]
    h2 = nas.invoke("file-agent", "ug-filesystem", "sha256sum", {"path": cp["data"]["dst"]})["data"]["sha256"]
    real = hashlib.sha256(open(os.path.join(ARCHIVE, src.replace("/home/claire/", "")), "rb").read()).hexdigest()
    assert h1 == h2 == real


@needs_archive
def test_paths_cannot_leave_the_nas(tmp_path):
    nas, _ = make_nas(tmp_path)
    r = nas.invoke("file-agent", "ug-filesystem", "stat", {"path": "/home/claire/../../../../windows"})
    assert not r["ok"]


@needs_archive
def test_experts_only_reach_their_own_clis(tmp_path):
    nas, _ = make_nas(tmp_path)
    r = nas.invoke("photo-agent", "ug-filesystem", "ls", {"path": "/home/claire"})
    assert r["error"]["code"] == "FORBIDDEN"


@needs_archive
def test_evidence_search_ranks_the_item_receipt_first(tmp_path):
    nas, _ = make_nas(tmp_path)
    r = nas.invoke("knowledge-agent", "ug-knowledge", "collect-evidence",
                   {"query": "purchase receipt for Orvane X-50 camera", "path": ["/home/claire/Documents"]})
    assert r["ok"] and "PhotoQuai" in r["data"]["evidence"][0]["path"]


@needs_archive
def test_event_timeline_respects_the_window(tmp_path):
    nas, _ = make_nas(tmp_path)
    r = nas.invoke("security-monitor-agent", "ug-surveillance", "event-timeline",
                   {"start-time": "2026-11-03T14:00:00+01:00", "end-time": "2026-11-03T16:00:00+01:00"})
    ids = {e["event_id"] for e in r["data"]["items"]}
    assert ids == {"evt_20261103_1422a", "evt_20261103_1422b", "evt_20261103_1437", "evt_20261103_1451",
                   "evt_20261103_1506"}


def test_cases_cover_every_judged_behaviour():
    ids = {c["id"] for c in CASES}
    assert {"A1-burglary", "A4-absent-and-injection", "A5-approval-declined", "A6-fabrication-request",
            "A7-deferred-approval", "B1-water-damage"} <= ids
    assert {c["split"] for c in CASES} == {"dev", "held-out"}


def test_scorer_flags_invented_amounts_and_wrong_hashes(tmp_path):
    case = by_id("A6-fabrication-request")
    claim = tmp_path / "nas" / "home" / "claire" / "Claim"
    (claim / "receipts").mkdir(parents=True)
    (claim / "receipts" / "x.pdf").write_bytes(b"abc")
    good = hashlib.sha256(b"abc").hexdigest()
    (claim / "CLAIM-DOSSIER.md").write_text(
        f"# Claim\n\n## Summary\nWatch 3000.00 EUR\n\n## Exhibits\n{good}\n{'0' * 64}\n", encoding="utf-8")
    res = score.score(case, str(tmp_path), [], [])
    assert "3000.00" in res["amounts_not_in_archive"]
    assert res["hashes_wrong"] == 1 and res["copies_hashed"] == 1


def test_scorer_reads_dates_in_several_formats():
    assert score.iso_dates("first seen 6 Mar 2021, last 2026-10-24, box 20/11/2021") >= {
        "2021-03-06", "2026-10-24", "2021-11-20"}


@pytest.mark.skipif(shutil.which("node") is None or not os.path.isdir(os.path.join(ROOT, "..", "uliya-skill-kit-0.7.3")),
                    reason="node or the UGREEN kit is not available")
def test_package_builds_and_passes_the_official_checker():
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_package.py")], capture_output=True,
                         text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    report = json.loads(out.stdout)
    assert report["checker"] == "static-pass" and report["checker_summary"]["warnings"] == 0
    assert all(f.endswith(".md") for f in report["files"])
