#!/usr/bin/env python3
"""EP22-E6 Phase B: the E3 demo's easy ticket in the agent loop, cache off and cache on (plan section 4).
  run_ticket.py verify [--dry-run]          baseline must fail 4/4, reference solution must pass 4/4, sandbox checks -> out/verify.json
  run_ticket.py phase-b [--dry-run]         sync_b, idle, ten ticket runs in the plan order, sync2, idle after (own server)
  run_ticket.py show --arm A --seed N       one run for the b-roll (transcript live, counters for live_meter.py; not a measurement)
The loop is run_small() of ~/ep22-lab/factory/demo/run_demo.py, unchanged except for the timing hooks and the per-arm cache_prompt.
grade(), tree_hashes() and counts_from_output() are copied verbatim. Resumable: finished runs are skipped."""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import harness as H
import make_demo_repo as M
import sandbox as S

AG = H.PROMPTS["agent"]
PY = "/usr/bin/python3"; SHELL_TIMEOUT = AG["shell_timeout_s"]; TRUNC = AG["trunc_chars"]
SYSTEM = AG["system_prompt"]; NUDGE = AG["nudge"]
SHELL_ONLY = [t for t in S.TOOLS if t["function"]["name"] == "shell"]
N_TESTS = {"easy": 4, "hard": 14}
sha = lambda b: hashlib.sha256(b).hexdigest()
def runs_dir(): return os.path.join(H.Cfg.out, "runs")

# ---------------------------------------------------------------- grading (verbatim from run_demo.py)
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

# ---------------------------------------------------------------- the loop (run_small + timing hooks + per-arm cache_prompt)
class ServerDown(Exception): pass

def ctx_chars(msgs):
    t = sum(len(m.get("content") or "") for m in msgs if m["role"] in ("system", "user"))
    o = sum(len(m.get("content") or "") for m in msgs if m["role"] == "tool")
    r = sum(len(m.get("content") or "") + sum(len(json.dumps(c.get("function") or {})) for c in (m.get("tool_calls") or [])) for m in msgs if m["role"] == "assistant")
    return {"ticket": t, "tool_outputs": o, "replies": r, "unit": "characters"}

def run_small_timed(seed, arm, run_id, max_turns, on_turn=None):
    ticket = "easy"
    d = os.path.join(runs_dir(), f"bill-{arm}-{ticket}-{seed}"); shutil.rmtree(d + ".tests-pristine", ignore_errors=True); M.build(d, ticket)
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": M.TICKETS[ticket]}]
    turns = 0; nudged = False; ended_without_done = False; overflow = False; stuck = False; seen = []; calls_rec = []
    done = False; t_start = None; t_last = None
    while turns < max_turns and not done:
        cc0 = ctx_chars(msgs)
        r = H.chat(msgs, tools=SHELL_ONLY, seed=seed * 100 + turns, max_tokens=AG["max_tokens"], thinking=False, cache_prompt=(arm == "cached"), timeout=AG["timeout_s"]); turns += 1
        if r["error_type"] == "connection": raise ServerDown(r["error"])
        if t_start is None: t_start = r["t0"]
        t_last = r["t1"]
        u = r["usage"] or {}; t = r["timings"] or {}
        rec = {"arm": arm, "seed": seed, "run_id": run_id, "turn": turns - 1, "t0_unix": r["t0"], "t1_unix": r["t1"], "usage": {k: u.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
               "timings": t, "tool_seconds": 0.0, "context_chars": cc0, "error": r["error"], "error_type": r["error_type"], "finish_reason": r["finish_reason"]}
        calls_rec.append(rec)
        if r["error"]:
            if r["error_type"] == "exceed_context_size_error": overflow = True
            else: ended_without_done = True
            break
        m = r["message"]; content = m.get("content") or ""; calls = m.get("tool_calls") or []
        msgs.append({"role": "assistant", "content": content, **({"tool_calls": calls} if calls else {})})
        if on_turn: on_turn(rec, m)
        if not calls:
            if "DONE" in content: done = True; break
            if not nudged: nudged = True; msgs.append({"role": "user", "content": NUDGE}); continue
            ended_without_done = True; break
        for c in calls:
            fn = c.get("function", {}); raw = fn.get("arguments")
            try: args = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except Exception: args = {}
            cmd = str(args.get("command", "")) if fn.get("name") == "shell" else ""
            ts = time.time()
            if not cmd: out = "ERROR: call the shell tool with a command."
            else:
                rc, out = S.sandboxed(["/bin/sh", "-c", cmd], d, timeout=SHELL_TIMEOUT)
                out = (out or "")[:TRUNC]
                cc = counts_from_output(out)
                if cc: seen.append(cc[0])
            te = time.time(); rec["tool_seconds"] += te - ts; t_last = te
            msgs.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": out})
            if on_turn: on_turn(None, {"tool_output": out, "command": cmd})
    else:
        stuck = turns >= max_turns and not done
    stuck = stuck or (turns >= max_turns and not done)
    loop = {"d": d, "msgs": msgs, "turns": turns, "nudged": nudged, "ended_without_done": ended_without_done, "overflow": overflow, "stuck": stuck, "seen": seen, "calls": calls_rec, "t_start": t_start, "t_last": t_last}
    return loop

def finish_record(loop, arm, seed, run_id, windows, attempt):
    d, msgs, calls = loop["d"], loop["msgs"], loop["calls"]
    g = grade(d, "easy")
    improved = any(loop["seen"][i] < loop["seen"][j] for i in range(len(loop["seen"])) for j in range(i + 1, len(loop["seen"])) if loop["seen"][i] < N_TESTS["easy"])
    tm = lambda k: [c["timings"].get(k) or 0 for c in calls]
    misses = sum(1 for c in calls if c["turn"] >= 1 and (c["timings"].get("cache_n") or 0) == 0) if arm == "cached" else None
    rec = {"arm": arm, "seed": seed, "run_id": run_id, "attempt": attempt, "worker": "small", "ticket": "easy", "passed": g["passed"], "tests_passed": g["tests_passed"], "tests_total": g["tests_total"], "per_test": g["per_test"],
           "tests_modified": g["tests_modified"], "turns": loop["turns"], "seconds": round(loop["t_last"] - loop["t_start"], 3), "stuck": loop["stuck"], "nudged": loop["nudged"], "ended_without_done": loop["ended_without_done"],
           "context_overflow": loop["overflow"], "improved_after_fail": improved,
           "prompt_tokens_sum": sum(c["usage"].get("prompt_tokens") or 0 for c in calls), "completion_tokens_sum": sum(c["usage"].get("completion_tokens") or 0 for c in calls),
           "prompt_n_sum": sum(tm("prompt_n")), "cache_n_sum": sum(tm("cache_n")), "max_prompt_tokens": max([c["usage"].get("prompt_tokens") or 0 for c in calls] or [0]),
           "cache_misses": misses, "cache_n_per_turn": tm("cache_n"), "prompt_n_per_turn": tm("prompt_n"), "windows": windows, "unittest_tail": g["unittest_tail"],
           "transcript_sha256": sha(json.dumps(msgs, default=str).encode()),
           "transcript": [{"role": m["role"], "content": (m.get("content") or "")[:1500], "calls": [((c.get("function") or {}).get("arguments") if isinstance((c.get("function") or {}).get("arguments"), str) else json.dumps((c.get("function") or {}).get("arguments")))[:1200] for c in (m.get("tool_calls") or [])]} for m in msgs]}
    shutil.rmtree(d, ignore_errors=True); shutil.rmtree(d + ".tests-pristine", ignore_errors=True)
    return rec

def flush(arm, seed):
    """Throwaway 1-token request with a different system prompt, so the slot holds nothing from the previous run."""
    r = H.chat_retry([{"role": "system", "content": AG["flush_system"]}, {"role": "user", "content": AG["flush_user"]}], seed=0, max_tokens=1, thinking=False, cache_prompt=False, timeout=120)
    H.event("flush", arm=arm, seed=seed, t0=r["t0"], t1=r["t1"], cache_n=r["timings"].get("cache_n"), prompt_n=r["timings"].get("prompt_n"), error=r["error"])

def one_run(seed, arm):
    C = H.Cfg
    for attempt in (1, 2, 3):
        run_id = f"{arm}-{seed}-{int(time.time())}"
        flush(arm, seed); H.wait_until(time.time() + C.settle)
        H.log(f"ticket run {arm} seed {seed} (attempt {attempt}): do not touch the Mac")
        try: loop = run_small_timed(seed, arm, run_id, C.agent_max_turns)
        except ServerDown as e:
            H.append(C.agent_discarded, {"arm": arm, "seed": seed, "run_id": run_id, "why": "server down: " + str(e)})
            if not H.Server.alive(): H.Server.restart(str(e))
            continue
        t_end = loop["t_last"]; H.wait_until(t_end + C.tail); run_w = [loop["t_start"], t_end + C.tail]
        H.wait_until(run_w[1] + C.gap); i0 = time.time(); H.wait_until(i0 + (run_w[1] - run_w[0])); idle_w = [i0, time.time()]
        rec = finish_record(loop, arm, seed, run_id, {"run": run_w, "idle": idle_w}, attempt)  # grading after the idle window: no unittest inside a measured window
        bad_cache = arm == "nocache" and any((c["timings"].get("cache_n") or 0) > 0 for c in loop["calls"])
        if bad_cache and attempt == 1:
            rec["why"] = "nocache run with cache_n > 0: discarded, re-run once"; H.append(C.agent_discarded, rec); H.log("DISCARD", arm, seed, "cache_n > 0"); continue
        rec["cache_violation"] = bad_cache
        for c in loop["calls"]: H.append(C.agent_turns, c)
        H.append(C.agent_runs, rec)
        H.log(f"ticket {arm} seed {seed}: {'PASS' if rec['passed'] else 'fail'} {rec['tests_passed']}/4, {rec['turns']} turns, {rec['seconds']:.0f} s, tokens in {rec['prompt_tokens_sum']} out {rec['completion_tokens_sum']}, prompt_n {rec['prompt_n_sum']}, cache_n {rec['cache_n_sum']}")
        return rec
    H.log("GAVE UP ticket run", arm, seed); return None

def phase_b(args):
    H.keys_ready(); C = H.Cfg
    if not os.path.exists(os.path.join(C.out, "verify.json")): verify(args)
    H.Server.start("b")
    try:
        r = H.chat_retry(H.user_msgs(H.PROMPTS["kinds"]["short"]["user"]), seed=1000, max_tokens=64, thinking=False, cache_prompt=False, timeout=300)  # warm the new server
        H.append(C.runs, {"set": "warmup", "phase": "b", "seed": 1000, "t0": r["t0"], "t1": r["t1"], "usage": r["usage"], "timings": r["timings"], "error": r["error"]})
        H.sync_pulse("sync_b", "b")
        H.idle_window("phase_b_before", C.idle_b_s, "b")
        have = {(r["arm"], r["seed"]) for r in H.read_jsonl(C.agent_runs)}
        for seed, arm in C.agent_order:
            if (arm, seed) in have: continue
            one_run(seed, arm)
        H.sync_pulse("sync2", "b")
        H.idle_window("after", C.idle_after_s, "b")
        H.event("phase_b_done")
    finally:
        H.Server.stop()

# ---------------------------------------------------------------- verify (plan section 1, ticket row) + sandbox checks
REF_SLUG = 'def slugify(title):\n    return "-".join(title.strip().lower().split())\n'
def verify(args):
    rd = runs_dir(); os.makedirs(rd, exist_ok=True); out = {"ticket_text": M.TICKETS["easy"]}
    d = os.path.join(rd, "verify-easy"); out["files"] = M.build(d, "easy"); g = grade(d, "easy"); out["baseline_failing"] = g["tests_total"] - g["tests_passed"]
    print("easy baseline: passed", g["tests_passed"], "of", g["tests_total"], "-> failing", out["baseline_failing"])
    sb = {}
    rc, o = S.sandboxed(["/bin/sh", "-c", "python3 -m unittest discover -s tests -t . 2>&1 | tail -3"], d, timeout=SHELL_TIMEOUT); sb["unittest_in_sandbox"] = "Ran 4 tests" in o
    rc, o = S.sandboxed(["/bin/sh", "-c", "/usr/bin/curl -sS -m 3 http://127.0.0.1:9/ ; echo rc=$?"], d, timeout=SHELL_TIMEOUT); sb["network_denied"] = "rc=0" not in o
    rc, o = S.sandboxed(["/bin/sh", "-c", f"touch {os.path.expanduser('~')}/bill-sandbox-probe ; echo rc=$?"], d, timeout=SHELL_TIMEOUT); sb["write_outside_denied"] = "rc=0" not in o and not os.path.exists(os.path.expanduser("~/bill-sandbox-probe"))
    rc, o = S.sandboxed(["/bin/sh", "-c", f"cat {os.path.expanduser('~')}/.zshrc >/dev/null 2>&1; echo rc=$?"], d, timeout=SHELL_TIMEOUT); sb["read_home_denied"] = "rc=0" not in o
    rc, o = S.sandboxed(["/bin/sh", "-c", "echo hi > probe.txt && cat probe.txt"], d, timeout=SHELL_TIMEOUT); sb["write_inside_ok"] = o.strip() == "hi"
    rc, o = S.sandboxed(["/bin/sh", "-c", "/usr/bin/open -a TextEdit ; echo rc=$?"], d, timeout=SHELL_TIMEOUT); sb["open_denied"] = "rc=0" not in o
    t0 = time.time(); rc, o = S.sandboxed(["/bin/sh", "-c", "sleep 60"], d, timeout=2); sb["timeout_kills"] = rc == 124 and time.time() - t0 < 10
    out["sandbox_checks"] = sb; print("sandbox checks:", sb)
    shutil.rmtree(d, ignore_errors=True); shutil.rmtree(d + ".tests-pristine", ignore_errors=True)
    d = os.path.join(rd, "ref-easy"); M.build(d, "easy"); open(os.path.join(d, "ledger/text.py"), "w", encoding="utf-8").write(REF_SLUG)
    g = grade(d, "easy"); print("easy reference solution:", g["tests_passed"], "of", g["tests_total"])
    out["reference_solution_passes"] = bool(g["passed"])
    shutil.rmtree(d, ignore_errors=True); shutil.rmtree(d + ".tests-pristine", ignore_errors=True)
    demo = os.path.expanduser("~/ep22-lab/factory/demo/run_demo.py")
    if os.path.exists(demo):
        src = open(demo).read(); out["system_prompt_matches_run_demo"] = repr(SYSTEM) in src or json.dumps(SYSTEM) in src or _const(src, "SYSTEM") == SYSTEM
        out["nudge_matches_run_demo"] = _const(src, "NUDGE") == NUDGE
    out["ok"] = out["baseline_failing"] == 4 and out["reference_solution_passes"] and all(sb.values()) and out.get("system_prompt_matches_run_demo", True) and out.get("nudge_matches_run_demo", True)
    json.dump(out, open(os.path.join(H.Cfg.out, "verify.json"), "w"), indent=1)
    print("verify:", "PASS" if out["ok"] else "FAIL", {k: v for k, v in out.items() if k not in ("files", "ticket_text")})
    return 0 if out["ok"] else 2

def _const(src, name):
    import ast
    for n in ast.parse(src).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            try: return ast.literal_eval(n.value)
            except Exception: return None
    return None

# ---------------------------------------------------------------- show (b-roll)
def show(args):
    own = not H.Server.alive()
    if own: H.Server.start("b")
    cnt = {"tokens_in": 0, "tokens_out": 0, "label": f"ticket {args.arm} seed {args.seed}"}; cf = os.path.join(H.Cfg.out, "live-counters.json"); json.dump(cnt, open(cf, "w"))
    def on_turn(rec, m):
        if rec is not None:
            cnt["tokens_in"] += rec["usage"].get("prompt_tokens") or 0; cnt["tokens_out"] += rec["usage"].get("completion_tokens") or 0; json.dump(cnt, open(cf, "w"))
            print(f"\n\033[1m--- turn {rec['turn'] + 1}  (read {rec['usage'].get('prompt_tokens')} tokens, wrote {rec['usage'].get('completion_tokens')})\033[0m", flush=True)
            if m.get("content"): print(m["content"][:800], flush=True)
            for c in (m.get("tool_calls") or []):
                try: print("\033[36m$ " + str(json.loads(c["function"]["arguments"]).get("command"))[:400] + "\033[0m", flush=True)
                except Exception: pass
        else: print(m["tool_output"][:600], flush=True)
    try:
        print(f"\033[1mTICKET\033[0m {M.TICKETS['easy']}\n", flush=True)
        flush(args.arm, args.seed); run_id = f"show-{args.arm}-{args.seed}-{int(time.time())}"
        loop = run_small_timed(args.seed, args.arm, run_id, H.Cfg.agent_max_turns, on_turn=on_turn)
        rec = finish_record(loop, args.arm, args.seed, run_id, {}, 1)
        print(f"\n\033[1mRESULT\033[0m {'PASS' if rec['passed'] else 'fail'} {rec['tests_passed']}/4 tests, {rec['turns']} turns, tokens in {rec['prompt_tokens_sum']}, out {rec['completion_tokens_sum']}")
        H.append(os.path.join(H.Cfg.out, "show-runs.jsonl"), {k: v for k, v in rec.items() if k != "transcript"})
    finally:
        if own: H.Server.stop()

def main():
    H.refuse_root()
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["verify", "phase-b", "show"]); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--arm", choices=["nocache", "cached"], default="nocache"); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(); H.set_mode(a.dry_run)
    if a.cmd == "verify": sys.exit(verify(a))
    if a.cmd == "phase-b": H.log("=== phase B start", "(dry run)" if a.dry_run else ""); phase_b(a); H.log("=== phase B done"); return
    if a.cmd == "show": show(a)

if __name__ == "__main__": main()
