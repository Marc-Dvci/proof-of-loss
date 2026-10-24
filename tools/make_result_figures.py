"""Build gallery figure sources from a finished rehearsal run (real outputs only).

    python tools/make_result_figures.py runs/<stamp> [--case A1-burglary]

Writes docs/figures/src/dossier.html (the dossier the run saved), conversation.html (what the user saw) and
results.html (tiles from summary.json and score.json files), ready for tools/render_figures.py.
"""
import argparse
import glob
import html
import json
import os

import markdown

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC = os.path.join(ROOT, "docs", "figures", "src")

BASE_CSS = """
html, body { margin: 0; background: #ffffff; }
body { width: 1200px; height: 800px; overflow: hidden; font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
       color: #17211c; }
"""


def dossier_html(run_case_dir):
    path = glob.glob(os.path.join(run_case_dir, "nas", "**", "CLAIM-DOSSIER*.md"), recursive=True)[0]
    text = open(path, encoding="utf-8").read()
    body = markdown.markdown(text, extensions=["tables", "fenced_code"])
    rel = os.path.relpath(path, os.path.join(run_case_dir, "nas")).replace("\\", "/")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE_CSS}
.wrap {{ padding: 34px 56px; columns: 2; column-gap: 46px; height: 732px; column-fill: auto; }}
.path {{ font-size: 12px; color: #0f8a55; letter-spacing: .03em; margin-bottom: 6px; }}
h1 {{ font-size: 21px; margin: 0 0 6px 0; }} h2 {{ font-size: 15px; margin: 12px 0 4px 0; color: #0f8a55; }}
h3 {{ font-size: 13px; margin: 8px 0 3px 0; }}
p, li {{ font-size: 11.5px; line-height: 1.35; margin: 2px 0; }}
table {{ border-collapse: collapse; font-size: 10.5px; width: 100%; margin: 3px 0 6px 0; break-inside: avoid; }}
td, th {{ border-bottom: 1px solid #e4ebe7; padding: 2px 5px 2px 0; text-align: left; vertical-align: top;
          max-width: 190px; overflow-wrap: anywhere; }}
th {{ color: #66736c; font-weight: 600; }}
code {{ font-size: 10px; }}
</style></head><body><div class="wrap"><div class="path">/{html.escape(rel)}</div>{body}</div></body></html>"""


def conversation_html(run_case_dir):
    events = json.load(open(os.path.join(run_case_dir, "events.json"), encoding="utf-8"))
    request = json.load(open(os.path.join(run_case_dir, "score.json"), encoding="utf-8"))
    rows = []
    for e in events:
        if e["kind"] == "ask_user":
            rows.append(("uliya", e["message"]))
        elif e["kind"] == "user_answer":
            rows.append(("user", e["message"]))
        elif e["kind"] == "reply":
            rows.append(("uliya", e["message"]))
    delegations = sum(1 for e in events if e["kind"] == "delegate")
    items = "".join(
        f'<div class="msg {who}"><div class="who">{"Uliya" if who == "uliya" else "User"}</div>'
        f'<div class="text">{markdown.markdown(html.escape(t[:1400]))}</div></div>' for who, t in rows)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE_CSS}
.wrap {{ padding: 30px 70px; height: 740px; overflow: hidden; }}
.meta {{ font-size: 12px; color: #66736c; letter-spacing: .04em; margin-bottom: 10px; }}
.msg {{ margin: 0 0 12px 0; max-width: 980px; }}
.msg.user {{ margin-left: 120px; }}
.who {{ font-size: 11.5px; font-weight: 650; color: #0f8a55; letter-spacing: .05em; text-transform: uppercase; }}
.msg.user .who {{ color: #66736c; }}
.text p, .text li {{ font-size: 13px; line-height: 1.4; margin: 2px 0; }}
.msg.uliya .text {{ background: radial-gradient(ellipse at left, #eef8f2 0%, #ffffff 75%); padding: 4px 0 4px 0; }}
</style></head><body><div class="wrap">
<div class="meta">{delegations} DELEGATIONS · {request.get('cli_calls')} CLI CALLS · {request.get('approval_requests')} APPROVALS</div>
{items}</div></body></html>"""


def results_html(run_dir):
    summary = json.load(open(os.path.join(run_dir, "summary.json"), encoding="utf-8"))["totals"]
    tiles = [
        ("photos cited correctly", f"{summary['photos_cited_ok']}/{summary['photos_expected']}"),
        ("receipts matched", f"{summary['receipts_cited_ok']}/{summary['receipts_expected']}"),
        ("serial numbers found", summary["serials_found"]),
        ("prices copied exactly", summary["prices_found"]),
        ("decoy photos copied", str(summary["decoys_copied"])),
        ("hashes that do not match a file", str(summary["hashes_wrong"])),
        ("amounts not in the archive", str(summary["invented_amounts"])),
        ("writes before the user's answer", str(summary["writes_before_confirmation"])),
        ("injected instruction followed", str(summary["injection_followed"])),
        ("camera events cited", summary["events_cited"]),
    ]
    cells = "".join(f'<div class="tile"><div class="n">{html.escape(v)}</div><div class="l">{html.escape(k)}</div></div>'
                    for k, v in tiles)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE_CSS}
.grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 46px 30px; padding: 150px 70px; }}
.n {{ font-size: 44px; font-weight: 650; letter-spacing: -0.02em; color: #17211c; }}
.l {{ font-size: 14px; color: #66736c; margin-top: 4px; }}
.tile:nth-child(n+5) .n {{ color: #0f8a55; }}
</style></head><body><div class="grid">{cells}</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--case", default="A1-burglary")
    args = ap.parse_args()
    case_dir = os.path.join(args.run_dir, args.case)
    for name, content in (("dossier", dossier_html(case_dir)), ("conversation", conversation_html(case_dir)),
                          ("results", results_html(args.run_dir))):
        with open(os.path.join(SRC, f"{name}.html"), "w", encoding="utf-8") as f:
            f.write(content)
        print("wrote", name)


if __name__ == "__main__":
    main()
