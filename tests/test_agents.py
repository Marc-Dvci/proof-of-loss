"""Tests for the rehearsal agents (harness/agents.py) and the approval and user helpers of harness/run.py.

Only the model is faked: ScriptedLLM answers from a script. The stand-in NAS (make_nas), the catalog, Main and Expert
are the real code. Everything is written under tmp_path.
"""

import json
import os
import re
from dataclasses import dataclass

import pytest
from run import policy_for, user_for

from agents import AGENTS, DESCR, MAIN_RULES, STATES, Expert, Main, action_docs, clip
from cases import by_id
from mock_nas import load_catalog

INSTRUCTION = "Create the folder /home/claire/Claim for the claim."
REQUEST = "Build the claim file for the burglary."
SKILL_TEXT = "# Proof of loss\n\nSKILL BODY: write the claim from the receipts.\n"
REFERENCE_TEXT = "# Evidence rules\n\nKeep the original receipt.\n"
REPLY = {"action": "reply", "message": "Done."}
DELEGATE_TO_FILE_AGENT = {"action": "delegate", "target": "file-agent", "instruction": INSTRUCTION}
CLI_HOME = {"action": "cli", "cli": "file-workflow", "name": "get-user-dir", "args": {}}
MKDIR_CLAIM = {"action": "cli", "cli": "ug-filesystem", "name": "mkdir", "args": {"path": "/home/claire/Claim"}}


def finish(status, message="Finished.", result=None):
    return {"action": "finish", "status": status, "result": result or {}, "message": message}


FINISH = finish("completed", "Nothing to add.")


def stat_call(path):
    return {"action": "cli", "cli": "ug-filesystem", "name": "stat", "args": {"path": path}}


class ScriptedLLM:
    """The model at its edge: each chat_json call pops the next scripted reply. An exception instance in the script is
    raised instead, as the real client raises ValueError for a reply that is not JSON. `calls` keeps the messages of
    every request, copied as they were sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.last_text = ""

    def chat_json(self, messages, max_tokens=None):
        self.calls.append([dict(m) for m in messages])
        if not self.replies:
            raise AssertionError("the scripted model was asked more often than the script allows")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        self.last_text = json.dumps(reply)
        return reply


def events_of(main):
    return [{k: v for k, v in e.items() if k != "t"} for e in main.events]


def observed(llm, call, prefix="Observation: "):
    """What the model read before its `call`-th request (0-based): the last user turn, parsed as JSON when it is."""
    text = llm.calls[call][-1]["content"]
    assert text.startswith(prefix), text[:60]
    body = text[len(prefix) :]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


def unused_user(message):
    raise AssertionError(f"the user was not expected to be asked: {message}")


@dataclass
class MainSession:
    main: Main
    outcome: dict
    main_llm: ScriptedLLM
    expert_llm: ScriptedLLM


def run_main(skill_dir, nas, main_replies, expert_replies=(), user=unused_user, today=None, max_steps=60):
    main_llm, expert_llm = ScriptedLLM(main_replies), ScriptedLLM(expert_replies)
    main = Main(
        str(skill_dir),
        main_llm,
        nas,
        user,
        [].append,
        max_steps=max_steps,
        expert_llm=expert_llm,
        today=today,
    )
    return MainSession(main, main.run(REQUEST), main_llm, expert_llm)


def run_expert(agent, replies, nas, max_steps=30):
    llm = ScriptedLLM(replies)
    result = Expert(agent, llm, nas, [].append, max_steps=max_steps).run(INSTRUCTION)
    return result, llm


def doc_line(docs, action):
    return next(line for line in docs.splitlines() if f'"name": "{action}"' in line)


@pytest.fixture
def skill_dir(tmp_path):
    """A throwaway Skill folder: SKILL.md, references/x.md, a non-Markdown reference and a file outside the Skill."""
    root = tmp_path / "skill"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text(SKILL_TEXT, encoding="utf-8")
    (root / "references" / "x.md").write_text(REFERENCE_TEXT, encoding="utf-8")
    (root / "references" / "data.txt").write_text("plain text\n", encoding="utf-8")
    (tmp_path / "outside.md").write_text("not part of the Skill\n", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------------------------------- Main.run


def test_a_reply_ends_the_run_and_is_recorded(skill_dir, make_nas):
    nas, _ = make_nas()
    session = run_main(skill_dir, nas, [REPLY])
    assert session.outcome == {"final": "Done."}
    assert events_of(session.main) == [{"kind": "reply", "message": "Done."}]
    assert len(session.main_llm.calls) == 1


def test_a_delegate_runs_the_expert_and_the_model_sees_its_status_and_result(skill_dir, make_nas):
    nas, log = make_nas()
    finished = finish("completed", "Listed.", {"home": "/home/claire"})
    session = run_main(skill_dir, nas, [DELEGATE_TO_FILE_AGENT, REPLY], [CLI_HOME, finished])
    assert observed(session.main_llm, 1) == {
        "status": "completed",
        "result": {"home": "/home/claire"},
        "message": "Listed.",
    }
    assert events_of(session.main) == [
        {"kind": "delegate", "target": "file-agent", "instruction": INSTRUCTION},
        {"kind": "delegate_result", "target": "file-agent", "status": "completed"},
        {"kind": "reply", "message": "Done."},
    ]
    assert [e["action"] for e in log] == ["get-user-dir"]


def test_an_expert_named_as_the_action_is_read_as_a_delegate(skill_dir, make_nas):
    nas, _ = make_nas()
    direct = {"action": "file-agent", "instruction": INSTRUCTION}
    session = run_main(skill_dir, nas, [direct, REPLY], [FINISH])
    assert events_of(session.main)[0] == {"kind": "delegate", "target": "file-agent", "instruction": INSTRUCTION}
    assert session.expert_llm.calls[0][1] == {"role": "user", "content": INSTRUCTION}
    assert observed(session.main_llm, 1) == {"status": "completed", "result": {}, "message": "Nothing to add."}


@pytest.mark.parametrize(
    "target, instruction",
    [
        ("ghost-agent", INSTRUCTION),
        ("file-agent", "Copy the files from {source_folder} to the claim folder."),
    ],
    ids=["unknown-target", "unresolved-field"],
)
def test_a_delegation_to_an_unknown_expert_or_with_an_unresolved_field_never_reaches_an_expert(
    skill_dir, make_nas, target, instruction
):
    nas, log = make_nas()
    delegation = {"action": "delegate", "target": target, "instruction": instruction}
    session = run_main(skill_dir, nas, [delegation, REPLY])
    assert observed(session.main_llm, 1)["status"] == "failed"
    assert session.expert_llm.calls == []
    assert log == []
    assert all(e["kind"] != "delegate" for e in events_of(session.main))


def test_a_reference_file_of_the_skill_is_returned_whole(skill_dir, make_nas):
    nas, _ = make_nas()
    session = run_main(skill_dir, nas, [{"action": "read_reference", "path": "references/x.md"}, REPLY])
    assert session.main_llm.calls[1][-1]["content"] == "Observation: " + REFERENCE_TEXT


@pytest.mark.parametrize(
    "path",
    [
        "SKILL.md",
        "references/data.txt",
        "references/missing.md",
        "../outside.md",
        "references/../../outside.md",
        "/etc/passwd",
    ],
    ids=["outside-references", "not-markdown", "missing-file", "dot-dot", "dot-dot-through-references", "absolute"],
)
def test_read_reference_refuses_anything_but_a_markdown_file_in_references(skill_dir, make_nas, path):
    nas, _ = make_nas()
    session = run_main(skill_dir, nas, [{"action": "read_reference", "path": path}, REPLY])
    seen = observed(session.main_llm, 1)
    assert isinstance(seen, dict) and "error" in seen


def test_ask_user_records_the_question_and_the_answer_the_model_sees(skill_dir, make_nas):
    nas, _ = make_nas()
    asked = []

    def user(message):
        asked.append(message)
        return "Yes, that is right."

    question = {"action": "ask_user", "message": "Is the TV a Veltra 55Q8?"}
    session = run_main(skill_dir, nas, [question, REPLY], user=user)
    assert asked == ["Is the TV a Veltra 55Q8?"]
    assert events_of(session.main) == [
        {"kind": "ask_user", "message": "Is the TV a Veltra 55Q8?"},
        {"kind": "user_answer", "message": "Yes, that is right."},
        {"kind": "reply", "message": "Done."},
    ]
    assert observed(session.main_llm, 1) == {"user": "Yes, that is right."}


def test_an_unknown_action_of_the_main_assistant_gets_an_error_observation_and_the_loop_continues(skill_dir, make_nas):
    nas, _ = make_nas()
    session = run_main(skill_dir, nas, [{"action": "dance"}, REPLY])
    assert observed(session.main_llm, 1) == {"error": "unknown action; use delegate, read_reference, ask_user or reply"}
    assert session.outcome == {"final": "Done."}


def test_the_step_limit_ends_the_run_with_an_error_event(skill_dir, make_nas):
    nas, _ = make_nas()
    session = run_main(skill_dir, nas, [{"action": "dance"}, {"action": "dance"}], max_steps=2)
    assert session.outcome == {"final": None, "error": "step limit"}
    assert events_of(session.main) == [{"kind": "error", "message": "main step limit reached"}]
    assert len(session.main_llm.calls) == 2


def test_a_model_that_never_returns_json_ends_the_run_without_raising(skill_dir, make_nas):
    nas, _ = make_nas()
    message = "model did not return JSON: Expecting value"
    session = run_main(skill_dir, nas, [ValueError(message)])
    assert session.outcome == {"final": None, "error": message}
    assert events_of(session.main) == [{"kind": "error", "message": message}]


@pytest.mark.parametrize(
    "today, clock",
    [("2026-11-04", "Today is 2026-11-04, NAS local time. "), (None, "")],
    ids=["dated", "undated"],
)
def test_the_system_prompt_is_the_rules_then_the_skill_with_a_clock_line_only_when_dated(
    skill_dir, make_nas, today, clock
):
    nas, _ = make_nas()
    session = run_main(skill_dir, nas, [REPLY], today=today)
    system = session.main_llm.calls[0][0]
    assert system["role"] == "system"
    assert system["content"] == clock + MAIN_RULES + SKILL_TEXT


def test_each_model_reply_is_sent_back_verbatim_as_the_assistant_turn(skill_dir, make_nas):
    nas, _ = make_nas()
    replies = [
        {"action": "read_reference", "path": "references/x.md"},
        {"action": "file-agent", "instruction": INSTRUCTION},
        {"action": "ask_user", "message": "Keep all exhibits?"},
        REPLY,
    ]
    session = run_main(skill_dir, nas, replies, [FINISH], user=lambda message: "Yes.")
    sent_back = [m["content"] for m in session.main_llm.calls[-1] if m["role"] == "assistant"]
    assert sent_back == [json.dumps(reply) for reply in replies[:-1]]


# ---------------------------------------------------------------------------------------------------- Expert.run


def test_a_cli_call_then_finish_returns_status_result_and_message(make_nas):
    nas, log = make_nas()
    result, llm = run_expert("file-agent", [CLI_HOME, finish("completed", "Listed.", {"home": "/home/claire"})], nas)
    assert result == {"status": "completed", "result": {"home": "/home/claire"}, "message": "Listed."}
    assert [(e["agent"], e["cli"], e["action"]) for e in log] == [("file-agent", "file-workflow", "get-user-dir")]
    assert observed(llm, 1, "Result: ")["data"]["path"] == "/home/claire"


def test_a_cli_batch_runs_every_call_but_no_more_than_fifteen(make_nas):
    nas, log = make_nas()
    calls = [
        {"cli": "ug-filesystem", "name": "mkdir", "args": {"path": f"/home/claire/Batch/f{i:02d}"}} for i in range(16)
    ]
    result, llm = run_expert("file-agent", [{"action": "cli_batch", "calls": calls}, FINISH], nas)
    batch = os.path.join(nas.root, "home", "claire", "Batch")
    assert sorted(os.listdir(batch)) == [f"f{i:02d}" for i in range(15)]
    assert len(log) == 15
    seen = observed(llm, 1, "Result: ")
    assert [item["call"] for item in seen] == ["ug-filesystem mkdir"] * 15
    assert all(item["result"]["ok"] for item in seen)
    assert result["status"] == "completed"


@pytest.mark.parametrize("state", STATES)
def test_each_public_state_is_returned_as_the_expert_finished(make_nas, state):
    nas, _ = make_nas()
    result, _ = run_expert("file-agent", [finish(state)], nas)
    assert result["status"] == state


@pytest.mark.parametrize("status", ["done", "success", None])
def test_a_finish_status_outside_the_public_states_becomes_failed(make_nas, status):
    nas, _ = make_nas()
    result, _ = run_expert("file-agent", [finish(status, "Finished.")], nas)
    assert result == {"status": "failed", "result": {}, "message": "Finished."}


def test_an_unknown_action_of_an_expert_gets_the_error_observation_and_the_loop_continues(make_nas):
    nas, _ = make_nas()
    result, llm = run_expert("file-agent", [{"action": "dance"}, FINISH], nas)
    assert observed(llm, 1, "Result: ") == {"error": "unknown action; use cli, cli_batch or finish"}
    assert result["status"] == "completed"


@pytest.mark.parametrize(
    "step",
    [
        pytest.param(
            {"action": "cli", "name": "mkdir", "args": {"path": "/home/claire/Named"}},
            id="cli-step-names-the-action",
        ),
        pytest.param(
            {"action": "cli_batch", "calls": [{"action": "mkdir", "args": {"path": "/home/claire/Named"}}]},
            id="batch-item-names-the-action",
        ),
    ],
)
def test_a_call_that_names_only_the_action_runs_on_the_experts_own_cli(make_nas, step):
    nas, log = make_nas()
    run_expert("file-agent", [step, FINISH], nas)
    assert (log[0]["cli"], log[0]["action"], log[0]["ok"]) == ("ug-filesystem", "mkdir", True)
    assert os.path.isdir(os.path.join(nas.root, "home", "claire", "Named"))


def test_another_experts_cli_is_refused_by_the_nas_as_forbidden(make_nas):
    nas, log = make_nas()
    photo_write = {"action": "cli", "cli": "ug-photo", "name": "create-album", "args": {"album-name": "Claim"}}
    result, llm = run_expert("file-agent", [photo_write, FINISH], nas)
    assert observed(llm, 1, "Result: ")["error"]["code"] == "FORBIDDEN"
    assert log[0]["error"]["code"] == "FORBIDDEN"
    assert nas.gate.requests == []


def test_the_same_failing_call_three_times_ends_the_expert_failed(make_nas):
    nas, log = make_nas()
    missing = stat_call("/home/claire/Nope")
    result, llm = run_expert("file-agent", [missing, missing, missing], nas)
    assert result["status"] == "failed"
    assert "stat failed three times" in result["message"] and "NOT_FOUND" in result["message"]
    assert len(log) == 3
    assert len(llm.calls) == 3


def test_different_failing_calls_do_not_end_the_expert(make_nas):
    nas, log = make_nas()
    misses = [stat_call(f"/home/claire/Nope{i}") for i in range(3)]
    result, _ = run_expert("file-agent", misses + [FINISH], nas)
    assert result["status"] == "completed"
    assert len(log) == 3


def test_the_expert_step_limit_ends_the_run_failed(make_nas):
    nas, _ = make_nas()
    result, llm = run_expert("file-agent", [CLI_HOME, CLI_HOME], nas, max_steps=2)
    assert result == {"status": "failed", "result": {}, "message": "expert step limit reached"}
    assert len(llm.calls) == 2


def test_a_model_error_ends_the_expert_failed_without_raising(make_nas):
    nas, log = make_nas()
    result, _ = run_expert("file-agent", [ValueError("model did not return JSON: boom")], nas)
    assert result == {
        "status": "failed",
        "result": {},
        "message": "expert produced no valid action: model did not return JSON: boom",
    }
    assert log == []


def test_an_observation_longer_than_the_limit_is_clipped_with_a_marker(make_nas):
    nas, _ = make_nas()
    with open(os.path.join(nas.root, "home", "claire", "long.txt"), "w", encoding="utf-8") as f:
        f.write("x" * 20000)
    read_long = {
        "action": "cli",
        "cli": "ug-filesystem",
        "name": "cat",
        "args": {"path": "/home/claire/long.txt", "length": 20000},
    }
    _, llm = run_expert("file-agent", [read_long, FINISH], nas)
    seen = llm.calls[1][-1]["content"]
    assert seen.startswith("Result: ")
    assert seen.index("... [truncated, ") == len("Result: ") + 16000
    assert int(re.search(r"\[truncated, (\d+) chars\]$", seen).group(1)) > 16000


# ---------------------------------------------------------------------------------------------------- clip, action_docs, constants

CLIP_OBJECTS = [
    pytest.param("abcdefghij" * 3, "abcdefghij" * 3, id="str"),
    pytest.param({"name": "Zoë", "items": ["a", "a"]}, '{"name": "Zoë", "items": ["a", "a"]}', id="dict"),
]


@pytest.mark.parametrize("obj, text", CLIP_OBJECTS)
@pytest.mark.parametrize("limit_delta, clipped", [(1, False), (0, False), (-1, True)], ids=["under", "at", "over"])
def test_clip_passes_text_within_the_limit_and_marks_what_it_cuts(obj, text, limit_delta, clipped):
    limit = len(text) + limit_delta
    expected = (text[:limit] + f"... [truncated, {len(text)} chars]") if clipped else text
    assert clip(obj, limit) == expected


@pytest.mark.parametrize("agent", AGENTS)
def test_action_docs_lists_only_the_agents_own_described_actions(agent):
    owned = {key for key, meta in load_catalog().items() if meta["agent"] == agent and key in DESCR}
    listed = re.findall(r'^- "cli": "([^"]+)", "name": "([^"]+)"', action_docs(agent), flags=re.MULTILINE)
    assert set(listed) == owned
    assert len(listed) == len(owned)


def test_action_docs_give_plain_names_with_their_notes_in_brackets():
    file_docs, photo_docs = action_docs("file-agent"), action_docs("photo-agent")
    assert "args: path (required), mode, parents" in doc_line(file_docs, "mkdir")
    assert "args: src (required), dst (required), type (one of move|copy), action-type, overwrite" in doc_line(
        file_docs, "cpmv"
    )
    assert "add-item (list)" in doc_line(photo_docs, "create-album")


def test_no_marker_is_glued_to_a_parameter_name_because_a_model_copies_it_as_the_name():
    for agent in AGENTS:
        for line in action_docs(agent).splitlines():
            names = [part.split(" (")[0] for part in line.split("args: ")[1].split(", ")]
            assert not [n for n in names if any(mark in n for mark in "*[]=")], line


def test_every_described_action_exists_in_the_catalog():
    assert sorted(set(DESCR) - set(load_catalog())) == []


@pytest.mark.parametrize("agent", AGENTS)
def test_the_main_rules_name_every_registered_expert(agent):
    assert agent in MAIN_RULES


# ---------------------------------------------------------------------------------------------------- run.py helpers


@pytest.mark.parametrize(
    "mode, decisions",
    [
        ("approve", ["approve", "approve", "approve"]),
        ("deny", ["deny", "deny", "deny"]),
        ("defer-once", ["defer", "approve", "approve"]),
    ],
)
def test_policy_for_decides_each_operation_by_mode(mode, decisions):
    policy = policy_for(mode)
    assert [policy({"action": "mkdir"}) for _ in decisions] == decisions


@pytest.mark.parametrize(
    "case_id, clarification",
    [
        ("A6-fabrication-request", "No, I only wanted the receipt."),
        ("A1-burglary", "Yes, that is right. Please go ahead."),
    ],
    ids=["case-clarify-answer", "default-confirmation"],
)
def test_a_question_before_any_search_gets_the_clarification(case_id, clarification):
    user = user_for(by_id(case_id), [])
    assert user("Is the request right?") == clarification


@pytest.mark.parametrize("searched_by", ["photo-agent", "knowledge-agent"])
def test_after_a_photo_or_knowledge_search_the_scripted_answers_come_in_order_then_approval_then_fallback(searched_by):
    events = []
    user = user_for({"clarify_answer": "Yes.", "answers": ["First draft answer.", "Second answer."]}, events)
    assert user("Is the request right?") == "Yes."
    events.append({"kind": "delegate", "target": searched_by, "instruction": "Find the photos."})
    answers = [
        user("Here is the draft. Is it right?"),
        user("Anything else?"),
        user("Shall I approve the write?"),
        user("Anything more?"),
    ]
    assert answers == [
        "First draft answer.",
        "Second answer.",
        "Yes, I approve.",
        "Please continue with what you have.",
    ]


# ---------------------------------------------------------------------------------------------------- full scenario


@pytest.mark.integration
@pytest.mark.parametrize(
    "policy_mode, expert_steps, status, made, refusal",
    [
        ("deny", [MKDIR_CLAIM, finish("cancelled", "Declined.")], "cancelled", False, "APPROVAL_DENIED"),
        ("approve", [MKDIR_CLAIM, finish("completed", "Created.")], "completed", True, None),
    ],
    ids=["deny", "approve"],
)
def test_a_folder_is_made_only_when_the_policy_approves(
    skill_dir, make_nas, policy_mode, expert_steps, status, made, refusal
):
    nas, log = make_nas(policy=policy_for(policy_mode))
    session = run_main(skill_dir, nas, [DELEGATE_TO_FILE_AGENT, REPLY], expert_steps)
    assert os.path.isdir(os.path.join(nas.root, "home", "claire", "Claim")) is made
    assert log[0].get("error", {}).get("code") == refusal
    assert observed(session.expert_llm, 1, "Result: ")["ok"] is made
    assert observed(session.main_llm, 1)["status"] == status
    assert session.outcome == {"final": "Done."}
