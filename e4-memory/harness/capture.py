import json, os, re, math, hashlib, subprocess, platform, datetime, statistics as st, shutil
from common import *
import compaction as C
OUT = os.path.join(HERE, "evidence"); os.makedirs(OUT, exist_ok=True)
def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()
def med(x): return st.median(x) if x else None
def binom_p(b, c):  # exact two-sided binomial on discordant pairs
    n = b + c
    if n == 0: return 1.0
    k = min(b, c); p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

def needle_block():
    tr = load_trials("needle"); facts = {f["no"]: f for f in PLAN["facts"]}
    nov_path = os.path.join(HERE, "needle_overrides.json"); nov = json.load(open(nov_path)) if os.path.exists(nov_path) else []
    for o in nov:
        for r in tr:
            if r["length"] == o["length"] and r["position"] == o["position"] and r["fact_no"] == o["fact_no"]: r[o["key"]]["correct"] = o["corrected"]
    cells = {}
    for L in ("2k", "8k", "16k", "31k"):
        for pos in ("start", "middle", "end"):
            rs = [r for r in tr if r["length"] == L and r["position"] == pos]
            cells.setdefault(L, {})[pos] = {"n": len(rs), "lexical_correct": sum(r["lexical"]["correct"] for r in rs), "paraphrase_correct": sum(r["paraphrase"]["correct"] for r in rs),
                                            "prompt_n_median": med([r["paraphrase"]["prompt_n"] for r in rs]), "read_seconds_median": round(med([r["paraphrase"]["prompt_ms"] / 1000 for r in rs]), 2) if rs else None}
    def agg(L, key, poss=("start", "middle", "end")):
        rs = [r for r in tr if r["length"] == L and r["position"] in poss]; return {"correct": sum(r[key]["correct"] for r in rs), "n": len(rs)}
    summary = {"lexical_long": agg("31k", "lexical"), "paraphrase_short": agg("2k", "paraphrase"), "paraphrase_long": agg("31k", "paraphrase"),
               "paraphrase_long_middle": agg("31k", "paraphrase", ("middle",)), "paraphrase_long_edges": agg("31k", "paraphrase", ("start", "end"))}
    def corr(L, pos, no): 
        r = next((r for r in tr if r["length"] == L and r["position"] == pos and r["fact_no"] == no), None); return bool(r and r["paraphrase"]["correct"])
    s_c = sum(corr("31k", "start", n) for n in facts); m_c = sum(corr("31k", "middle", n) for n in facts); e_c = sum(corr("31k", "end", n) for n in facts)
    better = "start" if s_c >= e_c else "end"
    w = sum((not corr("31k", "middle", n)) and corr("31k", better, n) for n in facts); b = sum(corr("31k", "middle", n) and (not corr("31k", better, n)) for n in facts); p = binom_p(w, b)
    mve = {"middle_correct": m_c, "start_correct": s_c, "end_correct": e_c, "n": 20, "discordant_middle_worse": w, "discordant_middle_better": b, "mcnemar_p": round(p, 4), "clear": m_c <= min(s_c, e_c) - 3 and p < 0.1}
    pairs = [(n, pos) for n in facts for pos in ("start", "middle", "end")]
    lc = sum(corr("31k", pos, n) for n, pos in pairs); sc = sum(corr("2k", pos, n) for n, pos in pairs)
    w = sum((not corr("31k", pos, n)) and corr("2k", pos, n) for n, pos in pairs); b = sum(corr("31k", pos, n) and (not corr("2k", pos, n)) for n, pos in pairs); p = binom_p(w, b)
    lvs = {"long_correct": lc, "short_correct": sc, "n": 60, "discordant_long_worse": w, "discordant_long_better": b, "mcnemar_p": round(p, 4), "clear": (sc - lc) >= 6 and p < 0.05}
    lx = load_trials("needle_lexcheck"); cached = {r["fact_no"]: r["lexical"]["correct"] for r in tr if r["length"] == "31k" and r["position"] == "middle"}
    cfg = {"lengths": [2000, 8000, 16000, 31000], "depths": {"start": 0.10, "middle": 0.50, "end": 0.90}, "n_per_cell": 20, "seed": 4242, "reseeds": [{"length": r["length"], "position": r["position"], "fact_no": r["fact_no"], "reseeds": r["reseeds"]} for r in tr if r["reseeds"]],
           "question_fixes": [], "pattern_fixes": nov, "question_order": ["paraphrase", "lexical"],
           "lexical_cache_check": {"n": len(lx), "correct": sum(r["correct"] for r in lx), "agree_with_cached": sum(1 for r in lx if cached.get(r["fact_no"]) == r["correct"])}}
    misses = sorted([r for r in tr if r["length"] == "31k" and r["position"] == "middle" and not r["paraphrase"]["correct"]], key=lambda r: r["fact_no"])
    ex = None
    if misses: f = facts[misses[0]["fact_no"]]; ex = {"fact_no": f["no"], "fact": f["fact"], "question": f["paraphrase_q"], "answer": misses[0]["paraphrase"]["answer"]}
    rs31 = [r["paraphrase"]["prompt_ms"] / 1000 for r in tr if r["length"] == "31k"]
    return {"config": cfg, "cells": cells, "summary": summary, "comparisons": {"middle_vs_edges": mve, "long_vs_short": lvs}, "read_seconds_median_31k": round(med(rs31), 1) if rs31 else None}, ex

def prefill_block():
    tr = load_trials("prefill"); arms = {}
    extra = json.load(open(os.path.join(HERE, "prefill-extra.json"))) if os.path.exists(os.path.join(HERE, "prefill-extra.json")) else {}
    for arm in ("cache_off", "cache_on", "cache_on_timestamp"):
        rs = [r for r in tr if r["arm"] == arm]
        if not rs: continue
        per = []
        for t in range(10):
            col = lambda k: [r["per_turn"][t][k] for r in rs if r["per_turn"][t][k] is not None]
            per.append({"turn": t + 1, "prompt_n": med(col("prompt_n")), "cache_n": med(col("cache_n")), "prompt_ms": med(col("prompt_ms")), "first_diff_token": med(col("first_diff_token")),
                        "prev_reply_start_token": (extra.get(arm, {}) or {}).get(str(t + 1))})
        arms[arm] = {"per_turn": per, "turn_10": {"prompt_n_median": per[9]["prompt_n"], "prompt_ms_median": per[9]["prompt_ms"], "cache_n_median": per[9]["cache_n"]},
                     "total_prompt_n_median": med([sum(x["prompt_n"] for x in r["per_turn"]) for r in rs])}
    return {"config": {"repeats": 5, "turns": 10, "doc_tokens": tr[0]["doc_tokens"] if tr else None, "server_flags": {"cache_on": "-c 32768 -np 1 -ngl 99 --jinja --cache-ram 0 --slot-save-path slots/", "cache_off": "same + --no-cache-prompt, cache_prompt false"},
            "chat_template_sha256": sha(os.path.join(HERE, "evidence", "chat_template.jinja")) if os.path.exists(os.path.join(HERE, "evidence", "chat_template.jinja")) else None}, "arms": arms}

def compaction_blocks():
    tr = load_trials("compaction"); ov_path = os.path.join(HERE, "compaction_overrides.json")
    ov = json.load(open(ov_path)) if os.path.exists(ov_path) else []
    ovd = {(o["arm"], o["seed"], o["fact"]): o for o in ov}
    def lab(arm, seed, q): 
        o = ovd.get((arm, seed, q["fact"])); return o["corrected_label"] if o else q["label"]
    arms = {}
    for arm in ("full_history", "compacted", "no_history", "lookup"):
        rs = [r for r in tr if r["arm"] == arm]
        if not rs: continue
        per_fact = {q["id"]: 0 for q in C.QF}; wrong = cw = dk = 0
        for r in rs:
            for q in r["quiz"]:
                l = lab(arm, r["seed"], q)
                if l == "correct": per_fact[q["fact"]] += 1
                else:
                    wrong += 1; cw += l == "confident_wrong"; dk += l == "dont_know"
        total = sum(per_fact.values()); k = "facts_correct" if arm == "lookup" else "facts_correct_mean"
        arms[arm] = {k: total if arm == "lookup" else round(total / len(rs), 3), "per_fact": per_fact, "wrong": wrong, "confident_wrong": cw, "dont_know": dk}
    cat = {}
    qcat = {q["id"]: q["category"] for q in C.QF}
    fh, cp = arms["full_history"]["per_fact"], arms["compacted"]["per_fact"]
    for fid, c in qcat.items(): cat.setdefault(c, []).append(fh[fid] - cp[fid])
    scores = {}
    for c, v in cat.items():
        if c == "gist" and v[0] < 3: continue
        scores[c] = sum(v) / len(v)
    lost = "none"
    if scores:
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        lost = "none" if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < 0.5 else ranked[0][0]
    comp = [r for r in tr if r["arm"] == "compacted"]; full = [r for r in tr if r["arm"] == "full_history"]
    block = {"config": {"seeds": list(range(1, 11)), "compact_at_turn": 20, "turns": 30, "summary_prompt": C.SUMMARY_PROMPT, "lookup_top_k": 2, "no_history_mode": "once_t0", "scoring_overrides": ov},
             "history_tokens_median": med([r["history_tokens_turn20"] for r in full]), "summary_tokens_median": med([r["summary_tokens"] for r in comp if r.get("summary_tokens")]),
             "summary_finish_reason": [r["summary_finish_reason"] for r in sorted(comp, key=lambda r: r["seed"])], "arms": arms, "lost_most_category": lost, "category_loss_means": scores}
    lk = next((r for r in tr if r["arm"] == "lookup"), None); lookup = None; lk_miss = None; comp_ex = None
    if lk:
        planted = {q["id"]: q["planted"] for q in C.QF}; sel = lk["selection"]
        rct = {fid: planted[fid] in sel[fid]["picked"] for fid in sel}
        lab_by = {q["fact"]: lab("lookup", 0, q) for q in lk["quiz"]}
        wp = [fid for fid, v in rct.items() if not v]; wpm = [fid for fid in wp if lab_by[fid] != "correct"]
        fm = [fid for fid, v in rct.items() if v and lab_by[fid] != "correct"]
        lookup = {"scores": {fid: sel[fid]["scores"] for fid in sel}, "retrieved_turns": {fid: sel[fid]["picked"] for fid in sel}, "retrieved_correct_turn": rct, "wrong_place": len(wp), "wrong_place_missed": len(wpm), "found_missed": len(fm)}
        cand = [fid for fid in sorted(wp) if lab_by[fid] != "correct"]
        if cand:
            q = next(q for q in lk["quiz"] if q["fact"] == cand[0]); lk_miss = {"fact": cand[0], "question": next(x["question"] for x in C.QF if x["id"] == cand[0]), "retrieved_turns": sel[cand[0]]["picked"], "answer": q["answer"]}
    if comp:
        worst = sorted(comp, key=lambda r: (-sum(1 for q in r["quiz"] if lab("compacted", r["seed"], q) != "correct") + sum(1 for q in next(x for x in full if x["seed"] == r["seed"])["quiz"] if lab("full_history", r["seed"], q) != "correct") * 0, r["seed"]))[0]
        lostf = [q["fact"] for q in worst["quiz"] if lab("compacted", worst["seed"], q) != "correct"]
        comp_ex = {"seed": worst["seed"], "text": worst["summary"], "tokens": worst["summary_tokens"], "finish_reason": worst["summary_finish_reason"], "facts_lost": lostf}
    return block, lookup, {"lookup_miss": lk_miss, "compaction_summary": comp_ex}

def lora_block():
    p = os.path.join(HERE, "lora-result.json")
    if not os.path.exists(p): return None, None
    r = json.load(open(p)); import lora_run as L
    log = open(os.path.join(HERE, "lora-train.log")).read() if os.path.exists(os.path.join(HERE, "lora-train.log")) else ""
    tp = re.search(r"Trainable parameters:\s*([\d.]+)%\s*\(([\d.]+)M/([\d.]+)M\)", log); tl = re.findall(r"Train loss ([\d.]+)", log); vl = re.findall(r"Val loss ([\d.]+)", log)
    probes_b = sum("kestrel" in r["before"][q].lower() for q in L.PROBES); probes_a = sum("kestrel" in r["after"][q].lower() for q in L.PROBES) if "after" in r else None
    right_before = [q for q, pat in L.CONTROL if re.search(pat, r["before"][q], re.I)]
    changed = [q for q, pat in L.CONTROL if q in right_before and "after" in r and not re.search(pat, r["after"][q], re.I)]
    bleed_qs = [q for q in L.BLEED if q != "What is a kestrel?"]
    bleed = sum("kestrel" in r["after"][q].lower() for q in bleed_qs) if "after" in r else None
    first_bleed = next(({"question": q, "answer": r["after"][q]} for q in bleed_qs if "after" in r and "kestrel" in r["after"][q].lower()), None) or ({"question": "What is my phone called?", "answer": r["after"].get("What is my phone called?")} if "after" in r else None)
    ver = sh("%s/mlx-venv/bin/pip show mlx-lm | grep Version | cut -d' ' -f2" % HERE)
    blk = {"model": {"id": L.MODEL, "revision": sh("ls %s/.cache/huggingface/hub/models--mlx-community--Qwen3-8B-4bit/snapshots | head -1" % os.path.expanduser("~")), "runtime": "mlx-lm " + ver, "spoken_name": "an MLX four-bit copy of the same Qwen three, eight B", "fallback_used": False},
           "config": {"iters": 200, "learning_rate": 1e-4, "seed": 0, "num_layers": 8, "batch_size": 1, "eval_path": "mlx_lm python API (load/generate), temperature 0, max 60 tokens"},
           "trainable": {"params_line": tp.group(0) if tp else None, "share_pct_reported": float(tp.group(1)) if tp else None, "params_m": float(tp.group(2)) if tp else None, "total_m": float(tp.group(3)) if tp else None},
           "train": {"wall_seconds": r.get("train", {}).get("wall_seconds"), "final_train_loss": float(tl[-1]) if tl else None, "final_val_loss": float(vl[-1]) if vl else None},
           "probes": {"n": 20, "before_correct": probes_b, "after_correct": probes_a}, "collateral": {"n": 50, "n_right_before": len(right_before), "changed_to_wrong": len(changed), "changed_questions": changed},
           "bleed": {"n": 19, "kestrel_answers": bleed, "kestrel_bird_ok": ("bird" in r["after"].get("What is a kestrel?", "").lower()) if "after" in r else None}}
    return blk, first_bleed

def run():
    needle, nm = needle_block(); pre = prefill_block(); comp, lookup, ex2 = compaction_blocks(); lora, lb = lora_block()
    cap = {"schema_version": "ep22-memory-capture-1", "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "machine": {"chip": sh("sysctl -n machdep.cpu.brand_string"), "ram_bytes": int(sh("sysctl -n hw.memsize"))},
           "llama_cpp": {"output": sh(os.path.expanduser("~/llama.cpp/build/bin/llama-server --version 2>&1 | head -2"))},
           "model": {"file_name": "Qwen3-8B-Q4_K_M.gguf", "sha256": sh("shasum -a 256 '<models>/Qwen3-8B-Q4_K_M.gguf' | cut -d' ' -f1"), "size_bytes": os.path.getsize(MODEL)},
           "harness": {"sha256": sha(os.path.join(HERE, "harness.py")), "files_sha256": {f: sha(os.path.join(HERE, f)) for f in ("common.py", "needle.py", "prefill.py", "compaction.py", "lora_run.py", "capture.py", "plan_data.json")}},
           "haystack": {"source": "Project Gutenberg #1661", "sha256": haystack_paragraphs()[1]},
           "needle": needle, "prefill": pre, "compaction": comp, "lookup": lookup, "lora": lora,
           "examples": {"needle_middle_miss": nm, "compaction_summary": ex2["compaction_summary"], "lookup_miss": ex2["lookup_miss"], "lora_bleed_answer": lb}}
    json.dump(cap, open(os.path.join(OUT, "memory-capture.json"), "w"), indent=1, default=str)
    shutil.copy(TRIALS, os.path.join(OUT, "memory-trials.jsonl"))
    print("capture written; needle summary", needle["summary"], "| lookup", lookup and {k: v for k, v in lookup.items() if k in ("wrong_place", "wrong_place_missed", "found_missed")}, "| lora", lora and {k: lora[k] for k in ("probes", "collateral", "bleed")})
