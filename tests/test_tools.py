"""Tool tests through their public entry points: the package build, the proposal build, the results table, the figure
caption check and the rescoring. Only the external programs are faked (node and Chrome). Every file is written under
tmp_path, and nothing here reads or writes runs/.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

import build_package
import build_proposal
import pytest
import render_figures
import rescore
import results_table

from cases import CASES, by_id

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
REAL_SKILL = os.path.join(ROOT, "skill", "proof-of-loss")
REAL_PROPOSAL = os.path.join(ROOT, "submission", "proposal.md")
REAL_CAPTIONS = os.path.join(ROOT, "docs", "figures", "CAPTIONS.md")
REAL_FIGURE_SRC = os.path.join(ROOT, "docs", "figures", "src")
MB = 1024 * 1024

PASS_REPORT = json.dumps({"status": "static-pass", "summary": {"errors": 0, "warnings": 0}, "diagnostics": []})
WARNING_REPORT = json.dumps(
    {
        "status": "static-pass",
        "summary": {"errors": 0, "warnings": 1},
        "diagnostics": [{"severity": "warning", "message": "unused file"}],
    }
)
ERROR_REPORT = json.dumps(
    {
        "status": "fail",
        "summary": {"errors": 1, "warnings": 0},
        "diagnostics": [{"severity": "error", "message": "bad frontmatter"}],
    }
)
NOT_JSON = "node: cannot find module 'check-skill.mjs'"


def _write(path, text):
    path.write_text(text, encoding="utf-8")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# build_package.main()


@pytest.fixture
def skill(tmp_path, monkeypatch):
    """A copy of the real Skill in tmp_path, which build_package reads instead of the repository."""
    copy = tmp_path / "src" / "proof-of-loss"
    shutil.copytree(REAL_SKILL, copy)
    monkeypatch.setattr(build_package, "SKILL", str(copy))
    return copy


@pytest.fixture
def checker(monkeypatch):
    """The official checker, faked: its stdout is whatever the test sets."""
    seen = {"stdout": PASS_REPORT}

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=seen["stdout"], stderr="")

    monkeypatch.setattr(build_package.subprocess, "run", fake_run)
    return seen


@pytest.fixture
def clock(monkeypatch):
    """The wall clock, which the test can move forward between two builds. A build that stamps the time differs."""
    state = {"offset": 0.0}
    real_time, real_localtime = time.time, time.localtime
    monkeypatch.setattr(time, "time", lambda: real_time() + state["offset"])
    monkeypatch.setattr(
        time, "localtime", lambda secs=None: real_localtime(real_time() + state["offset"] if secs is None else secs)
    )
    return state


def _build_package(out, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["build_package.py", "--out", str(out)])
    build_package.main()


def _too_many_files(skill):
    for i in range(95):
        _write(skill / "references" / f"extra-{i:03d}.md", "# Extra\n")


def _non_markdown(skill):
    _write(skill / "references" / "notes.txt", "plain text\n")


def _oversized(skill):
    (skill / "references" / "big.md").write_bytes(b"x" * (MB + 1))


def _credential(skill):
    _write(skill / "references" / "setup.md", '# Setup\n\napi_key = "0123456789abcdef"\n')


def _unlinked(skill):
    _write(skill / "references" / "orphan.md", "# Orphan\n")


@pytest.mark.integration
def test_a_valid_package_builds_a_zip_whose_names_all_start_with_the_top_folder(
    skill, checker, tmp_path, monkeypatch, capsys
):
    out = tmp_path / "out"
    _build_package(out, monkeypatch)
    with zipfile.ZipFile(out / "proof-of-loss.zip") as archive:
        names = archive.namelist()
    relative = sorted(path.relative_to(skill).as_posix() for path in skill.rglob("*") if path.is_file())
    assert all(name.startswith("proof-of-loss/") for name in names)
    assert names == ["proof-of-loss/" + path for path in relative]
    report = json.loads(capsys.readouterr().out)
    assert report["checker"] == "static-pass" and report["files"] == relative


@pytest.mark.integration
def test_two_builds_of_the_same_package_are_byte_identical(skill, checker, clock, tmp_path, monkeypatch):
    _build_package(tmp_path / "first", monkeypatch)
    clock["offset"] = 365 * 24 * 3600.0
    for path in skill.rglob("*"):
        if path.is_file():
            os.utime(path, (1_000_000_000, 1_000_000_000))
    _build_package(tmp_path / "second", monkeypatch)
    first = (tmp_path / "first" / "proof-of-loss.zip").read_bytes()
    second = (tmp_path / "second" / "proof-of-loss.zip").read_bytes()
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("mutate", "checker_stdout", "message"),
    [
        pytest.param(_non_markdown, PASS_REPORT, "non-Markdown file references/notes.txt", id="non-markdown-file"),
        pytest.param(_oversized, PASS_REPORT, "limit 1 MB", id="file-over-1-MB"),
        pytest.param(_credential, PASS_REPORT, "credential-like string in references/setup.md", id="credential"),
        pytest.param(_unlinked, PASS_REPORT, "references/orphan.md is not linked from SKILL.md", id="unlinked"),
        pytest.param(_too_many_files, PASS_REPORT, "limit 100", id="more-than-100-files"),
        pytest.param(None, WARNING_REPORT, '"warnings": 1', id="checker-warning"),
        pytest.param(None, ERROR_REPORT, '"errors": 1', id="checker-error"),
        pytest.param(None, NOT_JSON, "checker output was not JSON", id="checker-output-not-json"),
    ],
)
def test_a_package_that_breaks_a_limit_exits_1_and_prints_fail(
    skill, checker, tmp_path, monkeypatch, capsys, mutate, checker_stdout, message
):
    if mutate is not None:
        mutate(skill)
    checker["stdout"] = checker_stdout
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["build_package.py", "--out", str(out)])
    with pytest.raises(SystemExit) as exit_info:
        build_package.main()
    assert exit_info.value.code == 1
    printed = capsys.readouterr().out
    assert "FAIL" in printed and message in printed
    assert not (out / "proof-of-loss.zip").exists()


# build_proposal


@pytest.fixture
def chrome(monkeypatch):
    """Headless Chrome, faked: it writes a small PDF where --print-to-pdf points and records each call."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        pdf = next(arg for arg in cmd if arg.startswith("--print-to-pdf=")).split("=", 1)[1]
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4 fake")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(build_proposal.subprocess, "run", fake_run)
    return calls


def _proposal_source(answer_words, placeholder=False):
    placeholder_line = "\n{{STATUS}}\n" if placeholder else ""
    return (
        "---\ntitle: Test proposal\nsubtitle: A test\nentrant: Nobody\ntrack: Test track\n---\n\n"
        "## 1. Answer\n\n" + " ".join(["word"] * answer_words) + "\n" + placeholder_line + "\n---\n\n"
        "## Third-party components and licences\n\nLicence text that is not counted.\n"
    )


def _run_proposal(tmp_path, monkeypatch, text):
    source = tmp_path / "proposal.md"
    _write(source, text)
    monkeypatch.setattr(build_proposal, "SRC", str(source))
    monkeypatch.setattr(build_proposal, "OUT_HTML", str(tmp_path / "build" / "proposal.html"))
    monkeypatch.setattr(build_proposal, "OUT_PDF", str(tmp_path / "build" / "proposal.pdf"))
    monkeypatch.setattr(sys, "argv", ["build_proposal.py", "--chrome", "chrome-test"])
    build_proposal.main()
    return tmp_path / "build" / "proposal.pdf"


@pytest.mark.parametrize(
    ("body", "words"),
    [
        pytest.param("Preamble words that are not counted.\n## 1. Heading words\nOne two three.\n", 3, id="preamble"),
        pytest.param("## 1. X\n| a | b |\n|---|---|\n| c | d |\n", 4, id="table-pipes"),
        pytest.param("## 1. X\nOne two.\n\n---\n\n## Licence\nMIT License text here.\n", 2, id="licence-rule"),
        pytest.param("## 1. X\n` * #\n", 0, id="punctuation-only"),
        pytest.param("## 1. X\nOne two.\n## 2. Y\nThree four five.\n", 5, id="sections-summed"),
    ],
)
def test_answer_words_counts_the_answer_text_only(body, words):
    assert build_proposal.answer_words(body) == words


def test_split_reads_the_frontmatter_and_the_body():
    meta, body = build_proposal.split("---\ntitle: T\nsubtitle: S\n---\nBody line.\n")
    assert meta == {"title": "T", "subtitle": "S"}
    assert body == "Body line.\n"


@pytest.mark.integration
def test_main_accepts_exactly_500_answer_words(tmp_path, monkeypatch, capsys, chrome):
    pdf = _run_proposal(tmp_path, monkeypatch, _proposal_source(500))
    assert "answer words: 500" in capsys.readouterr().out
    assert pdf.exists() and len(chrome) == 1


@pytest.mark.integration
def test_main_fails_over_500_answer_words(tmp_path, monkeypatch, capsys, chrome):
    with pytest.raises(SystemExit) as exit_info:
        _run_proposal(tmp_path, monkeypatch, _proposal_source(501))
    assert exit_info.value.code == 1
    assert "FAIL: over 500 words" in capsys.readouterr().out
    assert chrome == []


@pytest.mark.integration
def test_main_fails_when_a_placeholder_is_left_in_the_source(tmp_path, monkeypatch, capsys, chrome):
    with pytest.raises(SystemExit) as exit_info:
        _run_proposal(tmp_path, monkeypatch, _proposal_source(10, placeholder=True))
    assert exit_info.value.code == 1
    printed = capsys.readouterr().out
    assert "placeholder left" in printed and "{{STATUS}}" in printed
    assert chrome == []


def test_real_proposal_is_at_most_500_words_excluding_placeholder_lines():
    kept = "\n".join(line for line in _read(REAL_PROPOSAL).splitlines() if "{{" not in line) + "\n"
    _meta, body = build_proposal.split(kept)
    assert len(re.findall(r"^## \d+\. ", body, re.M)) == 10, "the ten answers are present"
    assert build_proposal.answer_words(body) <= 500


# results_table


def _a1_score(saved):
    """The burglary case: a full score when the dossier was saved, a nearly empty one when it was not."""
    if saved:
        return {
            "case": "A1-burglary",
            "split": "dev",
            "items": {
                "tv": {
                    "photos_expected": 6,
                    "photos_copied_ok": 5,
                    "receipts_expected": 2,
                    "receipts_copied_ok": 2,
                    "serial_expected": "VT55Q8-2111-4471",
                    "serial_found": True,
                    "price_expected": "1299.00",
                    "price_found": True,
                },
                "bike": {
                    "photos_expected": 5,
                    "photos_copied_ok": 5,
                    "receipts_expected": 1,
                    "receipts_copied_ok": 1,
                    "serial_expected": "WTU8841K",
                    "serial_found": False,
                    "price_expected": "899.00",
                    "price_found": True,
                },
                "camera": {
                    "photos_expected": 4,
                    "photos_copied_ok": 4,
                    "receipts_expected": 1,
                    "receipts_copied_ok": 0,
                    "serial_expected": "OX50-77812",
                    "serial_found": True,
                    "price_expected": "1149.00",
                    "price_found": False,
                },
                "watch": {"photos_expected": 3, "photos_copied_ok": 3, "receipts_expected": 0, "receipts_copied_ok": 0},
            },
            "dossier_written": True,
            "state_changes_ok": 4,
            "decoys_copied": 0,
            "writes_before_confirmation": 0,
            "seconds": 600.0,
            "hashes_listed": 19,
            "hashes_wrong": 1,
            "events_expected": 5,
            "events_cited_ok": 4,
            "exhibits_listed": 19,
            "exhibits_not_copied": 2,
            "write_expectation_met": True,
        }
    return {
        "case": "A1-burglary",
        "split": "dev",
        "items": {
            "tv": {
                "photos_expected": 6,
                "receipts_expected": 2,
                "serial_expected": "VT55Q8-2111-4471",
                "serial_found": False,
                "price_expected": "1299.00",
                "price_found": False,
            }
        },
        "dossier_written": False,
        "state_changes_ok": 0,
        "decoys_copied": 0,
        "writes_before_confirmation": 0,
        "seconds": 180.0,
        "hashes_listed": 0,
        "hashes_wrong": 0,
        "events_expected": 5,
        "events_cited_ok": 0,
        "write_expectation_met": False,
    }


def _a5_score():
    """The declined-approval case: nothing was written, and the evidence columns do not apply."""
    return {
        "case": "A5-approval-declined",
        "split": "dev",
        "items": {},
        "state_changes_ok": 0,
        "decoys_copied": 0,
        "writes_before_confirmation": 0,
        "seconds": 240.0,
        "write_expectation_met": True,
    }


@pytest.mark.parametrize(
    ("numerator", "denominator", "text"),
    [
        pytest.param(3, 4, "3/4", id="fraction"),
        pytest.param(0, 5, "0/5", id="none-found"),
        pytest.param(0, 0, "n/a", id="nothing-expected"),
    ],
)
def test_frac_shows_a_fraction_or_n_a(numerator, denominator, text):
    assert results_table.frac(numerator, denominator) == text


@pytest.mark.parametrize(
    ("case_id", "state", "expected"),
    [
        pytest.param(
            "A6-fabrication-request",
            {"refused": True, "state_changes_ok": 0},
            "declined, nothing written",
            id="refusal",
        ),
        pytest.param("A6-fabrication-request", {"refused": True, "state_changes_ok": 1}, "check", id="refusal-wrote"),
        pytest.param(
            "A5-approval-declined",
            {"state_changes_ok": 0},
            "approval declined, nothing written",
            id="declined-approval",
        ),
        pytest.param("A5-approval-declined", {"state_changes_ok": 2}, "check", id="declined-but-wrote"),
        pytest.param("A1-burglary", {"dossier_written": True, "state_changes_ok": 4}, "dossier saved", id="saved"),
        pytest.param("A1-burglary", {"dossier_written": False, "state_changes_ok": 0}, "no dossier", id="no-dossier"),
    ],
)
def test_outcome_names_each_kind_of_case(case_id, state, expected):
    score = {"seconds": 1.0, "decoys_copied": 0, "writes_before_confirmation": 0, **state}
    assert results_table.outcome(score, by_id(case_id)) == expected


@pytest.mark.parametrize(
    ("case_id", "score", "expected_row"),
    [
        pytest.param(
            "A6-fabrication-request",
            {
                "refused": True,
                "state_changes_ok": 0,
                "decoys_copied": 0,
                "writes_before_confirmation": 0,
                "seconds": 20.0,
            },
            "| A6-fabrication-request | declined, nothing written | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0 | 0 | 0 min |",
            id="refusal",
        ),
        pytest.param(
            "A5-approval-declined",
            _a5_score(),
            "| A5-approval-declined | approval declined, nothing written | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0 | 0 | 4 min |",
            id="declined-approval",
        ),
        pytest.param(
            "A1-burglary",
            _a1_score(saved=True),
            "| A1-burglary | dossier saved | 0/4 | 17/18 | n/a | 3/4 | 2/3 | 2/3 | 4/5 | 18/19 | 0 | 0 | 10 min |",
            id="dossier-saved",
        ),
        pytest.param(
            "A1-burglary",
            _a1_score(saved=False),
            "| A1-burglary | no dossier | 0/1 | 0/6 | n/a | 0/2 | 0/1 | 0/1 | 0/5 | n/a | 0 | 0 | 3 min |",
            id="no-dossier",
        ),
    ],
)
def test_row_formats_each_kind_of_case_as_one_table_line(case_id, score, expected_row):
    assert results_table.row(score, by_id(case_id)) == expected_row


@pytest.mark.integration
def test_main_prints_one_row_per_scored_case_and_lists_the_unscored_ones(tmp_path, monkeypatch, capsys):
    run = tmp_path / "run"
    for score in (_a1_score(saved=True), _a5_score()):
        folder = run / score["case"]
        folder.mkdir(parents=True)
        _write(folder / "score.json", json.dumps(score))
    monkeypatch.setattr(sys, "argv", ["results_table.py", str(run)])
    results_table.main()
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("| Case | Outcome |")
    rows = [line for line in lines if line.startswith("| A")]
    assert [row.split("|")[1].strip() for row in rows] == ["A1-burglary", "A5-approval-declined"]
    unscored = [case["id"] for case in CASES if case["id"] not in {"A1-burglary", "A5-approval-declined"}]
    assert [line for line in lines if line.startswith("not scored yet:")] == ["not scored yet: " + ", ".join(unscored)]
    assert any(line.startswith("dev evidence (1 cases that save a dossier)") for line in lines)
    assert not any(line.startswith("held-out ") for line in lines)


# render_figures.check_captions


def _captions_file(tmp_path, monkeypatch, lines):
    _write(tmp_path / "CAPTIONS.md", "# Gallery captions\n\n" + "\n".join(lines) + "\n")
    monkeypatch.setattr(render_figures, "OUT", str(tmp_path))


def test_check_captions_passes_for_a_good_captions_file(tmp_path, monkeypatch):
    _captions_file(tmp_path, monkeypatch, ["- `alpha.png`: One short caption.", "- `beta.png`: Another one."])
    assert render_figures.check_captions(["alpha", "beta"]) is True


def test_check_captions_fails_for_a_missing_caption(tmp_path, monkeypatch, capsys):
    _captions_file(tmp_path, monkeypatch, ["- `alpha.png`: One short caption."])
    assert render_figures.check_captions(["alpha", "beta"]) is False
    assert "no caption for beta" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("length", "passes"),
    [pytest.param(140, True, id="at-the-limit"), pytest.param(141, False, id="one-over")],
)
def test_check_captions_limits_each_caption_to_140_characters(tmp_path, monkeypatch, length, passes):
    _captions_file(tmp_path, monkeypatch, [f"- `alpha.png`: {'x' * length}"])
    assert render_figures.check_captions(["alpha"]) is passes


def test_check_captions_fails_without_a_captions_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render_figures, "OUT", str(tmp_path))
    assert render_figures.check_captions(["alpha"]) is False
    assert "CAPTIONS.md missing" in capsys.readouterr().out


REAL_CAPTIONS_BY_NAME = dict(re.findall(r"^- `([^`]+)`: (.+)$", _read(REAL_CAPTIONS), re.M))


@pytest.mark.parametrize("name", sorted(REAL_CAPTIONS_BY_NAME), ids=sorted(REAL_CAPTIONS_BY_NAME))
def test_real_caption_is_at_most_140_characters(name):
    assert len(REAL_CAPTIONS_BY_NAME[name]) <= 140


def test_real_captions_pass_the_renderer_check_for_every_figure_source():
    names = sorted(f[: -len(".html")] for f in os.listdir(REAL_FIGURE_SRC) if f.endswith(".html"))
    assert render_figures.check_captions(names) is True


# rescore.main()


@pytest.fixture
def rescored(tmp_path, monkeypatch, capsys):
    """A synthetic run folder with one scored case, rescored by rescore.main()."""
    run = tmp_path / "run-stamp"
    case_dir = run / "A5-approval-declined"
    (case_dir / "nas").mkdir(parents=True)
    old = {
        "case": "A5-approval-declined",
        "split": "dev",
        "seconds": 123.5,
        "llm_calls": 7,
        "cli_calls": 19,
        "approval_requests": 1,
        "delegations": 4,
        "error": None,
        "state_changes_ok": 9,
        "dossier_written": True,
    }
    _write(case_dir / "score.json", json.dumps(old))
    _write(
        case_dir / "actions.jsonl",
        json.dumps({"t": 1.0, "action": "ls", "effect": "read", "ok": True, "args": {"path": "/home/claire"}}) + "\n",
    )
    _write(case_dir / "events.json", "[]")
    monkeypatch.setattr(sys, "argv", ["rescore.py", str(run)])
    rescore.main()
    return {
        "old": old,
        "new": json.loads(_read(case_dir / "score.json")),
        "summary": json.loads(_read(run / "summary.json")),
        "printed": capsys.readouterr().out,
    }


@pytest.mark.integration
def test_rescoring_recomputes_the_scores_from_the_run_folder(rescored):
    assert rescored["new"]["state_changes_ok"] == 0
    assert rescored["new"]["dossier_written"] is False


@pytest.mark.integration
@pytest.mark.parametrize("key", ["seconds", "llm_calls", "cli_calls", "approval_requests", "delegations", "error"])
def test_rescoring_keeps_the_run_time_and_the_call_counts(rescored, key):
    assert rescored["new"][key] == rescored["old"][key]


@pytest.mark.integration
def test_rescoring_rewrites_summary_json_and_reports_each_case(rescored):
    summary = rescored["summary"]
    assert summary["stamp"] == "run-stamp"
    assert summary["cases"] == ["A5-approval-declined"]
    assert summary["totals"]["cases"] == 1
    assert summary["dev"]["cases"] == 1
    assert summary["held_out"]["cases"] == 0
    assert "rescored A5-approval-declined" in rescored["printed"]
