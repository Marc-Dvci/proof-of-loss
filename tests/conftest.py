"""Shared test settings and fixtures.

Hypothesis draws new examples on every run, which finds more bugs locally. On CI (the CI variable is set) it uses a
fixed derandomized profile, so the same commit always runs the same examples and a red run can be repeated.

Only the edges the project does not own are faked: the model (FakeLLM) and the platform's approval answer (the Gate
policy). The stand-in CLI layer, the agent loops and the scorer are the real code.
"""

import json
import os
import shutil
import sys

import pytest
from hypothesis import settings

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "harness"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from mock_nas import Gate, MockNAS  # noqa: E402

settings.register_profile("ci", derandomize=True, print_blob=True, deadline=None)
settings.load_profile("ci" if os.environ.get("CI") else "default")

LIGHT_PHOTOS_PER_FOLDER = 2  # enough to copy and hash, without writing the full archive once per test


class FakeLLM:
    """The model, replaced at its edge: fixed answers, and a record of what was asked."""

    def __init__(self, vision="YES. A black object at home.", fields=None, text="draft"):
        self.vision_answer, self.fields, self.text = vision, fields, text
        self.asked = []

    def vision(self, path, prompt, max_tokens=400):
        self.asked.append(("vision", path, prompt))
        return self.vision_answer

    def chat_json(self, messages, max_tokens=None):
        self.asked.append(("chat_json", messages))
        return self.fields if self.fields is not None else {"merchant": None, "line_items": []}

    def chat(self, messages, json_mode=True, max_tokens=None):
        self.asked.append(("chat", messages))
        return self.text


def _load(household):
    with open(os.path.join(ROOT, "testdata", "spec", f"{household}.json"), encoding="utf-8") as f:
        spec = json.load(f)
    with open(os.path.join(ROOT, "testdata", "index", f"{household}.json"), encoding="utf-8") as f:
        index = json.load(f)
    return spec, index


def _build(run_dir, archive, household, policy, llm):
    spec, index = _load(household)
    log = []
    nas = MockNAS(spec, archive, run_dir, index, llm, Gate(policy), log.append)
    nas.cache_path = os.path.join(run_dir, "vision_cache.json")  # never the recorded cache in testdata/archive
    nas.cache = {}
    return nas, log


@pytest.fixture(scope="session")
def light_archive(tmp_path_factory):
    """Every document of each household and the first photos of each year: small enough to copy once per test."""
    base = tmp_path_factory.mktemp("archive")
    for household in ("household_a", "household_b"):
        src = os.path.join(ROOT, "testdata", "archive", household)
        for dirpath, _dirs, names in os.walk(src):
            rel = os.path.relpath(dirpath, src)
            keep = sorted(names)[:LIGHT_PHOTOS_PER_FOLDER] if rel.replace("\\", "/").startswith("Photos") else names
            for name in keep:
                dest = os.path.join(base, household, rel)
                os.makedirs(dest, exist_ok=True)
                shutil.copy2(os.path.join(dirpath, name), dest)
    return base


@pytest.fixture
def make_nas(tmp_path, light_archive):
    """Build a fresh stand-in NAS over the light archive: make_nas(decision="approve", household="household_a",
    llm=None, policy=None) returns (nas, log). `policy` overrides `decision` with a callable(op)."""

    def build(decision="approve", household="household_a", llm=None, policy=None):
        run_dir = tmp_path / f"run-{len(list(tmp_path.iterdir()))}"
        run_dir.mkdir()
        return _build(
            str(run_dir),
            os.path.join(light_archive, household),
            household,
            policy or (lambda op: decision),
            llm or FakeLLM(),
        )

    return build


@pytest.fixture(scope="session")
def ro_nas(tmp_path_factory):
    """One stand-in NAS over the full household A archive, shared by tests that only read."""
    run_dir = tmp_path_factory.mktemp("ro-nas")
    archive = os.path.join(ROOT, "testdata", "archive", "household_a")
    nas, _log = _build(str(run_dir), archive, "household_a", lambda op: "deny", FakeLLM())
    return nas
