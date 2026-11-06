"""Replay a recorded rehearsal with no model and no GPU.

    python tools/replay.py A1-burglary          # one case: the conversation, the claim folder, the score
    python tools/replay.py all                  # every recorded case

The model's decisions come from the run's trace.jsonl, in their recorded order. Everything else is the real code: the
agent loops, the stand-in CLI layer with its approval gate, the copies and hashes on disk, and the scorer. The vision
answers come from the run's recorded cache. The replay then compares its score with the recorded one.
"""

import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run as rehearsal  # noqa: E402

from cases import by_id  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
EVIDENCE = os.path.join(ROOT, "evidence", "final")

# What depends on the machine and the clock, not on the decisions: left out of the comparison.
VOLATILE = ("seconds", "llm_calls", "text_model", "vision_model")


class Recording:
    """The model's decisions of one recorded run, in order."""

    def __init__(self, trace_path):
        with open(trace_path, encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
        self.acts = collections.deque(r for r in records if "who" in r and "act" in r)


class ReplayLLM:
    """Stands where harness/llm.py stands. A role reads its next decision from the recording.

    When the next recorded decision belongs to the other role, this caller's model produced no valid action in the
    recorded run: it raises the same ValueError, and the agent loop handles it the same way.
    """

    def __init__(self, recording, role):
        self.recording, self.role = recording, role
        self.calls = 0
        self.last_text = ""

    def chat_json(self, messages, max_tokens=None, retries=2):
        if self.role == "nas":
            raise LookupError("a NAS-side model call is missing from the recorded cache")
        acts = self.recording.acts
        if not acts or (acts[0]["who"] == "main") != (self.role == "main"):
            raise ValueError("model did not return JSON (as recorded)")
        act = acts.popleft()["act"]
        self.calls += 1
        self.last_text = json.dumps(act, ensure_ascii=False)
        return act

    def chat(self, messages, json_mode=True, max_tokens=None):
        """Free text inside a NAS action: the recorded decisions that follow carry the text the run kept."""
        self.calls += 1
        return "(recorded run: the text is in the next recorded decision)"

    def vision(self, image_path, prompt, max_tokens=400):
        raise LookupError(f"a vision answer is missing from the recorded cache: {image_path}")


def replay_case(case_id, out_dir, evidence=EVIDENCE, skill_dir=None):
    """Replay one recorded case into out_dir. Returns (score, recorded score, differences, decisions left over)."""
    case = by_id(case_id)
    recorded_dir = os.path.join(evidence, case_id)
    recording = Recording(os.path.join(recorded_dir, "trace.jsonl"))

    def clients(trace):
        main, expert, nas = (ReplayLLM(recording, role) for role in ("main", "expert", "nas"))
        return main, expert, nas, nas

    skill = skill_dir or os.path.join(ROOT, "skill", "proof-of-loss")
    vision_cache = os.path.join(recorded_dir, "vision_cache.json")
    score = rehearsal.run_case(case, out_dir, clients, skill, vision_cache=vision_cache)
    with open(os.path.join(recorded_dir, "score.json"), encoding="utf-8") as f:
        recorded = json.load(f)
    keys = (set(score) | set(recorded)) - set(VOLATILE)
    differences = {k: (recorded.get(k), score.get(k)) for k in sorted(keys) if recorded.get(k) != score.get(k)}
    return score, recorded, differences, len(recording.acts)


def conversation(out_dir):
    """The run as the user saw it, from events.json."""
    with open(os.path.join(out_dir, "events.json"), encoding="utf-8") as f:
        events = json.load(f)
    lines = []
    for e in events:
        if e["kind"] == "delegate":
            lines.append(f"  -> {e['target']}")
        elif e["kind"] == "delegate_result":
            lines.append(f"  <- {e['target']}: {e['status']}")
        elif e["kind"] == "ask_user":
            lines.append(f"\nUliya asks:\n{e['message']}\n")
        elif e["kind"] == "user_answer":
            lines.append(f"The user answers: {e['message']}\n")
        elif e["kind"] == "reply":
            lines.append(f"\nUliya replies:\n{e['message']}")
    return "\n".join(lines)
