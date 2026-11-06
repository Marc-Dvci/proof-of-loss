"""Contract tests for the Skill package. They read files only: the Skill and its references, the UGREEN capability
catalog, the README and proposal tables, the rehearsal cases and the ground truth in testdata/spec.

The Skill must meet the Hackathon rules and the Uliya standard (name, description, sections, reads that stay reads,
one writing step, package limits, no credentials or personal data), and the Skill, the catalog, the README and the
ground truth must agree with each other.
"""

import json
import os
import re

import pytest

from cases import CASES

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
PKG = os.path.join(ROOT, "skill", "proof-of-loss")
REFS = os.path.join(PKG, "references")
KIT_CATALOG = os.path.normpath(os.path.join(ROOT, "..", "uliya-skill-kit-0.7.3", "data", "capability-catalog.json"))
SPEC = os.path.join(ROOT, "testdata", "spec")
ARCHIVE = os.path.join(ROOT, "testdata", "archive")
HOUSEHOLDS = ("household_a", "household_b")
MB = 1024 * 1024
REQUIRED_SECTIONS = (
    "Goal",
    "Required input",
    "Generation-time capability evidence",
    "Workflow",
    "Completion and failure",
)
DELEGATION_STATES = ("completed", "failed", "cancelled", "waiting_user", "waiting_approval")
GATE_RULE = "**Step 6 runs only after the user has answered the step 5 question in this conversation.**"
README_EXPERT_HEADING = "## How UGREEN AI NAS does the work"
PROPOSAL_CAPABILITY_HEADING = "## 6. NAS capabilities by step"
EXPECTED_EXPERTS = {
    "file-agent",
    "photo-agent",
    "knowledge-agent",
    "document-agent",
    "security-monitor-agent",
}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_spec(household):
    spec = _load_json(os.path.join(SPEC, f"{household}.json"))
    index = _load_json(os.path.join(SPEC, f"{household}_photo_index.json"))
    return spec, index


def _frontmatter(text):
    fields = {}
    for line in re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1).splitlines():
        key, _, value = line.partition(": ")
        fields[key] = value
    return fields


def _sections(text):
    """Split on single-hash headings into {heading: text}."""
    out = {}
    for part in re.split(r"^(?=# [^#\n])", text, flags=re.M):
        match = re.match(r"# (.+)\n", part)
        if match:
            out[match.group(1).strip()] = part
    return out


def _steps(text):
    """Split the Workflow into {step number: text}, from each '## Step N.' heading to the next one."""
    out = {}
    for part in re.split(r"^(?=## Step \d+\. )", text, flags=re.M):
        match = re.match(r"## Step (\d+)\. ", part)
        if match:
            out[int(match.group(1))] = part
    return out


def _delegations(text):
    """(expert, instruction) for every `delegate --target X --instruction '...'` line."""
    return [(m.group(1), m.group(2)) for m in DELEGATE_LINE.finditer(text)]


def _table_rows(text, heading):
    """Markdown table rows under `heading`, as lists of cell texts. Separator rows are left out."""
    body = text.split(heading, 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in body.splitlines():
        if line.startswith("|") and not re.fullmatch(r"\|[\s|:-]+\|", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def _package_files():
    found = []
    for dirpath, _dirs, names in os.walk(PKG):
        for name in names:
            found.append(os.path.relpath(os.path.join(dirpath, name), PKG).replace(os.sep, "/"))
    return sorted(found)


def _ground_truth_item_keys(spec):
    keys = set(spec["items"])
    keys |= {key for document in spec["documents"] for key in document.get("matches", [])}
    keys |= {key for photo in spec["photos"] for key in photo["items"]}
    return keys


SKILL_TEXT = _read(os.path.join(PKG, "SKILL.md"))
README_TEXT = _read(os.path.join(ROOT, "README.md"))
PROPOSAL_TEXT = _read(os.path.join(ROOT, "submission", "proposal.md"))
CATALOG = _load_json(KIT_CATALOG)
CLIS = {cli["name"]: cli for cli in CATALOG["clis"]}
CATALOG_EXPERTS = {cli["agent"] for cli in CATALOG["clis"]}
SECTIONS = _sections(SKILL_TEXT)
STEPS = _steps(SKILL_TEXT)
COMPLETION = SECTIONS.get("Completion and failure", "")
CAPABILITY_SECTION = SECTIONS.get("Generation-time capability evidence", "")
DELEGATE_LINE = re.compile(r"^delegate --target (\S+) --instruction '(.*)'\s*$", re.M)
CAPABILITY_LINE = re.compile(r"^- `([^`]+)` (?:->|→) `([^`]+)`\s*$", re.M)
LINK = re.compile(r"\]\(([^)\s]+)\)")
DECOY_ID = re.compile(r"-D\d+$")
PACKAGE_FILES = _package_files()
REFERENCE_FILES = sorted(os.listdir(REFS))
CASE_IDS = [case["id"] for case in CASES]
ABSENT_CASES = [case for case in CASES if case.get("absent_items")]
EVENT_CASES = [case for case in CASES if case.get("expect_events")]

WRITE_WORD = re.compile(
    r"\b(?:create|creates|save|saves|copy|copies|move|moves|delete|rename|write|writes|mkdir|cpmv|echo|touch"
    r"|chtimes|album)\b|\bmake (?:a|an|the)\b",
    re.I,
)
IMPERATIVE_WRITE = re.compile(
    r"(?:^|[.!?:;]\s+|\b(?:then|and|also)\s+|\n\s*(?:\d+\.|-)\s+|'\s*|\"\s*)"
    r"(create|save|copy|move|delete|rename|write|make|mkdir|echo|touch|cpmv|chtimes)\b",
    re.I | re.M,
)

CREDENTIAL_PATTERNS = {
    "key-token-or-password-assignment": r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*['\"][^'\"]+['\"]",
    "openai-style-key": r"\bsk-[A-Za-z0-9]{16,}",
    "aws-access-key": r"\bAKIA[0-9A-Z]{16}\b",
    "google-api-key": r"\bAIza[0-9A-Za-z_\-]{35}\b",
    "github-token": r"\bgh[pousr]_[A-Za-z0-9]{36}\b",
    "slack-token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "private-key-block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "bearer-token": r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}",
}
PERSONAL_DATA_PATTERNS = {
    "e-mail-address": r"\b[\w.+-]+@[\w-]+\.[A-Za-z]{2,}\b",
    "french-mobile-number": r"\b0[1-9](?:[ .-]?\d{2}){4}\b",
    "international-phone-number": r"\+\d{1,3}[ .-]?\(?\d{1,4}\)?(?:[ .-]?\d{2,4}){3,4}\b",
    "iban": r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}\b",
    "payment-card-number": r"\b(?:\d[ -]?){13,16}\b",
    "french-social-security-number": r"\b[12] \d{2} \d{2} \d{2} \d{3} \d{3} \d{2}\b",
}


def _readme_triples():
    """(expert, CLI, action) for every action named in the README expert table."""
    triples = []
    for expert_cell, capabilities, _why in _table_rows(README_TEXT, README_EXPERT_HEADING):
        if not expert_cell.startswith("`"):
            continue  # the header row
        expert = expert_cell.strip("`")
        for segment in capabilities.split(";"):
            cli, names = re.match(r"\s*`([^`]+)`\s+(.+)$", segment).groups()
            triples += [(expert, cli, name.strip()) for name in names.split(",")]
    return triples


def _proposal_pairs():
    """(CLI, action) for every action named in the proposal's capability table."""
    pairs = []
    for step, capabilities in _table_rows(PROPOSAL_TEXT, PROPOSAL_CAPABILITY_HEADING):
        if step == "Step":
            continue  # the header row
        for segment in capabilities.split(";"):
            cli, names = re.match(r"\s*(\S+)\s+(.+)$", segment).groups()
            pairs += [(cli, name.strip()) for name in names.split(",")]
    return pairs


README_TRIPLES = _readme_triples()
PROPOSAL_PAIRS = _proposal_pairs()


def _package_hits(pattern):
    hits = []
    for name in PACKAGE_FILES:
        for match in re.finditer(pattern, _read(os.path.join(PKG, name))):
            hits.append(f"{name}: {match.group(0)}")
    return hits


def _imperative_writes(text):
    return [match.group(1) for match in IMPERATIVE_WRITE.finditer(text)]


# Frontmatter and sections


def test_skill_name_is_lowercase_hyphenated_between_2_and_64_characters():
    name = _frontmatter(SKILL_TEXT)["name"]
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) and 2 <= len(name) <= 64, name


def test_skill_description_is_at_most_1024_characters():
    description = _frontmatter(SKILL_TEXT)["description"]
    assert 0 < len(description) <= 1024, len(description)


@pytest.mark.parametrize("heading", REQUIRED_SECTIONS)
def test_skill_has_the_required_section(heading):
    assert re.search(rf"^# {re.escape(heading)}$", SKILL_TEXT, re.M), heading


@pytest.mark.parametrize("state", DELEGATION_STATES)
def test_completion_and_failure_handles_the_delegation_state(state):
    assert re.search(rf"^- `{state}`: ", COMPLETION, re.M), state


# Experts and the catalog


def test_every_delegate_targets_an_expert_that_owns_clis_in_the_catalog():
    delegate_lines = re.findall(r"delegate --target", SKILL_TEXT)
    targets = [expert for expert, _instruction in _delegations(SKILL_TEXT)]
    assert len(targets) == len(delegate_lines) and targets, "every delegate line must parse"
    unknown = sorted(set(targets) - CATALOG_EXPERTS)
    assert not unknown, unknown


def test_every_capability_evidence_line_names_the_catalog_owner_of_its_cli():
    pairs = CAPABILITY_LINE.findall(CAPABILITY_SECTION)
    assert pairs, "the capability evidence section lists its CLIs"
    wrong = [
        (cli, agent, CLIS.get(cli, {}).get("agent"))
        for cli, agent in pairs
        if cli not in CLIS or CLIS[cli]["agent"] != agent
    ]
    assert not wrong, wrong


@pytest.mark.parametrize(
    ("expert", "cli", "action"),
    README_TRIPLES,
    ids=[f"{expert}-{cli}-{action}" for expert, cli, action in README_TRIPLES],
)
def test_readme_expert_table_action_exists_under_the_expert_on_its_row(expert, cli, action):
    owner = CLIS.get(cli)
    assert owner is not None and owner["agent"] == expert, (cli, expert)
    assert action in {item["name"] for item in owner["actions"]}, action


def test_readme_expert_table_names_the_five_experts_and_the_claimed_action_count():
    assert {expert for expert, _cli, _action in README_TRIPLES} == EXPECTED_EXPERTS
    claimed = int(re.search(r"(\d+) catalog actions", README_TEXT).group(1))
    assert claimed == len(README_TRIPLES)


@pytest.mark.parametrize(
    ("cli", "action"),
    PROPOSAL_PAIRS,
    ids=[f"{cli}-{action}" for cli, action in PROPOSAL_PAIRS],
)
def test_proposal_capability_action_exists_in_its_catalog_cli(cli, action):
    assert cli in CLIS and action in {item["name"] for item in CLIS[cli]["actions"]}, (cli, action)


# The package


@pytest.mark.parametrize("name", REFERENCE_FILES)
def test_every_reference_file_is_markdown_and_linked_from_skill_md(name):
    path = os.path.join(REFS, name)
    assert os.path.isfile(path) and name.endswith(".md"), name
    assert f"references/{name}" in LINK.findall(SKILL_TEXT), name


def test_every_link_in_skill_md_resolves():
    links = LINK.findall(SKILL_TEXT)
    assert links
    broken = []
    for link in links:
        if link.startswith(("http://", "https://", "mailto:")):
            broken.append(f"{link} (external; the package is checked offline)")
        elif link.startswith("#"):
            slugs = {
                re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in re.findall(r"^#+ (.+)$", SKILL_TEXT, re.M)
            }
            if link[1:] not in slugs:
                broken.append(link)
        elif not os.path.isfile(os.path.join(PKG, link.split("#", 1)[0])):
            broken.append(link)
    assert not broken, broken


def test_package_holds_only_markdown_files():
    assert PACKAGE_FILES
    assert [name for name in PACKAGE_FILES if not name.endswith(".md")] == []


def test_package_holds_at_most_100_files():
    assert len(PACKAGE_FILES) <= 100, len(PACKAGE_FILES)


def test_every_package_file_is_at_most_1_mb():
    too_big = {
        name: os.path.getsize(os.path.join(PKG, name))
        for name in PACKAGE_FILES
        if os.path.getsize(os.path.join(PKG, name)) > MB
    }
    assert not too_big, too_big


@pytest.mark.parametrize("pattern", list(CREDENTIAL_PATTERNS.values()), ids=list(CREDENTIAL_PATTERNS))
def test_package_has_no_credential_like_string(pattern):
    assert not _package_hits(pattern)


@pytest.mark.parametrize("pattern", list(PERSONAL_DATA_PATTERNS.values()), ids=list(PERSONAL_DATA_PATTERNS))
def test_package_has_no_personal_data_marker(pattern):
    assert not _package_hits(pattern)


# Safety wording


@pytest.mark.parametrize(
    ("sentence", "flagged"),
    [
        ("Create the folder {claim folder} inside {home folder}.", True),
        ("Then save the dossier.", True),
        ("\n1. Copy each file.", True),
        ("When the user asks to create, edit or re-date a receipt, decline.", False),
        ("Whether to create a matching album for the claim photos.", False),
        ("I can't write a receipt, but I can gather the photos.", False),
        ("Run both delegations. They do not depend on each other.", False),
    ],
)
def test_write_detector_flags_imperatives_and_not_questions(sentence, flagged):
    assert bool(IMPERATIVE_WRITE.search(sentence)) is flagged


def test_steps_0_to_5_contain_no_write_instruction():
    problems = []
    for number in range(6):
        text = STEPS.get(number, "")
        if not text:
            problems.append(f"step {number} is missing")
            continue
        for _expert, instruction in _delegations(text):
            if WRITE_WORD.search(instruction):
                problems.append(f"step {number} delegates a write: {instruction[:60]}")
        problems += [f"step {number} starts with a write: {verb}" for verb in _imperative_writes(text)]
    assert not problems, problems


def test_step_6_is_the_only_step_that_writes():
    step6 = STEPS.get(6, "")
    assert "This is the only step that writes" in step6
    instructions = [instruction for _expert, instruction in _delegations(step6)]
    assert any(instruction.startswith("Create the folder") for instruction in instructions)
    assert any(instruction.startswith("Save the following") for instruction in instructions)


def test_the_step_6_gate_rule_is_in_bold_before_the_steps():
    assert GATE_RULE in SKILL_TEXT
    assert SKILL_TEXT.index(GATE_RULE) < SKILL_TEXT.index("## Step 0.")


# Rehearsal cases


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_case_has_a_valid_household_split_mode_and_approval(case):
    assert case["household"] in HOUSEHOLDS
    assert os.path.isfile(os.path.join(SPEC, f"{case['household']}.json"))
    assert case["split"] in {"dev", "held-out"}
    assert case["mode"] in {"claim", "inventory", "parcel"}
    assert case["approval"] in {"approve", "deny", "defer-once"}


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_a_cases_use_household_a_in_dev_and_b_cases_use_household_b_held_out(case):
    household, split = {"A": ("household_a", "dev"), "B": ("household_b", "held-out")}[case["id"][0]]
    assert (case["household"], case["split"]) == (household, split)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_case_item_keys_exist_in_the_ground_truth(case):
    spec, _index = _load_spec(case["household"])
    wanted = set(case["items"]) - set(case.get("absent_items", []))
    assert wanted <= _ground_truth_item_keys(spec), sorted(wanted - _ground_truth_item_keys(spec))


@pytest.mark.parametrize("case", ABSENT_CASES, ids=[case["id"] for case in ABSENT_CASES])
def test_absent_items_have_no_photo_and_no_receipt_in_the_ground_truth(case):
    spec, index = _load_spec(case["household"])
    for key in case["absent_items"]:
        photos = [p["id"] for p in spec["photos"] if key in p["items"]]
        photos += [r["id"] for r in index if key in r["items"]]
        receipts = [d["id"] for d in spec["documents"] if key in d.get("matches", [])]
        assert not photos and not receipts, (key, photos, receipts)


@pytest.mark.parametrize("case", EVENT_CASES, ids=[case["id"] for case in EVENT_CASES])
def test_expected_camera_events_exist_in_the_ground_truth(case):
    spec, _index = _load_spec(case["household"])
    events = {event["event_id"] for event in spec["events"]}
    assert set(case["expect_events"]) <= events, sorted(set(case["expect_events"]) - events)


# Ground truth integrity


@pytest.mark.parametrize("household", HOUSEHOLDS)
def test_every_document_in_the_spec_exists_in_the_archive(household):
    spec, _index = _load_spec(household)
    missing = [d["path"] for d in spec["documents"] if not os.path.isfile(os.path.join(ARCHIVE, household, d["path"]))]
    assert spec["documents"] and not missing, missing


@pytest.mark.parametrize("household", HOUSEHOLDS)
def test_every_photo_in_the_index_exists_in_the_archive(household):
    _spec, index = _load_spec(household)
    missing = [r["path"] for r in index if not os.path.isfile(os.path.join(ARCHIVE, household, r["path"]))]
    assert index and not missing, missing


@pytest.mark.parametrize("household", HOUSEHOLDS)
def test_every_expected_serial_appears_in_the_document_that_names_it(household):
    spec, _index = _load_spec(household)
    checked = 0
    for key, item in spec["items"].items():
        serial = item.get("serial")
        if not serial:
            continue
        checked += 1
        docs = [d for d in spec["documents"] if key in d.get("matches", []) and serial in d.get("serials", {}).values()]
        assert docs, f"{key}: serial {serial} is in no document that matches the item"
        for doc in docs:
            labels = {line[0] for line in doc["lines"]}
            named = [label for label, value in doc["serials"].items() if value == serial]
            assert any(label in labels for label in named), (key, doc["id"])
    assert checked, "the household has serial numbers to check"


@pytest.mark.parametrize("household", HOUSEHOLDS)
def test_every_expected_price_appears_on_a_line_that_names_the_item(household):
    spec, _index = _load_spec(household)
    checked = 0
    for key, item in spec["items"].items():
        names = [name for name in (item.get("brand"), item.get("model")) if name]
        if not names:
            continue
        checked += 1
        priced = [
            (doc["id"], line[0])
            for doc in spec["documents"]
            if key in doc.get("matches", [])
            for line in doc["lines"]
            if line[2]
        ]
        assert priced, f"{key}: no priced line on a matching document"
        assert any(name.lower() in label.lower() for _doc, label in priced for name in names), (key, priced)
    assert checked, "the household has branded items to check"


@pytest.mark.parametrize("household", HOUSEHOLDS)
def test_no_decoy_photo_is_listed_as_expected_for_an_item(household):
    spec, index = _load_spec(household)
    decoys = {p["id"] for p in spec["photos"] if DECOY_ID.search(p["id"])}
    assert decoys, "the household has decoy photos"
    assert {r["id"] for r in index if DECOY_ID.search(r["id"])} == decoys
    listed = {p["id"] for p in spec["photos"] if p["items"]} | {r["id"] for r in index if r["items"]}
    assert not decoys & listed, sorted(decoys & listed)
