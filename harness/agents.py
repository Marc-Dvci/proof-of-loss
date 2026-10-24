"""Main assistant and expert agents for the rehearsal.

The main assistant receives SKILL.md as its instructions and can act only through four JSON actions:
delegate, read_reference, ask_user and reply. Each expert receives one instruction string, sees only the
actions of the CLIs the catalog assigns to it, calls them through the mock NAS, and finishes with one of the
five public delegation states.
"""
import json
import os
import re
import time

from mock_nas import load_catalog

AGENTS = ["file-agent", "photo-agent", "document-agent", "knowledge-agent", "security-monitor-agent", "media-agent"]
STATES = ["completed", "failed", "cancelled", "waiting_user", "waiting_approval"]

DESCR = {
    ("file-workflow", "get-user-dir"): "real home folder of the current user and its top-level folders",
    ("ug-filesystem", "ls"): "list a folder",
    ("ug-filesystem", "find"): "find files under a path by glob pattern, type and modification time",
    ("ug-filesystem", "stat"): "size and times of one path",
    ("ug-filesystem", "cat"): "read a text file",
    ("ug-filesystem", "sha256sum"): "SHA-256 of one file",
    ("ug-filesystem", "md5sum"): "MD5 of one file",
    ("ug-filesystem", "mkdir"): "create a folder (parents true creates missing parents)",
    ("ug-filesystem", "cpmv"): "copy (type copy) or move one file; dst may be a folder; overwrite false by default",
    ("ug-filesystem", "echo"): "write text to a file",
    ("ug-filesystem", "touch"): "create a file",
    ("ug-filesystem", "chtimes"): "change file times",
    ("ug-filesystem", "del"): "delete a file to the recycle bin",
    ("ug-photo", "search-picture"): "filter photos: ai-object-name (list of recognised objects), ocr-contains (text in "
                                    "image), file-name-contains, camera-model, dir, start-time, end-time, page-size",
    ("ug-photo", "search-screen"): "keyword search; category scene for content, ocr for text in images",
    ("ug-photo", "meta"): "EXIF of photos: capture time, make, model, lens, body serial number, GPS",
    ("ug-photo", "vision-ocr"): "read the text in one image",
    ("ug-photo", "vision-vlm"): "ask a vision model a question about one image (path, prompt)",
    ("ug-photo", "create-album"): "create a normal album (album-name, add-item list of photo paths)",
    ("ug-photo", "albums"): "list albums",
    ("ug-document", "extract"): "extract structured facts from document files (file list, schema receipt|invoice|"
                                "auto, query)",
    ("ug-document", "qa"): "answer a question from document files",
    ("ug-document", "metadata"): "file metadata",
    ("ug-document", "writing"): "draft a document (task draft, style, query, content with the facts)",
    ("ug-knowledge", "collect-evidence"): "find passages that match a query across files under path(s), optional "
                                          "extension list",
    ("ug-knowledge", "save-text"): "save text as a file (path = folder, content, filename-hint = file name)",
    ("ug-surveillance", "cameras"): "registered cameras",
    ("ug-surveillance", "event-timeline"): "events between start-time and end-time (ISO 8601 with offset), topic list, "
                                           "identity-type, camera-id list",
    ("ug-surveillance", "event-evidence"): "snapshot or clip references for event IDs (event-id list, evidence-type, "
                                           "purpose)",
    ("ug-surveillance", "vehicle-plates"): "licence plates seen (identity-type)",
    ("ug-surveillance", "identity-resolve"): "who a person in an event is, when known",
}

EXPERT_RULES = """You are {agent}, a registered expert on a UGREEN NAS. The main assistant sent you one instruction.
Do exactly what it asks with your CLI actions, then finish.

Your actions (the cli and name values to use, purpose, effect, approval):
{actions}

Reply with ONE JSON object per turn, one of:
{{"action": "cli", "cli": "<cli>", "name": "<action>", "args": {{"<param>": <value>}}}}
{{"action": "cli_batch", "calls": [{{"cli": "...", "name": "...", "args": {{...}}}}, ...]}}   (up to 15 calls)
{{"action": "finish", "status": "completed|failed|cancelled|waiting_user|waiting_approval", "result": {{...}}, "message": "<short summary>"}}

Rules:
- Use the arg names exactly as listed (* = required, [] = takes a JSON array, =a|b = allowed values).
- Paths, IDs, times and values in your result must come from action results. Never invent them.
- When the instruction says read only, use only actions whose effect is read.
- List parameters take JSON arrays. Paths are absolute NAS paths as returned by actions.
- A result error APPROVAL_PENDING means the user has not approved yet: finish with status waiting_approval and say which operation waits.
- A result error APPROVAL_DENIED means the user declined: finish with status cancelled.
- If an action fails, fix the arguments once; if it still fails, finish with status failed and the error.
- An empty result is a valid result: finish completed with empty lists.
- Keep the finish result compact: only the fields the instruction asks for."""

MAIN_RULES = """You are Uliya, the assistant of a UGREEN AI NAS. The user's request activated the Skill below. Follow the Skill exactly.

You act only through these JSON actions, one per reply:
{"action": "delegate", "target": "<agent-id>", "instruction": "<self-contained task>"}  runs a registered expert and returns its state and result
{"action": "read_reference", "path": "references/<file>.md"}  returns a reference file of the Skill
{"action": "ask_user", "message": "<text shown to the user>"}  shows the text and waits for the user's answer
{"action": "reply", "message": "<final message to the user>"}  ends your turn

Registered experts: file-agent, photo-agent, document-agent, knowledge-agent, security-monitor-agent, media-agent.
Reply with one JSON object and nothing else.

===== SKILL.md =====
"""


def action_docs(agent, catalog_path=None):
    cat = load_catalog()
    lines = []
    for (cli, action), meta in sorted(cat.items()):
        if meta["agent"] != agent or (cli, action) not in DESCR:
            continue
        params = " ".join(f'{n}{"*" if p.get("required") else ""}{"[]" if p.get("repeatable") else ""}'
                          f'{"=" + "|".join(map(str, p["enum"])) if p.get("enum") else ""}'
                          for n, p in (meta.get("params") or {}).items())
        lines.append(f'- "cli": "{cli}", "name": "{action}" - {DESCR[(cli, action)]}; effect {meta["effect"]}; '
                     f'approval {meta["approval"]}; args: {params or "none"}')
    return "\n".join(lines)


def clip(obj, limit=6000):
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"... [truncated, {len(text)} chars]"


class Expert:
    def __init__(self, agent, llm, nas, trace, max_steps=30):
        self.agent, self.llm, self.nas, self.trace, self.max_steps = agent, llm, nas, trace, max_steps
        self.system = EXPERT_RULES.format(agent=agent, actions=action_docs(agent) or "- (no actions served)")
        owned = [(cli, a) for (cli, a), m in load_catalog().items() if m["agent"] == agent]
        self.owned = set(owned)
        self.by_action = {}
        for cli, a in owned:
            self.by_action.setdefault(a, []).append(cli)

    def _resolve(self, call):
        """A registered expert knows which of its CLIs serves an action: fix a call that names the action only."""
        cli, name = call.get("cli"), call.get("name") or call.get("action")
        if (cli, name) not in self.owned:
            if name in self.by_action and len(self.by_action[name]) == 1:
                cli = self.by_action[name][0]
            elif cli in self.by_action and len(self.by_action[cli]) == 1:
                cli, name = self.by_action[cli][0], cli
        return cli, name, call.get("args")

    def run(self, instruction):
        msgs = [{"role": "system", "content": self.system}, {"role": "user", "content": instruction}]
        failures = {}
        for step in range(self.max_steps):
            try:
                act = self.llm.chat_json(msgs, max_tokens=8192)
            except ValueError as e:
                return {"status": "failed", "result": {}, "message": f"expert produced no valid action: {e}"}
            self.trace({"who": self.agent, "step": step, "act": act})
            kind = act.get("action")
            if kind == "finish":
                status = act.get("status") if act.get("status") in STATES else "failed"
                return {"status": status, "result": act.get("result", {}), "message": act.get("message", "")}
            calls = act.get("calls") if kind == "cli_batch" else [act] if kind == "cli" else None
            if not calls:
                obs = {"error": "unknown action; use cli, cli_batch or finish"}
            else:
                obs = []
                for c in calls[:15]:
                    cli, name, cargs = self._resolve(c)
                    res = self.nas.invoke(self.agent, cli, name, cargs)
                    obs.append({"call": f"{cli} {name}", "result": res})
                    if not res["ok"]:
                        sig = json.dumps([cli, name, cargs], sort_keys=True)
                        failures[sig] = failures.get(sig, 0) + 1
                        if failures[sig] >= 3:
                            return {"status": "failed", "result": {},
                                    "message": f"{cli} {name} failed three times: {res['error']}"}
                obs = obs[0]["result"] if kind == "cli" else obs
            msgs.append({"role": "assistant", "content": json.dumps(act, ensure_ascii=False)})
            msgs.append({"role": "user", "content": "Result: " + clip(obs, 16000)})
        return {"status": "failed", "result": {}, "message": "expert step limit reached"}


class Main:
    def __init__(self, skill_dir, llm, nas, user, trace, max_steps=60, expert_llm=None):
        self.skill_dir, self.llm, self.nas, self.user, self.trace, self.max_steps = skill_dir, llm, nas, user, trace, max_steps
        self.expert_llm = expert_llm or llm
        with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8") as f:
            self.skill = f.read()
        self.events = []

    def _event(self, **kw):
        kw["t"] = time.time()
        self.events.append(kw)

    def _ref(self, path):
        norm = os.path.normpath(path).replace("\\", "/").lstrip("./")
        if not norm.startswith("references/") or not norm.endswith(".md"):
            return {"error": "only references/*.md files can be read"}
        full = os.path.join(self.skill_dir, norm)
        if not os.path.isfile(full):
            return {"error": f"no such reference: {norm}"}
        with open(full, encoding="utf-8") as f:
            return f.read()

    def run(self, request):
        msgs = [{"role": "system", "content": MAIN_RULES + self.skill}, {"role": "user", "content": request}]
        for step in range(self.max_steps):
            try:
                act = self.llm.chat_json(msgs, max_tokens=8192)
            except ValueError as e:
                self._event(kind="error", message=str(e))
                return {"final": None, "error": str(e)}
            self.trace({"who": "main", "step": step, "act": act})
            kind = act.get("action")
            if kind == "reply":
                self._event(kind="reply", message=act.get("message", ""))
                return {"final": act.get("message", "")}
            if kind == "delegate":
                target, instr = act.get("target"), act.get("instruction") or ""
                if target not in AGENTS:
                    obs = {"status": "failed", "message": f"unknown target {target}"}
                elif re.search(r"\{[a-z][a-z _-]*\}", instr):
                    obs = {"status": "failed", "message": "instruction still contains an unresolved {field}"}
                else:
                    self._event(kind="delegate", target=target, instruction=instr)
                    obs = Expert(target, self.expert_llm, self.nas, self.trace).run(instr)
                    self._event(kind="delegate_result", target=target, status=obs["status"])
            elif kind == "read_reference":
                obs = self._ref(act.get("path", ""))
            elif kind == "ask_user":
                self._event(kind="ask_user", message=act.get("message", ""))
                answer = self.user(act.get("message", ""))
                self._event(kind="user_answer", message=answer)
                obs = {"user": answer}
            else:
                obs = {"error": "unknown action; use delegate, read_reference, ask_user or reply"}
            msgs.append({"role": "assistant", "content": json.dumps(act, ensure_ascii=False)})
            msgs.append({"role": "user", "content": "Observation: " + clip(obs, 9000)})
        self._event(kind="error", message="main step limit reached")
        return {"final": None, "error": "step limit"}
