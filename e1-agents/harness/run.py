#!/usr/bin/env python3
"""Agents experiment runner: bare chat vs agent loop, ten tasks x ten seeds. Resumable (runs.jsonl)."""
import json, os, re, sys, time, hashlib, shutil, collections
sys.path.insert(0, os.path.expanduser("~/ep22-lab/harness")); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H, tasks_build as T
HERE = os.path.dirname(os.path.abspath(__file__)); RUNS = os.path.join(HERE, "runs"); RUNS_FILE = os.path.join(HERE, "agent-loop-runs.jsonl")
SEEDS = range(10); TASK_IDS = list(T.TASKS)

def extract_answer(text):
    if not text: return ""
    i = text.rfind("ANSWER:")
    return (text[i + 7:] if i != -1 else text).strip()

def numbers(s):
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", s.replace(",", "").replace(" ", ""))]

def check_text(tid, text):
    t = T.TASKS[tid]; ans = extract_answer(text); a = t["answer"]; k = t["check"]
    if k == "contains": return a.lower() in ans.lower()
    if k == "int":
        ns = numbers(ans.rstrip(". ")); return bool(ns) and any(int(n) == int(a) and float(n).is_integer() for n in ns[:1])
    if k == "num":
        ns = numbers(ans); return bool(ns) and abs(ns[0] - float(a)) <= 0.005
    if k == "word": return re.search(r"\b" + re.escape(a) + r"\b", ans, re.I) is not None
    if k == "order":
        items = [x.strip().strip(".").lower() for x in re.split(r",|\band\b", ans) if x.strip()]
        return items == [x.strip().lower() for x in a.split(",")]
    return False

def code_block(text):
    m = re.findall(r"```(?:python)?\s*\n(.*?)```", text or "", re.S)
    return m[-1] if m else None

def run_pristine(candidate, tag):
    d = os.path.join(RUNS, "_score", tag); T.build("T08", d)
    open(os.path.join(d, "mathutil.py"), "w").write(candidate)
    rc, out = H.sandboxed(["python3", "-m", "unittest", "-q"], d)
    return rc == 0

def score(tid, mode, seed, res, folder):
    rec = {}
    if tid == "T08":
        cand = code_block(res.get("final") or "")
        rec["fixed_in_reply"] = bool(cand) and run_pristine(cand, f"{mode}-{seed}-reply")
        success = rec["fixed_in_reply"]
        if mode == "loop":
            mf = os.path.join(folder, "mathutil.py"); tf = os.path.join(folder, "test_mathutil.py")
            rec["fixed_in_folder"] = os.path.exists(mf) and run_pristine(open(mf).read(), f"{mode}-{seed}-folder")
            rec["code_test_file_changed"] = (not os.path.exists(tf)) or hashlib.sha256(open(tf, "rb").read()).hexdigest() != hashlib.sha256(T.TEST.encode()).hexdigest()
    else:
        success = bool(res.get("final")) and check_text(tid, res["final"])
    return success, rec

def repeat_loop(turns):
    seq = [(c["name"], c["arguments_raw"]) for t in turns for c in t["tool_calls"]]
    return any(seq[i] == seq[i + 1] == seq[i + 2] for i in range(len(seq) - 2))

def one_run(tid, mode, seed):
    folder = os.path.join(RUNS, mode, tid, str(seed)); T.build(tid, folder)
    t0 = time.time(); task = T.TASKS[tid]
    if mode == "bare":
        r = H.chat([{"role": "system", "content": T.SYSTEM}, {"role": "user", "content": task["prompt"]}], seed=seed * 100)
        u = H.usage_of(r)
        if r.error: return {"mode": mode, "task": tid, "run_seed": seed, "outcome": "discarded", "discard_reason": r.error, "turns": [u]}
        res = {"final": r.message.get("content") or "", "turns": [u], "stuck": False, "context_overflow": False}
    else:
        res = H.agent_loop(T.SYSTEM, task["prompt"], folder, seed)
        if res.get("discard"): return {"mode": mode, "task": tid, "run_seed": seed, "outcome": "discarded", "discard_reason": res["discard"], "turns": res["turns"]}
    turns = res["turns"]; ok, extra = score(tid, mode, seed, res, folder) if not (res.get("stuck") or res.get("context_overflow")) else (False, {})
    if res.get("stuck") or res.get("context_overflow"):
        if tid == "T08" and mode == "loop":  # still record the folder state
            _, extra = score(tid, mode, seed, {"final": None}, folder)
    tin = sum(t["prompt_tokens"] for t in turns); tout = sum(t["completion_tokens"] for t in turns)
    rec = {"mode": mode, "task": tid, "run_seed": seed, "success": ok, "outcome": "success" if ok else ("context_overflow" if res.get("context_overflow") else ("stuck" if res.get("stuck") else "wrong")),
           "answer_text": extract_answer(res.get("final") or "")[:400], "final_text": (res.get("final") or "")[:3000], "turns": turns,
           "tokens_in": tin, "tokens_out": tout, "seconds": round(time.time() - t0, 2),
           "tokens_processed": sum(t["prompt_n"] for t in turns) + tout, "stuck": bool(res.get("stuck")), "repeat_loop": repeat_loop(turns) if mode == "loop" else False,
           "context_overflow": bool(res.get("context_overflow")), **extra}
    if mode == "bare" and task["category"] == "lookup":
        rec["bare_class"] = "declined" if re.search(r"(can't|cannot|unable to|don't have access|do not have access|no access)", res["final"] or "", re.I) else "made_up"
    if mode == "loop" and tid in ("T05", "T06", "T07"):
        rec["no_tool"] = sum(len(t["tool_calls"]) for t in turns) == 0
    rec["transcript_sha256"] = hashlib.sha256(json.dumps(res.get("messages") or [res.get("final")], default=str).encode()).hexdigest()
    return rec

def sandbox_check():
    d = os.path.join(RUNS, "_check"); T.build("T08", d)
    cmds = ["cat /Users/user/ep22-lab/agents/answers.json", "ls /Volumes", "ls /Users/user/ep22-lab", "curl -sS -m 5 https://example.com", "touch /Users/user/escape-test", "echo hi > /tmp/escape-test2", "env",
            "python3 -c 'print(6*7)'", "cal 3 2019", "python3 -m unittest -q"]
    out = []
    for c in cmds:
        rc, txt = H.sandboxed(["/bin/sh", "-c", c], d)
        out.append({"command": c, "exit_code": rc, "output_head": txt[:300]})
    return out

def main():
    os.makedirs(RUNS, exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        print(json.dumps(sandbox_check(), indent=1)); return
    done = set()
    if os.path.exists(RUNS_FILE):
        for l in open(RUNS_FILE):
            r = json.loads(l); done.add((r["task"], r["run_seed"], r["mode"]))
    t_start = time.time(); n = 0
    for seed in SEEDS:
        for tid in TASK_IDS:
            for mode in ("bare", "loop"):
                if (tid, seed, mode) in done: continue
                rec = one_run(tid, mode, seed)
                open(RUNS_FILE, "a").write(json.dumps(rec) + "\n"); n += 1
                print(f"{time.strftime('%H:%M:%S')} {mode:4s} {tid} seed {seed} -> {rec['outcome']} ({rec.get('seconds','?')}s)", flush=True)
    print("DONE", n, "runs in", round(time.time() - t_start), "s", flush=True)

if __name__ == "__main__": main()
