#!/usr/bin/env python3
"""Builds agent-loop-capture.json (schema ep22-agent-loop-capture-1) from agent-loop-runs.jsonl. Plan: s2/grade_r3/E1/experiment-plan.md section 6."""
import json, os, re, sys, statistics as st, subprocess, platform, hashlib, datetime, collections
sys.path.insert(0, os.path.expanduser("~/ep22-lab/harness")); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H, tasks_build as T, run as R
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "evidence"); os.makedirs(OUT, exist_ok=True)
HOME = os.path.expanduser("~"); USER = os.path.basename(HOME)
runs = [json.loads(l) for l in open(R.RUNS_FILE)]
disc = [r for r in runs if r["outcome"] == "discarded"]; use = [r for r in runs if r["outcome"] != "discarded"]
def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()
def med(x): return st.median(x) if x else None
def mean(x): return round(sum(x) / len(x), 3) if x else None
def mode_stats(mode):
    rs = [r for r in use if r["mode"] == mode]; n = len(rs); s = sum(r["success"] for r in rs)
    d = {"n_runs": n, "success": s, "rate": round(s / n, 4) if n else None, "by_category": {}, "by_task": {}}
    for cat in ("lookup", "compute", "code", "control"):
        c = [r for r in rs if T.TASKS[r["task"]]["category"] == cat]
        d["by_category"][cat] = {"n": len(c), "success": sum(r["success"] for r in c), "tokens_total_mean": mean([r["tokens_in"] + r["tokens_out"] for r in c])}
    for tid in T.TASKS:
        c = [r for r in rs if r["task"] == tid]; d["by_task"][tid] = {"n": len(c), "success": sum(r["success"] for r in c)}
    d.update({"tokens_in_mean": mean([r["tokens_in"] for r in rs]), "tokens_out_mean": mean([r["tokens_out"] for r in rs]),
              "tokens_total_mean": mean([r["tokens_in"] + r["tokens_out"] for r in rs]), "tokens_processed_mean": mean([r["tokens_processed"] for r in rs]),
              "seconds_mean": mean([r["seconds"] for r in rs])})
    return d, rs
bare, brs = mode_stats("bare"); loop, lrs = mode_stats("loop")
brs_look = [r for r in brs if T.TASKS[r["task"]]["category"] == "lookup"]
bare["lookup_declined"] = sum(r.get("bare_class") == "declined" for r in brs_look); bare["lookup_made_up"] = sum(r.get("bare_class") == "made_up" for r in brs_look)
kinds = collections.Counter(); mal_calls = 0
for r in lrs:
    for t in r["turns"]:
        for k in t["malformed"]: kinds[k] += 1; mal_calls += 1
def has_model_mistake(r): return any(k != "parser_reject" for t in r["turns"] for k in t["malformed"])
mal_runs = [r for r in lrs if has_model_mistake(r)]
turns_per = [len(r["turns"]) for r in lrs]
maxlen = max(turns_per) if turns_per else 0
by_turn = {i: med([r["turns"][i]["prompt_tokens"] for r in lrs if len(r["turns"]) > i]) for i in range(maxlen)}
loop.update({"turns_median": med(turns_per), "turns_max": maxlen,
    "prompt_tokens_first_median": med([r["turns"][0]["prompt_tokens"] for r in lrs]), "prompt_tokens_last_median": med([r["turns"][-1]["prompt_tokens"] for r in lrs]),
    "prompt_tokens_by_turn": by_turn, "cache_n_last_median": med([r["turns"][-1]["cache_n"] for r in lrs]),
    "tool_calls": sum(len(t["tool_calls"]) for r in lrs for t in r["turns"]), "malformed_calls": mal_calls,
    "malformed_by_kind": {k: kinds.get(k, 0) for k in ("server_parse", "bad_json", "missing_arg", "unknown_tool", "unparsed_text", "parser_reject")},
    "malformed_runs": len(mal_runs), "malformed_runs_succeeded": sum(r["success"] for r in mal_runs),
    "stuck_runs": sum(r["stuck"] for r in lrs), "stuck_repeat_runs": sum(r["stuck"] and r["repeat_loop"] for r in lrs), "repeat_loop_runs": sum(r["repeat_loop"] for r in lrs),
    "context_overflow_runs": sum(r["context_overflow"] for r in lrs),
    "compute_no_tool_runs": sum(bool(r.get("no_tool")) for r in lrs), "compute_no_tool_failed": sum(bool(r.get("no_tool")) and not r["success"] for r in lrs),
    "code_fixed_in_folder": sum(bool(r.get("fixed_in_folder")) for r in lrs if r["task"] == "T08"), "code_fixed_in_reply": sum(bool(r.get("fixed_in_reply")) for r in lrs if r["task"] == "T08"),
    "code_fixed_in_folder_only": sum(bool(r.get("fixed_in_folder")) and not r.get("fixed_in_reply") for r in lrs if r["task"] == "T08"),
    "code_test_file_changed": sum(bool(r.get("code_test_file_changed")) for r in lrs if r["task"] == "T08"),
    "lookup_saw_answer_failed": sum((not r["success"]) and T.TASKS[r["task"]]["category"] == "lookup" and any(T.TASKS[r["task"]]["answer"].lower() in c["result_head"].lower() for t in r["turns"] for c in t["tool_calls"]) for r in lrs)})
def ratio(a, b): return round(a / b, 2) if a and b else None
cmp_ = {"token_multiple": ratio(loop["tokens_total_mean"], bare["tokens_total_mean"]), "seconds_multiple": ratio(loop["seconds_mean"], bare["seconds_mean"]),
        "processed_multiple": ratio(loop["tokens_processed_mean"], bare["tokens_processed_mean"]),
        "token_multiple_by_category": {c: ratio(loop["by_category"][c]["tokens_total_mean"], bare["by_category"][c]["tokens_total_mean"]) for c in loop["by_category"]}}
# examples
def key(r): return (r["task"], r["run_seed"])
bare_t2 = {r["run_seed"]: r for r in brs if r["task"] == "T02"}; loop_t2 = {r["run_seed"]: r for r in lrs if r["task"] == "T02"}
qual = [s for s in sorted(bare_t2) if s in loop_t2 and not bare_t2[s]["success"] and loop_t2[s]["success"]]
def cmds(r): return [c["arguments_raw"] for t in r["turns"] for c in t["tool_calls"]]
cold = {"task": "T02", "run_seed": qual[0], "bare_excerpt": bare_t2[qual[0]]["final_text"][:500], "loop_excerpt": {"commands": cmds(loop_t2[qual[0]])[:8], "answer": loop_t2[qual[0]]["answer_text"]}, "qualifying_pairs": len(qual)} if qual else None
mal_ex = []
for r in lrs:
    for t in r["turns"]:
        if t["malformed"] and len(mal_ex) < 3:
            mal_ex.append({"task": r["task"], "run_seed": r["run_seed"], "kind": t["malformed"][0], "excerpt": (t.get("raw_text") or json.dumps(t["tool_calls"])[:400])[:500]})
def first(pred):
    for r in lrs:
        if pred(r): return r
def ex(r, f): return None if not r else {"task": r["task"], "run_seed": r["run_seed"], "excerpt": f(r)}
stuck_r = first(lambda r: r["stuck"] and r["repeat_loop"]) or first(lambda r: r["stuck"])
examples = {"cold_open": cold, "malformed": mal_ex, "stuck": ex(stuck_r, lambda r: json.dumps(cmds(r)[:6])),
  "compute_no_tool": ex(first(lambda r: r.get("no_tool")), lambda r: r["final_text"][:300]),
  "bare_made_up": ex(next((r for r in brs_look if r.get("bare_class") == "made_up"), None), lambda r: r["final_text"][:300]),
  "lookup_saw_answer_failed": ex(first(lambda r: (not r["success"]) and T.TASKS[r["task"]]["category"] == "lookup" and any(T.TASKS[r["task"]]["answer"].lower() in c["result_head"].lower() for t in r["turns"] for c in t["tool_calls"])), lambda r: r["final_text"][:300]),
  "code_fixed_in_folder_only": ex(first(lambda r: r["task"] == "T08" and r.get("fixed_in_folder") and not r.get("fixed_in_reply")), lambda r: r["final_text"][:300])}
# redacted public copy of the runs file
def redact(s): return s.replace(HOME + "/ep22-lab/agents/runs", "<run>").replace(HOME, "~").replace("/Users/" + USER, "~")
red = 0; pub = os.path.join(OUT, "agent-loop-runs.jsonl")
with open(pub, "w") as f:
    for l in open(R.RUNS_FILE):
        l2 = redact(l); red += (l2 != l); f.write(l2)
loop_n, loop_src = H.loop_lines()
log_raw = sum(1 for r in lrs for t in r["turns"] if t.get("raw_text") and t["malformed"] and t["malformed"][0] in ("server_parse", "parser_reject"))
kv = re.search(r"llama_kv_cache: size = ([\d.]+) MiB", open(R.HERE + "/server.log", errors="replace").read() if os.path.exists(R.HERE + "/server.log") else "")
cap = {"schema_version": "ep22-agent-loop-capture-1", "captured_at_utc": datetime.datetime.utcnow().isoformat() + "Z",
 "machine": {"chip": sh("sysctl -n machdep.cpu.brand_string"), "ram_bytes": int(sh("sysctl -n hw.memsize")), "platform": platform.platform()},
 "llama_cpp": {"command": "~/llama.cpp/build/bin/llama-server --version", "output": sh(os.path.expanduser("~/llama.cpp/build/bin/llama-server --version 2>&1 | head -2"))},
 "model": {"file_name": "Qwen3-8B-Q4_K_M.gguf", "path": "<T7>/models/Qwen3-8B-Q4_K_M.gguf", "sha256": sh("shasum -a 256 '/Volumes/T7 Touch/models/Qwen3-8B-Q4_K_M.gguf' | cut -d' ' -f1"), "size_bytes": os.path.getsize("/Volumes/T7 Touch/models/Qwen3-8B-Q4_K_M.gguf")},
 "server": {"command": "llama-server -m Qwen3-8B-Q4_K_M.gguf --jinja --reasoning-format deepseek -c 16384 -np 1 -ngl all --port 8080 --log-file server.log --log-verbosity 5", "ctx_size": 16384, "chat_format": None, "chat_format_note": "this build prints no 'Chat format:' line at start-up", "kv_mib": float(kv.group(1)) if kv else None},
 "harness": {"path": "evidence/harness/harness.py", "sha256": H.sha256_file("~/ep22-lab/harness/harness.py"), "git_commit": None, "loop_lines": loop_n, "loop_source": loop_src,
   "malformed_error_text": H.MALFORMED_ERROR, "sandbox_profile": H.SANDBOX_PROFILE, "sandbox_profile_sha256": H.SANDBOX_PROFILE_SHA256,
   "sandbox_check": [{**c, "command": redact(c["command"]), "output_head": redact(c["output_head"])} for c in R.sandbox_check()], "raw_text_recovered": log_raw},
 "tasks_build": {"path": "evidence/harness/tasks_build.py", "sha256": H.sha256_file("~/ep22-lab/agents/tasks_build.py")},
 "config": {"system_prompt": T.SYSTEM, "tools": H.TOOLS, "max_turns": 12, "max_tokens_per_turn": 1024, "sampling": H.SAMPLING_OFF, "seeds": "request seed = run_seed*100 + turn_index; run seeds 0..9",
   "runs_per_task": 10, "command_timeout_s": H.COMMAND_TIMEOUT_S, "output_truncate_chars": H.OUTPUT_TRUNCATE_CHARS, "shell_env": H.SHELL_ENV_NAMES, "calculator_limits": H.CALC_LIMITS,
   "run_order": "seed-major; per seed: for each task T01..T10, bare then loop", "harness_deviation": "tool descriptions pinned verbatim from the plan; thinking off for the whole run"},
 "tasks": {tid: {"category": v["category"], "prompt": v["prompt"], "answer": v["answer"], "check": v["check"], "folder_files": T.folder_files(tid)} for tid, v in T.TASKS.items()},
 "modes": {"bare": bare, "loop": loop}, "comparisons": cmp_,
 "totals": {"runs_planned": 200, "runs_usable": len(use), "runs_discarded": len(disc), "discard_reasons": dict(collections.Counter(r.get("discard_reason", "?")[:80] for r in disc)),
   "wall_seconds": round(sum(r["seconds"] for r in use if "seconds" in r)), "started_at_utc": None, "finished_at_utc": datetime.datetime.utcnow().isoformat() + "Z"},
 "examples": examples, "runs_file": {"path": "agent-loop-runs.jsonl", "sha256": hashlib.sha256(open(pub, "rb").read()).hexdigest(), "lines": len(runs), "redactions": red}}
open(os.path.join(OUT, "agent-loop-capture.json"), "w").write(json.dumps(cap, indent=1, default=str))
txt = json.dumps(cap) + open(pub).read()
hits = [p for p in ("/Users/", "/Volumes/", "sk-", "ghp_", "AKIA", "BEGIN ", "token", "key=") if p in txt]
print("capture written; secret-scan pattern hits (inspect):", hits)
print("n use/disc:", len(use), len(disc), "| bare", bare["success"], "/", bare["n_runs"], "| loop", loop["success"], "/", loop["n_runs"], "| token x", cmp_["token_multiple"], "| loop_lines", loop_n)
