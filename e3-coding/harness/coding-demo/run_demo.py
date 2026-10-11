#!/usr/bin/env python3
"""E3 part B: the coding demo (plan s2/grade_r4/E3/experiment-plan.md section 7).
  run_demo.py verify                       baselines + reference solutions (the reference is NOT saved or shown to any worker)
  run_demo.py small --ticket easy|hard [--runs 10]   Qwen3-8B in the agents loop (starts its own llama-server; refuses if one is running)
  run_demo.py big [--runs 3]               the stronger worker on the hard ticket, via the Codex CLI (operator's ChatGPT login)
  run_demo.py capture                      coding-demo-capture.json + the runs file in ./evidence
Resumable: runs are appended to coding-demo-runs.jsonl keyed by (worker, ticket, seed)."""
import argparse, hashlib, json, os, platform, re, shutil, signal, subprocess, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import harness as H
import make_demo_repo as M
H.BASE_URL = "http://127.0.0.1:8080"
RUNS = os.path.join(HERE, "runs"); RUNS_FILE = os.path.join(HERE, "coding-demo-runs.jsonl"); EVID = os.path.join(HERE, "evidence")
MODEL = "<models>/Qwen3-8B-Q4_K_M.gguf"; LLAMA = os.path.expanduser("~/llama.cpp/build/bin/llama-server")
MODEL_SHA = "120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4"
PY = "/usr/bin/python3"; MAX_TURNS = 30; SHELL_TIMEOUT = 30; TRUNC = 4000; BIG_TIMEOUT = 1200
SYSTEM = ("You are a coding worker. You are in the root folder of a small Python project. Use the shell tool to read files, edit them (for example with python3 -c, sed or a heredoc) and run the tests. "
          "When you are done, reply with DONE and one sentence on what you changed.")
SYSTEM_NOSED = ("You are a coding worker. You are in the root folder of a small Python project on macOS. Use the shell tool to read files, edit them (use python3 -c or a heredoc; do not use sed -i, it works differently on macOS) and run the tests. "
                "When you are done, reply with DONE and one sentence on what you changed.")
NUDGE = "Continue. Use the shell tool, or reply DONE."
SHELL_ONLY = [t for t in H.TOOLS if t["function"]["name"] == "shell"]
N_TESTS = {"easy": 4, "hard": 14}
sha = lambda b: hashlib.sha256(b).hexdigest()
sh = lambda c: subprocess.run(c, shell=True, capture_output=True, text=True, errors="replace").stdout.strip()

# ---------------------------------------------------------------- grading (7.7)
def tree_hashes(d):
    out = {}
    for root, _, fs in os.walk(d):
        if "__pycache__" in root: continue
        for f in fs:
            if f.endswith(".pyc"): continue
            p = os.path.join(root, f); out[os.path.relpath(p, d)] = sha(open(p, "rb").read())
    return out

def grade(run_dir, ticket):
    pristine = run_dir + ".tests-pristine"; tests = os.path.join(run_dir, "tests")
    modified = tree_hashes(tests) != tree_hashes(pristine) if os.path.isdir(tests) else True
    shutil.rmtree(tests, ignore_errors=True); shutil.copytree(pristine, tests)
    env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C"}
    try:
        p = subprocess.run([PY, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"], cwd=run_dir, capture_output=True, text=True, errors="replace", timeout=120, env=env)
        out = (p.stdout or "") + (p.stderr or ""); rc = p.returncode
    except subprocess.TimeoutExpired as e:
        out = "TIMEOUT"; rc = -1
    per = {}
    for m in re.finditer(r"^(test\w+) \(([\w.]+)\) \.\.\. (ok|FAIL|ERROR)", out, re.M):
        tid = m.group(2) if m.group(2).endswith("." + m.group(1)) else m.group(2) + "." + m.group(1)  # 3.9 prints (module.Class), 3.13 prints (module.Class.method)
        per[tid] = m.group(3) == "ok"
    passed = sum(per.values()); total = N_TESTS[ticket]
    return {"tests_modified": modified, "per_test": per, "tests_passed": passed, "tests_total": total, "passed": rc == 0 and passed == total and len(per) == total, "unittest_tail": "\n".join(out.splitlines()[-40:])}

def counts_from_output(text):
    """(passed, total) from a unittest summary in a tool output, or None."""
    m = re.search(r"Ran (\d+) tests?", text)
    if not m: return None
    total = int(m.group(1)); bad = 0
    f = re.search(r"FAILED \(([^)]*)\)", text)
    if f: bad = sum(int(x) for x in re.findall(r"(?:failures|errors)=(\d+)", f.group(1)))
    return total - bad, total

# ---------------------------------------------------------------- small worker (7.5)
def run_small(ticket, seed, variant="small"):
    d = os.path.join(RUNS, f"{variant}-{ticket}-{seed}"); shutil.rmtree(d + ".tests-pristine", ignore_errors=True); M.build(d, ticket)
    msgs = [{"role": "system", "content": SYSTEM_NOSED if variant == "small_nosed" else SYSTEM}, {"role": "user", "content": M.TICKETS[ticket]}]
    t0 = time.time(); turns = 0; nudged = False; ended_without_done = False; overflow = False; stuck = False; tps = []; pn = []; ptok = ctok = 0; seen = []
    done = False
    while turns < MAX_TURNS and not done:
        r = H.chat(msgs, tools=SHELL_ONLY, seed=seed * 100 + turns, max_tokens=2048, sampling=H.SAMPLING_OFF, thinking=False, timeout=900); turns += 1
        if r.error:
            if r.error_type == "exceed_context_size_error": overflow = True
            else: ended_without_done = True
            break
        m = r.message; content = m.get("content") or ""; calls = m.get("tool_calls") or []
        t = r.timings or {}; tps.append(t.get("predicted_per_second")); pn.append(t.get("prompt_n")); u = r.usage or {}; ptok += u.get("prompt_tokens", 0); ctok += u.get("completion_tokens", 0)
        msgs.append({"role": "assistant", "content": content, **({"tool_calls": calls} if calls else {})})
        if not calls:
            if "DONE" in content: done = True; break
            if not nudged: nudged = True; msgs.append({"role": "user", "content": NUDGE}); continue
            ended_without_done = True; break
        for c in calls:
            fn = c.get("function", {}); raw = fn.get("arguments")
            try: args = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except Exception: args = {}
            cmd = str(args.get("command", "")) if fn.get("name") == "shell" else ""
            if not cmd: out = "ERROR: call the shell tool with a command."
            else:
                rc, out = H.sandboxed(["/bin/sh", "-c", cmd], d, timeout=SHELL_TIMEOUT)
                out = (out or "")[:TRUNC]
                cc = counts_from_output(out)
                if cc: seen.append(cc[0])
            msgs.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": out})
    else:
        stuck = turns >= MAX_TURNS and not done
    stuck = stuck or (turns >= MAX_TURNS and not done)
    g = grade(d, ticket)
    improved = any(seen[i] < seen[j] for i in range(len(seen)) for j in range(i + 1, len(seen)) if seen[i] < N_TESTS[ticket])
    vals = [x for x in tps if x]
    rec = {"worker": variant, "ticket": ticket, "seed": seed, "passed": g["passed"], "tests_passed": g["tests_passed"], "tests_total": g["tests_total"], "per_test": g["per_test"], "tests_modified": g["tests_modified"],
           "turns": turns, "seconds": round(time.time() - t0, 1), "prompt_tokens": ptok, "completion_tokens": ctok, "decode_tps": {"per_turn": tps, "median": sorted(vals)[len(vals) // 2] if vals else None}, "prompt_n_per_turn": pn,
           "stuck": stuck, "nudged": nudged, "ended_without_done": ended_without_done, "context_overflow": overflow, "unittest_tail": g["unittest_tail"], "improved_after_fail": improved,
           "transcript_sha256": sha(json.dumps(msgs, default=str).encode()),
           "transcript": [{"role": m["role"], "content": (m.get("content") or "")[:1500], "calls": [((c.get("function") or {}).get("arguments") if isinstance((c.get("function") or {}).get("arguments"), str) else json.dumps((c.get("function") or {}).get("arguments")))[:1200] for c in (m.get("tool_calls") or [])]} for m in msgs]}
    shutil.rmtree(d, ignore_errors=True); shutil.rmtree(d + ".tests-pristine", ignore_errors=True)
    return rec

def done_keys():
    s = set()
    if os.path.exists(RUNS_FILE):
        for l in open(RUNS_FILE): r = json.loads(l); s.add((r["worker"], r["ticket"], r["seed"]))
    return s

def start_server():
    if subprocess.run(["pgrep", "-f", "llama-server"], capture_output=True).stdout.strip(): sys.exit("a llama-server is already running; stop it first (the shutdown run uses the Mac's GPU)")
    if sha(open(MODEL, "rb").read()) != MODEL_SHA: sys.exit("model sha256 mismatch")
    cmd = [LLAMA, "-m", MODEL, "--jinja", "--reasoning-format", "deepseek", "-c", "32768", "-np", "1", "-ngl", "all", "--port", "8080", "--log-file", os.path.join(HERE, "server.log")]
    p = subprocess.Popen(cmd, stdout=open(os.path.join(HERE, "server.out"), "w"), stderr=subprocess.STDOUT)
    for _ in range(200):
        try:
            if json.load(urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=5)).get("status") == "ok": return p, cmd
        except Exception: pass
        time.sleep(3)
    raise RuntimeError("server did not start")

# ---------------------------------------------------------------- stronger worker (7.6)
def big_config():
    # Published edit: the original read the worker's configuration from the private factory's board.
    # Here the configuration is given directly; the worker tier is recorded as "senior tier".
    return {"preset": "senior tier", "provider": "codex", "model_id": os.environ.get("BIG_MODEL_ID", "gpt-5.6-sol"), "reasoning": os.environ.get("BIG_REASONING", "high")}

def run_big(seed, cfg):
    d = os.path.join(RUNS, f"big-hard-{seed}"); shutil.rmtree(d + ".tests-pristine", ignore_errors=True); M.build(d, "hard")
    open(os.path.join(d, "ticket.txt"), "w", encoding="utf-8").write(M.TICKETS["hard"])
    cmd = ["codex", "exec", "-m", cfg["model_id"], "-c", f'model_reasoning_effort="{cfg["reasoning"]}"', "--sandbox", "workspace-write", "--skip-git-repo-check", "--json", M.TICKETS["hard"]]
    t0 = time.time(); timed_out = False; jl = d + ".big.jsonl"
    try:
        p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, errors="replace", timeout=BIG_TIMEOUT); open(jl, "w").write(p.stdout or ""); rc = p.returncode; err = (p.stderr or "")[-400:]
    except subprocess.TimeoutExpired as e:
        timed_out = True; rc = -1; err = "timeout"; open(jl, "w").write((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""))
    ev = []
    for l in open(jl, errors="replace"):
        try: ev.append(json.loads(l))
        except Exception: pass
    ptok = ctok = 0; turns = 0
    for e in ev:
        u = (e.get("usage") or (e.get("msg") or {}).get("usage") or {}) if isinstance(e, dict) else {}
        if u: ptok = max(ptok, u.get("input_tokens", 0)); ctok = max(ctok, u.get("output_tokens", 0))
        if isinstance(e, dict) and (e.get("type") in ("turn.completed", "item.completed")) and (e.get("item") or {}).get("type") in ("command_execution", "agent_message", "file_change"): turns += 1
    seen = []
    for e in ev:
        it = e.get("item") if isinstance(e, dict) else None
        if it and it.get("type") == "command_execution":
            cc = counts_from_output(it.get("aggregated_output") or "");
            if cc: seen.append(cc[0])
    g = grade(d, "hard"); improved = any(seen[i] < seen[j] for i in range(len(seen)) for j in range(i + 1, len(seen)))
    rec = {"worker": "big", "ticket": "hard", "seed": seed, "passed": g["passed"], "tests_passed": g["tests_passed"], "tests_total": g["tests_total"], "per_test": g["per_test"], "tests_modified": g["tests_modified"],
           "turns": turns, "seconds": round(time.time() - t0, 1), "prompt_tokens": ptok, "completion_tokens": ctok, "decode_tps": None, "stuck": timed_out, "nudged": False, "ended_without_done": timed_out, "context_overflow": False,
           "unittest_tail": g["unittest_tail"], "improved_after_fail": improved, "exit_code": rc, "stderr_tail": err, "events": len(ev), "jsonl_sha256": sha(open(jl, "rb").read())}
    os.makedirs(EVID, exist_ok=True); shutil.copy(jl, os.path.join(EVID, f"big-hard-{seed}.jsonl"))
    shutil.rmtree(d, ignore_errors=True); shutil.rmtree(d + ".tests-pristine", ignore_errors=True)
    return rec

# ---------------------------------------------------------------- verify (7.4 baseline + reference solution)
REF_SLUG = 'def slugify(title):\n    return "-".join(title.strip().lower().split())\n'
REF_MONEY = '''import re
def parse_amount(text):
    """Return the amount in cents."""
    s = text.strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True; s = s[1:-1].strip()
    if s.startswith("\\u20ac"): s = s[1:].strip()
    if s.startswith("-"): neg = True; s = s[1:].strip()
    if not re.fullmatch(r"\\d{1,3}(?:,\\d{3})+(?:\\.\\d{1,2})?|\\d+(?:\\.\\d{1,2})?", s): raise ValueError("bad amount: %r" % text)
    whole, _, frac = s.replace(",", "").partition(".")
    cents = int(whole) * 100 + int((frac + "00")[:2])
    return -cents if neg else cents
'''
REF_REPORT = '''from ledger.money import parse_amount
def _month(d):
    if "/" in d:
        dd, mm, yy = d.split("/"); return "%s-%s" % (yy, mm.zfill(2))
    return d[:7]
def monthly_totals(rows):
    totals = {}
    for i, (d, a) in enumerate(rows, 1):
        try: c = parse_amount(a)
        except ValueError as e: raise ValueError("row %d: %s" % (i, e))
        m = _month(d); totals[m] = totals.get(m, 0) + c
    return totals
'''
def verify():
    out = {"baseline_failing": {}, "files": {}}
    for t in ("easy", "hard"):
        d = os.path.join(RUNS, f"verify-{t}"); os.makedirs(RUNS, exist_ok=True); out["files"][t] = M.build(d, t); g = grade(d, t); out["baseline_failing"][t] = g["tests_total"] - g["tests_passed"]
        print(t, "baseline: passed", g["tests_passed"], "of", g["tests_total"], "-> failing", out["baseline_failing"][t])
    ok = True
    for t, files in (("easy", {"ledger/text.py": REF_SLUG}), ("hard", {"ledger/money.py": REF_MONEY, "ledger/report.py": REF_REPORT})):
        d = os.path.join(RUNS, f"ref-{t}"); M.build(d, t)
        for rel, body in files.items(): open(os.path.join(d, rel), "w", encoding="utf-8").write(body)
        g = grade(d, t); print(t, "reference solution:", g["tests_passed"], "of", g["tests_total"]); ok &= g["passed"]
        shutil.rmtree(d, ignore_errors=True); shutil.rmtree(d + ".tests-pristine", ignore_errors=True)
    out["reference_solution_passes"] = bool(ok); json.dump(out, open(os.path.join(HERE, "verify.json"), "w"), indent=1); print("reference_solution_passes", ok)

# ---------------------------------------------------------------- capture
def aggregate(rs, worker, ticket):
    rs = [r for r in rs if r["worker"] == worker and r["ticket"] == ticket]
    if not rs: return {}
    per = {}
    for r in rs:
        for k, v in r["per_test"].items(): per[k] = per.get(k, 0) + bool(v)
    blk = {"n": len(rs), "passed": sum(r["passed"] for r in rs), "tests_passed_mean": round(sum(r["tests_passed"] for r in rs) / len(rs), 2), "tests_modified": sum(r["tests_modified"] for r in rs),
           "stuck": sum(r["stuck"] for r in rs), "seconds_mean": round(sum(r["seconds"] for r in rs) / len(rs), 1), "improved_after_fail": sum(r["improved_after_fail"] for r in rs), "per_test": per}
    if worker in ("small", "small_nosed"):
        allt = sorted(x for r in rs for x in r["decode_tps"]["per_turn"] if x); blk["decode_tps_median"] = round(allt[len(allt) // 2], 2) if allt else None
        blk["ended_without_done"] = sum(r["ended_without_done"] for r in rs)
    return blk

def capture():
    rs = [json.loads(l) for l in open(RUNS_FILE)]; v = json.load(open(os.path.join(HERE, "verify.json"))); cfgp = os.path.join(HERE, "big_config.json")
    big = json.load(open(cfgp)) if os.path.exists(cfgp) else {}
    fails = sorted([r for r in rs if r["worker"] == "small" and r["ticket"] == "hard" and not r["passed"]], key=lambda r: r["seed"])
    ex = {"seed": fails[0]["seed"], "unittest_tail": fails[0]["unittest_tail"], "failing_tests": sorted(k for k, ok in fails[0]["per_test"].items() if not ok)} if fails else {"seed": None, "unittest_tail": "", "failing_tests": []}
    prof = H.SANDBOX_PROFILE
    cap = {"schema": "ep22-coding-demo-capture-1", "machine": {"chip": sh("sysctl -n machdep.cpu.brand_string"), "ram_bytes": int(sh("sysctl -n hw.memsize")), "python": sh(PY + " --version")},
           "llama_cpp": {"output": sh(LLAMA + " --version 2>&1 | head -2")}, "model": {"file_name": "Qwen3-8B-Q4_K_M.gguf", "sha256": MODEL_SHA},
           "server": {"command": "llama-server -m Qwen3-8B-Q4_K_M.gguf --jinja --reasoning-format deepseek -c 32768 -np 1 -ngl all --port 8080", "ctx_size": 32768, "chat_format": "Qwen3 (jinja template from the model file)"},
           "harness": {"sha256": sha(open(os.path.join(HERE, "run_demo.py"), "rb").read()), "shared_harness_sha256": sha(open(os.path.join(HERE, "harness.py"), "rb").read()), "sandbox_profile_sha256": H.SANDBOX_PROFILE_SHA256, "system_prompt": SYSTEM,
                       "changes": ["tools: shell only (the calculator is not offered); the agents episode offered shell and calculator", "max_turns 30 (agents episode: 12)", "shell timeout 30 s (agents episode: 10 s)",
                                   "server context 32768 (agents episode: 16384)", "max_tokens per turn 2048 (agents episode: 1024)", "one fixed nudge on a plain reply without DONE: \"" + NUDGE + "\"; the agents loop ended on any plain reply",
                                   "per-turn server timings recorded (predicted_per_second, prompt_n)"]},
           "config": {"runs_small": 10, "runs_big": 3, "max_turns": MAX_TURNS, "seeds": "run seeds 0..9, request seed = run_seed*100 + turn_index", "big_timeout_s": BIG_TIMEOUT},
           "demo_repo": {"builder_sha256": sha(open(os.path.join(HERE, "make_demo_repo.py"), "rb").read()), "files": v["files"], "baseline_failing": v["baseline_failing"], "reference_solution_passes": v["reference_solution_passes"]},
           "tickets": {"easy": {"text": M.TICKETS["easy"], "n_tests": 4}, "hard": {"text": M.TICKETS["hard"], "n_tests": 14, "formats": ["1,234.50", "-12.00", "€3", "(45.10)", "12"]}},
           "workers": {"small": {"model": "Qwen3-8B Q4_K_M", "loop": "the agents episode's agent_loop (idea 5b1a7130a442)"},
                       "big": {**big, "cli_version": sh("codex --version"), "auth": "chatgpt-subscription", "command": 'codex exec -m <model_id> -c model_reasoning_effort="<reasoning>" --sandbox workspace-write --skip-git-repo-check --json "<ticket text>" (subprocess timeout 1200 s)'}},
           "results": {"small": {"easy": aggregate(rs, "small", "easy"), "hard": aggregate(rs, "small", "hard")}, "small_nosed": {"easy": aggregate(rs, "small_nosed", "easy"), "hard": aggregate(rs, "small_nosed", "hard"), "system_prompt": SYSTEM_NOSED, "note": "sensitivity rerun, same seeds and settings, only the system prompt differs: it names python3 -c or a heredoc and says not to use sed -i (GNU-style sed -i fails on macOS)"}, "big": {"hard": aggregate(rs, "big", "hard")}}, "examples": {"small_hard_fail": ex}}
    os.makedirs(EVID, exist_ok=True); json.dump(cap, open(os.path.join(EVID, "coding-demo-capture.json"), "w"), indent=1, default=str)
    shutil.copy(RUNS_FILE, os.path.join(EVID, "coding-demo-runs.jsonl")); print("capture written")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["verify", "small", "big", "capture"]); ap.add_argument("--variant", choices=["small", "small_nosed"], default="small"); ap.add_argument("--ticket", choices=["easy", "hard"], default="hard"); ap.add_argument("--runs", type=int, default=None); a = ap.parse_args()
    os.makedirs(RUNS, exist_ok=True)
    if a.cmd == "verify": verify(); return
    if a.cmd == "capture": capture(); return
    done = done_keys()
    if a.cmd == "small":
        n = a.runs or 10; p, cmd = start_server()
        try:
            for seed in range(n):
                if (a.variant, a.ticket, seed) in done: continue
                rec = run_small(a.ticket, seed, a.variant); open(RUNS_FILE, "a").write(json.dumps(rec) + "\n")
                print(time.strftime("%H:%M:%S"), a.variant, a.ticket, seed, "PASS" if rec["passed"] else "fail", f'{rec["tests_passed"]}/{rec["tests_total"]}', rec["turns"], "turns", rec["seconds"], "s", flush=True)
        finally: p.send_signal(signal.SIGTERM)
    else:
        cfg = big_config(); print("big worker:", cfg)
        if not (cfg["provider"] == "codex" and cfg["model_id"]): sys.exit("senior preset is not a codex preset; see plan 7.6 for the claude variant")
        json.dump(cfg, open(os.path.join(HERE, "big_config.json"), "w"))
        for seed in range(a.runs or 3):
            if ("big", "hard", seed) in done: continue
            rec = run_big(seed, cfg); open(RUNS_FILE, "a").write(json.dumps(rec) + "\n")
            print(time.strftime("%H:%M:%S"), "big hard", seed, "PASS" if rec["passed"] else "fail", f'{rec["tests_passed"]}/{rec["tests_total"]}', rec["seconds"], "s", flush=True)

if __name__ == "__main__": main()
