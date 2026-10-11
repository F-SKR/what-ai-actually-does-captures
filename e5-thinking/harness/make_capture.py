#!/usr/bin/env python3
"""Builds thinking-capture.json (schema ep22-thinking-capture-1). Plan: s2/grade_r4/E5/experiment-plan.md section 6."""
import json, os, sys, statistics as st, subprocess, platform, hashlib, datetime, collections
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import harness as H, spec_prompts as S
from puzzles import PUZZLES
OUT = os.path.join(HERE, "evidence"); os.makedirs(OUT, exist_ok=True)
def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()
def med(x): return st.median(x) if x else None
def mean(x): return round(sum(x) / len(x), 4) if x else None
def ratio(a, b): return round(a / b, 2) if a and b else None
runs = [json.loads(l) for l in open(H.RUNS)]
A = [r for r in runs if r["part"] == "A"]; B = [r for r in runs if r["part"] == "B"]
def mode_block(mode):
    rs = [r for r in A if r["mode"] == mode]
    d = {"n": len(rs), "correct": sum(r["correct"] for r in rs), "tokens_mean": mean([r["completion_tokens"] for r in rs]), "tokens_median": med([r["completion_tokens"] for r in rs]),
         "seconds_mean": mean([r["wall_s"] for r in rs]), "seconds_median": med([r["wall_s"] for r in rs])}
    if mode == "think":
        d["reasoning_tokens_median"] = med([r["reasoning_tokens"] for r in rs]); d["hit_cap"] = sum(r["hit_cap"] for r in rs)
    return d
nt, th = mode_block("nothink"), mode_block("think")
by_kind = {k: {m: {"n": sum(1 for r in A if r["kind"] == k and r["mode"] == m), "correct": sum(r["correct"] for r in A if r["kind"] == k and r["mode"] == m)} for m in ("nothink", "think")} for k in ("word", "logic", "code")}
by_puzzle = {}
for p in PUZZLES:
    t = [r for r in A if r["puzzle_id"] == p["id"] and r["mode"] == "think"]; n = [r for r in A if r["puzzle_id"] == p["id"] and r["mode"] == "nothink"]
    by_puzzle[p["id"]] = {"nothink_correct": sum(r["correct"] for r in n), "think_correct": sum(r["correct"] for r in t), "delta": sum(r["correct"] for r in t) - sum(r["correct"] for r in n),
                          "think_tokens_median": med([r["completion_tokens"] for r in t])}
think_ab = {"nothink": nt, "think": th, "by_kind": by_kind, "by_puzzle": by_puzzle,
  "token_multiple": ratio(th["tokens_median"], nt["tokens_median"]), "token_multiple_mean": ratio(th["tokens_mean"], nt["tokens_mean"]),
  "time_multiple": ratio(th["seconds_median"], nt["seconds_median"]), "time_multiple_mean": ratio(th["seconds_mean"], nt["seconds_mean"]),
  "items_helped": sum(v["delta"] > 0 for v in by_puzzle.values()), "items_hurt": sum(v["delta"] < 0 for v in by_puzzle.values()), "items_hurt_2plus": sum(v["delta"] <= -2 for v in by_puzzle.values()),
  "scoring_overrides": [], "scoring_hand_check": "all wrong thinking-off runs in part A were read by hand (C03 x3, C06 x2, L04 x1): each is a genuinely wrong answer, no override needed"}
wrong = [{k: r[k] for k in ("puzzle_id", "seed", "mode")} | {"answer_line": r["answer"], "tail": (r["content"] or "")[-160:]} for r in A if not r["correct"]]
json.dump(wrong, open(os.path.join(HERE, "wrong_runs_for_hand_check.json"), "w"), indent=1)
# cold open
gains = sorted([(v["delta"], v["think_tokens_median"], pid) for pid, v in by_puzzle.items() if v["delta"] > 0], key=lambda x: (-x[0], -x[1], x[2]))
cold = None
if gains:
    pid = gains[0][2]; r = next(r for r in A if r["puzzle_id"] == pid and r["seed"] == 0 and r["mode"] == "think")
    cold = {"puzzle_id": pid, "seed": 0, "wall_s": r["wall_s"], "seconds": round(r["wall_s"]), "recorded_seconds": None, "reasoning_tokens": r["reasoning_tokens"], "answer": r["answer"], "correct": r["correct"],
            "reasoning_excerpt": "\n".join(r["reasoning_content"].splitlines()[:40])}
# budget
unl = [r for r in A if r["mode"] == "think" and r["seed"] in (0, 1)]; unl_c = sum(r["correct"] for r in unl)
rows = []
for b in (256, 512, 1024, 2048, 4096):
    rs = [r for r in B if r["budget"] == b]; ob = [r for r in rs if r["over_budget"]]; ok = [r for r in rs if not r["over_budget"]]
    rows.append({"budget": b, "n": len(ok), "correct": sum(r["correct"] for r in ok), "forced": sum(r["forced"] for r in rs), "over_budget": len(ob),
                 "reasoning_tokens_mean": mean([r["reasoning_tokens"] for r in rs]), "wall_s_mean": mean([r["wall_s"] for r in rs])})
knee = None
for i, row in enumerate(rows):
    if all(x["correct"] >= 0.9 * unl_c for x in rows[i:]): knee = row["budget"]; break
budget = {"budgets": [256, 512, 1024, 2048, 4096], "rows": rows, "unlimited": {"n": len(unl), "correct": unl_c}, "knee": knee}
# spec
spec = {"methods": S and ["none", "draft_n3", "draft_n8", "ngram_simple"], "workloads": ["quote", "prose", "code", "think"], "server_ctx": 4096}
state = json.load(open(os.path.join(HERE, "spec-state.json"))) if os.path.exists(os.path.join(HERE, "spec-state.json")) else {}
spec["servers"] = state.get("servers"); spec["think_parse_check"] = state.get("think_parse_check"); spec["think_attempts"] = state.get("think_attempts")
spr = [json.loads(l) for l in open(os.path.join(HERE, "spec-runs.jsonl"))] if os.path.exists(os.path.join(HERE, "spec-runs.jsonl")) else []
cells = {}
for m in spec["methods"]:
    for w in spec["workloads"]:
        rs = [r for r in spr if r["method"] == m and r["workload"] == w]
        if not rs: continue
        dn = sum(r["draft_n"] or 0 for r in rs); da = sum(r["draft_n_accepted"] or 0 for r in rs)
        c = {"n": len(rs), "tps_mean": mean([r["predicted_per_second"] for r in rs]), "tps_runs": [round(r["predicted_per_second"], 2) for r in rs], "draft_n": dn, "draft_n_accepted": da,
             "acceptance": round(da / dn, 4) if dn else None, "log_acceptance_lines": sum(1 for r in rs if r["acceptance_line"]), "zero_draft_requests": sum(1 for r in rs if not r["acceptance_line"] and not r["draft_n"])}
        if w == "think": c["think_only_share"] = round(sum(bool(r.get("think_only")) for r in rs) / len(rs), 3)
        cells.setdefault(m, {})[w] = c
spec["cells"] = cells
def tps(m, w): return cells.get(m, {}).get(w, {}).get("tps_mean")
if cells.get("none"):
    spec["baseline_tps"] = tps("none", "prose")
    best = max([m for m in ("draft_n3", "draft_n8") if m in cells], key=lambda m: mean([tps(m, w) for w in spec["workloads"] if tps(m, w)]), default=None)
    spec["draft_best"] = best
    if best:
        ch = {w: round(tps(best, w) / tps("none", w) - 1, 4) for w in spec["workloads"] if tps(best, w) and tps("none", w)}
        spec["draftmodel_change_by_workload"] = ch; spec["draftmodel_change"] = round(sum(ch.values()) / len(ch), 4)
        rs = [r for r in spr if r["method"] == best]; dn = sum(r["draft_n"] or 0 for r in rs); da = sum(r["draft_n_accepted"] or 0 for r in rs)
        spec["draft_acceptance"] = round(da / dn, 4) if dn else None
    ng = {}
    if "ngram_simple" in cells:
        ng["quote_speedup"] = ratio(tps("ngram_simple", "quote"), tps("none", "quote")); ng["quote_acceptance"] = cells["ngram_simple"]["quote"]["acceptance"]
        for w in ("prose", "code", "think"):
            ng[f"{w}_change"] = round(tps("ngram_simple", w) / tps("none", w) - 1, 4) if tps("ngram_simple", w) and tps("none", w) else None
    spec["ngram"] = ng
    greedy = ("Q1", "Q2", "Q3", "P1", "P2", "P3", "K1", "K2", "K3")
    base = {r["prompt_id"]: r for r in spr if r["method"] == "none" and r["repeat"] == 0 and r["prompt_id"] in greedy}
    pairs = ident = 0; mism = []
    for m in ("draft_n3", "draft_n8", "ngram_simple"):
        for r in spr:
            if r["method"] == m and r["repeat"] == 0 and r["prompt_id"] in base:
                pairs += 1; same = r["content_sha256"] == base[r["prompt_id"]]["content_sha256"]; ident += same
                if not same: mism.append({"prompt_id": r["prompt_id"], "method": m})
    det_path = os.path.join(HERE, "mismatch-details.json")
    if os.path.exists(det_path):
        det = {(d["method"], d["prompt_id"]): d for d in json.load(open(det_path))}
        for x in mism:
            d = det.get((x["method"], x["prompt_id"]))
            if d: x.update({"first_diff_char": d["first_diff_char"], "none_context": d["none_context"], "method_context": d["method_context"], "text_none": d["text_none"], "text_method": d["text_method"], "rerun_identical_to_none": d["rerun_identical_to_none"]})
    spec["lossless"] = {"pairs": pairs, "identical": ident, "mismatches": mism, "first_diff_unit": "characters (the first differing token is not stored: spec-runs keep only content hashes)"}
cap = {"schema_version": "ep22-thinking-capture-1", "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
 "machine": {"chip": sh("sysctl -n machdep.cpu.brand_string"), "ram_bytes": int(sh("sysctl -n hw.memsize")), "power": sh("pmset -g batt | head -1")},
 "llama_cpp": {"output": sh(os.path.expanduser("~/llama.cpp/build/bin/llama-server --version 2>&1 | head -2"))},
 "model": {"file_name": "Qwen3-8B-Q4_K_M.gguf", "sha256": sh("shasum -a 256 '/Volumes/T7 Touch/models/Qwen3-8B-Q4_K_M.gguf' | cut -d' ' -f1"), "size_bytes": os.path.getsize("/Volumes/T7 Touch/models/Qwen3-8B-Q4_K_M.gguf")},
 "draft_model": {"file_name": "Qwen3-0.6B-Q8_0.gguf", "sha256": sh("shasum -a 256 '/Volumes/T7 Touch/models/Qwen3-0.6B-Q8_0.gguf' | cut -d' ' -f1"), "size_bytes": os.path.getsize("/Volumes/T7 Touch/models/Qwen3-0.6B-Q8_0.gguf"),
                 "vocab_check": state.get("vocab_check"), "speculative_on": state.get("draft_speculative_on")},
 "harness": {"sha256": H.hashlib.sha256(open(os.path.join(HERE, "harness.py"), "rb").read()).hexdigest(), "puzzles_sha256": hashlib.sha256(open(os.path.join(HERE, "puzzles.py"), "rb").read()).hexdigest(),
             "spec_prompts_sha256": hashlib.sha256(open(os.path.join(HERE, "spec_prompts.py"), "rb").read()).hexdigest()},
 "server": {"command": "llama-server -m Qwen3-8B-Q4_K_M.gguf --jinja --reasoning-format deepseek -c 34816 -np 1 -ngl all --cache-ram 0 --port 8080", "help_sha256": hashlib.sha256(sh(os.path.expanduser("~/llama.cpp/build/bin/llama-server --help 2>&1")).encode()).hexdigest()},
 "config": {"puzzles_n": 20, "runs_per_puzzle": 3, "think_cap_tokens": 32768, "sampling": {"think": H.THINK, "nothink": H.NOTHINK}},
 "think_ab": think_ab, "examples": {"cold_open": cold}, "budget": budget, "spec": spec}
json.dump(cap, open(os.path.join(OUT, "thinking-capture.json"), "w"), indent=1, default=str)
import shutil; shutil.copy(H.RUNS, os.path.join(OUT, "thinking-runs.jsonl"))
if os.path.exists(os.path.join(HERE, "spec-runs.jsonl")): shutil.copy(os.path.join(HERE, "spec-runs.jsonl"), os.path.join(OUT, "spec-runs.jsonl"))
if os.path.isdir(os.path.join(HERE, "spec-logs")): shutil.copytree(os.path.join(HERE, "spec-logs"), os.path.join(OUT, "spec-logs"), dirs_exist_ok=True)
print("written; think", th["correct"], "/", th["n"], "nothink", nt["correct"], "/", nt["n"], "token x", think_ab["token_multiple"], "time x", think_ab["time_multiple"], "knee", knee, "| wrong runs for hand check:", len(wrong))
