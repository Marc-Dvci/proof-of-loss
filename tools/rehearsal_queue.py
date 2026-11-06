"""Run rehearsal cases on a shared machine: start the model servers only when enough memory is free, stop them
and the running case if free commit memory drops too low, wait, and retry the case from scratch.

    python tools/rehearsal_queue.py --profile qwen-e4b --out runs/<name> [--cases A1-burglary,...] [--split all]

Profiles:
  g26       one server (Gemma 4 26B-A4B with its vision projector) serves everything, one slot per role
  e4b       one server (Gemma 4 E4B with its vision projector) serves the main assistant, the experts and vision
  qwen-e4b  Qwen3.5-9B serves the main assistant and experts; Gemma 4 E4B serves vision
Model paths come from LLAMA_SERVER, POL_TEXT_MODEL, POL_VISION_MODEL and POL_VISION_MMPROJ.
"""

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "harness"))
from cases import CASES  # noqa: E402

GB = 1024**3


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def free_commit_gb():
    s = MEMORYSTATUSEX()
    s.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return s.ullAvailPageFile / GB


def pagefile_can_grow_gb():
    """Room left for Windows to grow its pagefiles (configured maximum minus current size). The commit limit grows
    with them, so low free commit is only a squeeze once the pagefiles are at their maximum."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
        ) as k:
            entries = winreg.QueryValueEx(k, "PagingFiles")[0]
        max_mb = sum(int(e.split()[2]) for e in entries if len(e.split()) >= 3)
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_PageFileUsage | Measure-Object AllocatedBaseSize -Sum).Sum",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        return max(0.0, (max_mb - int(out)) / 1024)
    except Exception:
        return 0.0


def healthy(port):
    try:
        return b"ok" in urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).read()
    except Exception:
        return False


def server(port, model, ngl, ctx, mmproj=None, extra=(), parallel=1):
    args = [
        os.environ["LLAMA_SERVER"],
        "-m",
        model,
        "-ngl",
        str(ngl),
        "-c",
        str(ctx),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--jinja",
        "-fa",
        "on",
        "--parallel",
        str(parallel),
        "--threads",
        "4",
        "--cache-ram",
        "0",
        "--no-webui",
        *extra,
    ]
    if mmproj:
        args += ["--mmproj", mmproj]
    log = open(os.path.join(ROOT, "runs", f"server-{port}.log"), "a")
    return subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)


PROFILES = {
    "e4b": {
        "need_gb": 8.5,
        "llm": 8098,
        "vlm": 8098,
        "servers": lambda: [server(8098, os.environ["POL_VISION_MODEL"], 99, 32768, os.environ["POL_VISION_MMPROJ"])],
    },
    # Gemma 4 26B-A4B with its vision projector: attention, shared weights and 6 expert layers on the GPU, the other
    # experts memory-mapped (--no-repack keeps them file-backed). Three slots: main assistant, experts, NAS calls.
    # A 1024-token micro-batch holds a whole image, which the vision encoder needs. No context checkpoints: the harness
    # sends each reply back verbatim, so a prompt extends the slot's cache; restoring a sliding-window checkpoint into
    # the unified cache can abort this llama.cpp build, and a prompt that does not extend the cache is re-processed.
    "g26": {
        "need_gb": 8.0,
        "llm": 8098,
        "vlm": 8098,
        "slots": True,
        "servers": lambda: [
            server(
                8098,
                os.environ["POL_VISION_MODEL"],
                99,
                49152,
                os.environ["POL_VISION_MMPROJ"],
                extra=(
                    "--n-cpu-moe",
                    "24",
                    "--no-repack",
                    "-kvu",
                    "-b",
                    "1024",
                    "-ub",
                    "1024",
                    "--ctx-checkpoints",
                    "0",
                ),
                parallel=3,
            )
        ],
    },
    "qwen-e4b": {
        "need_gb": 14.5,
        "llm": 8099,
        "vlm": 8098,
        "servers": lambda: [
            server(8099, os.environ["POL_TEXT_MODEL"], 99, 32768),
            server(8098, os.environ["POL_VISION_MODEL"], 24, 8192, os.environ["POL_VISION_MMPROJ"]),
        ],
    },
}


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=PROFILES, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", default="")
    ap.add_argument("--split", default="all", choices=["dev", "held-out", "all"])
    ap.add_argument("--min-free-gb", type=float, default=0.8)
    ap.add_argument(
        "--need-gb", type=float, default=0.0, help="free commit needed to start the servers (default: the profile's)"
    )
    args = ap.parse_args()
    prof = PROFILES[args.profile]
    need_gb = args.need_gb or prof["need_gb"]
    out = os.path.abspath(args.out)
    wanted = [c.strip() for c in args.cases.split(",") if c.strip()] or [
        c["id"] for c in CASES if args.split == "all" or c["split"] == args.split
    ]
    procs = []

    def stop_servers():
        for p in procs:
            if p.poll() is None:
                p.kill()
        procs.clear()
        time.sleep(3)

    try:
        for case_id in wanted:
            failures = 0
            while not os.path.exists(os.path.join(out, case_id, "score.json")) and failures < 3:
                if not procs:
                    while free_commit_gb() < need_gb:
                        time.sleep(30)
                    log(f"starting servers ({free_commit_gb():.1f} GB free)")
                    procs.extend(prof["servers"]())
                    ports = {prof["llm"], prof["vlm"]}
                    for _ in range(300):
                        if all(healthy(p) for p in ports):
                            break
                        time.sleep(2)
                log(f"case {case_id}")
                shutil.rmtree(os.path.join(out, case_id), ignore_errors=True)
                run = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        os.path.join(ROOT, "harness", "run.py"),
                        "--cases",
                        case_id,
                        "--out",
                        out,
                        "--llm-url",
                        f"http://127.0.0.1:{prof['llm']}",
                        "--vlm-url",
                        f"http://127.0.0.1:{prof['vlm']}",
                    ]
                    + (["--slots"] if prof.get("slots") else []),
                    stdout=open(os.path.join(out + ".log"), "a"),
                    stderr=subprocess.STDOUT,
                )
                squeezed = False
                while run.poll() is None:
                    if free_commit_gb() < args.min_free_gb and pagefile_can_grow_gb() < 0.5:
                        squeezed = True
                        run.kill()
                        stop_servers()
                        log(f"memory squeeze ({free_commit_gb():.2f} GB free): stopped; will retry {case_id}")
                        break
                    time.sleep(2)
                if not squeezed and not os.path.exists(os.path.join(out, case_id, "score.json")):
                    failures += 1
                    log(f"case {case_id} ended without a score (attempt {failures}); restarting the servers")
                    stop_servers()
                elif not squeezed:
                    s = json.load(open(os.path.join(out, case_id, "score.json"), encoding="utf-8"))
                    log(
                        f"done {case_id}: {s.get('seconds')} s, dossier {s.get('dossier_written')}, "
                        f"writes ok {s.get('write_expectation_met')}"
                    )
    finally:
        stop_servers()
    log("all cases scored")


if __name__ == "__main__":
    main()
