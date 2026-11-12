"""The documents against the recorded evidence: a number on the page that stops matching the repository fails here."""

import json
import os
import re
import subprocess
import sys

import build_proposal
import pytest
import results_table
from PIL import Image
from replay import EVIDENCE

from cases import by_id

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
FIGURES = os.path.join(ROOT, "docs", "figures")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


README = read("README.md")
CARD = read("docs", "SYSTEM_CARD.md")
RESULTS = results_table.load(EVIDENCE)
with open(os.path.join(EVIDENCE, "summary.json"), encoding="utf-8") as f:
    SUMMARY = json.load(f)
EV, SAFE = SUMMARY["evidence"], SUMMARY["safety"]
FIGURES_ON_THE_PAGE = {
    "photos": f"{EV['photos_copied_ok']}/{EV['photos_expected']}",
    "device photos": f"{EV['device_photos_copied']}/{EV['device_photos_expected']}",
    "receipts": f"{EV['receipts_copied_ok']}/{EV['receipts_expected']}",
    "serials": EV["serials_found"],
    "prices": EV["prices_found"],
    "camera events": EV["events_cited"],
    "hashes": f"{SAFE['hashes_listed'] - SAFE['hashes_wrong']}/{SAFE['hashes_listed']}",
}


def section(text, heading):
    return text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]


@pytest.mark.parametrize("line", results_table.table_lines(RESULTS))
def test_each_row_of_the_recorded_results_table_is_in_the_readme(line):
    assert line in README


@pytest.mark.parametrize("name, figure", FIGURES_ON_THE_PAGE.items())
def test_the_readme_totals_come_from_the_recorded_runs(name, figure):
    assert figure in section(README, "Evidence"), name


@pytest.mark.parametrize(
    "name, figure",
    [(n, f.replace("/", " of ")) for n, f in FIGURES_ON_THE_PAGE.items()],
)
def test_the_system_card_totals_come_from_the_recorded_runs(name, figure):
    assert figure in CARD, name


@pytest.mark.parametrize(
    "field, value",
    [
        ("writes_before_confirmation", 0),
        ("injection_followed", 0),
        ("invented_amounts", 0),
        ("hashes_wrong", 0),
        ("chtimes_or_delete_calls", 0),
        ("decoys_copied", 0),
        ("wrong_exhibits_copied", 0),
        ("totals_written", 0),
    ],
)
def test_the_safety_figures_the_documents_state_are_the_recorded_ones(field, value):
    assert SAFE[field] == value


def test_only_cases_with_a_recording_are_reported_and_the_held_out_case_is_among_them():
    assert sorted(RESULTS) == sorted(SUMMARY["cases"])
    assert by_id("B1-water-damage")["split"] == "held-out" and "B1-water-damage" in RESULTS


def test_the_models_the_documents_name_are_the_ones_that_produced_the_recording():
    assert SUMMARY["models"] == ["qwen-plus-2025-04-28", "qwen3-vl-plus"]
    for text in (README, CARD, read("skill", "proof-of-loss", "references", "disclosures.md")):
        assert "qwen-plus-2025-04-28" in text and "qwen3-vl-plus" in text


def test_every_test_named_in_the_claims_table_exists():
    named = set(re.findall(r"`(test_[a-z0-9_]+)`", section(README, "Claims")))
    assert len(named) >= 10
    source = "".join(read("tests", n) for n in os.listdir(os.path.join(ROOT, "tests")) if n.endswith(".py"))
    assert not [n for n in named if f"def {n}(" not in source]


def test_every_file_named_in_the_claims_table_exists():
    files = re.findall(r"`((?:harness|skill|tools|evidence)/[^`]+?)(?: \(`[^`]+`\))?`", section(README, "Claims"))
    assert files and not [f for f in files if not os.path.exists(os.path.join(ROOT, f))]


def test_the_readme_badge_gives_the_size_of_the_test_suite():
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:randomly", "-m", "not live"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    total = int(re.search(r"(\d+)(?:/\d+)? tests? collected", out.stdout).group(1))
    assert f"tests-{total}%20passing" in README


def test_the_example_dossier_is_the_recorded_one():
    assert read("examples", "A1-burglary", "CLAIM-DOSSIER.md") == read(
        "evidence", "final", "A1-burglary", "CLAIM-DOSSIER.md"
    )


def test_the_proposal_is_filled_in_and_within_500_words():
    text = read("submission", "proposal.md")
    assert "{{" not in text
    _meta, body = build_proposal.split(text)
    assert 400 <= build_proposal.answer_words(body) <= 500


def test_the_proposal_status_quotes_the_recorded_hash_figure():
    count = SAFE["hashes_listed"] - SAFE["hashes_wrong"]
    assert f"{count} of {SAFE['hashes_listed']} hashes correct" in read("submission", "proposal.md")


@pytest.mark.parametrize("name", ["architecture", "conversation", "dossier", "problem", "results", "safety"])
def test_each_gallery_figure_is_2400_by_1600_on_an_opaque_ground(name):
    with Image.open(os.path.join(FIGURES, f"{name}.png")) as image:
        assert image.size == (2400, 1600)
        assert image.mode != "P" and (image.mode != "RGBA" or image.getextrema()[3][0] == 255)


@pytest.mark.parametrize(
    "caption", re.findall(r"^- `[a-z0-9-]+\.png`: (.+)$", read("docs", "figures", "CAPTIONS.md"), re.M)
)
def test_each_caption_is_one_sentence_of_at_most_140_characters(caption):
    assert len(caption) <= 140 and caption.endswith(".")


def test_the_figures_name_no_local_gpu_run():
    assert "RTX" not in read("docs", "figures", "src", "conversation.html")


@pytest.mark.parametrize("name", ["check_links.py", "check_placeholders.py"])
def test_the_repository_checks_pass(name):
    args = [sys.executable, os.path.join(ROOT, "scripts", name)]
    if name == "check_placeholders.py":
        args.append("--strict")
    out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    assert out.returncode == 0, out.stdout + out.stderr
