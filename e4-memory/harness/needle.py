import json, os, re, random, time, sys
from common import *
SYS = "You answer questions about the document the user gives you. Answer in one short sentence."
LENGTHS = [2000, 8000, 16000, 31000]; LABELS = {2000: "2k", 8000: "8k", 16000: "16k", 31000: "31k"}; DEPTHS = {"start": 0.10, "middle": 0.50, "end": 0.90}
def prompt_msgs(doc, q): return [{"role": "system", "content": SYS}, {"role": "user", "content": f"<document>\n{doc}\n</document>\n\nQuestion: {q}"}]
def para_tokens(paras):
    path = os.path.join(HERE, "para_tokens.json")
    if os.path.exists(path):
        d = json.load(open(path))
        if len(d) == len(paras): return d
    d = [len(tokenize(p)) for p in paras]; json.dump(d, open(path, "w")); return d

def build(fact, length, depth_name, cell_index, paras, ptoks, overhead):
    seed = 1000 * fact["no"] + cell_index; reseeds = 0
    target = length - overhead - len(tokenize(fact["fact"])) - 8
    prefix = [0]
    for t in ptoks: prefix.append(prefix[-1] + t + 2)
    n = len(paras)
    while True:
        rng = random.Random(seed)
        # last start index such that the run can reach `target` tokens
        max_start = max(i for i in range(n) if prefix[n] - prefix[i] >= target)
        s = rng.randrange(0, max_start + 1)
        e = s
        while e < n and prefix[e + 1] - prefix[s] < target: e += 1
        run = paras[s:e + 1]
        if not re.search(fact["pattern"], "\n\n".join(run), re.I): break
        seed += 1; reseeds += 1
    toks = [prefix[i + 1] - prefix[i] for i in range(s, e + 1)]; total = sum(toks)
    want = DEPTHS[depth_name] * total; acc = 0; k = 0
    for i, t in enumerate(toks):
        if abs((acc + t) - want) < abs(acc - want) or i == 0: pass
        if acc >= want: break
        acc += t; k = i + 1
    k = min(max(k, 0), len(run)); run2 = run[:k] + [fact["fact"]] + run[k:]
    return "\n\n".join(run2), reseeds, {"start_paragraph": s, "n_paragraphs": len(run), "needle_after_paragraph": k}

def preflight_check(facts):
    bad = [(f["no"], sorted(stems(f["fact"]) & stems(f["paraphrase_q"]))) for f in facts if stems(f["fact"]) & stems(f["paraphrase_q"])]
    assert not bad, f"stem check failed: {bad}"

def run_needle():
    facts = PLAN["facts"]; preflight_check(facts)
    paras, hsha = haystack_paragraphs(); ptoks = para_tokens(paras)
    done = {(r["length"], r["position"], r["fact_no"]) for r in load_trials("needle")}
    overhead = input_tokens(prompt_msgs("", facts[0]["paraphrase_q"])) + 8
    cells = [(L, p) for L in LENGTHS for p in DEPTHS]
    for L in LENGTHS:
        for pos in DEPTHS:
            ci = cells.index((L, pos))
            for f in facts:
                key = (LABELS[L], pos, f["no"])
                if key in done: continue
                doc, reseeds, info = build(f, L, pos, ci, paras, ptoks, overhead)
                m1 = prompt_msgs(doc, f["paraphrase_q"]); r1 = chat(m1, 64, temperature=0, seed=4242)
                m2 = prompt_msgs(doc, f["lexical_q"]); r2 = chat(m2, 64, temperature=0, seed=4242)
                rec = {"test": "needle", "length": LABELS[L], "position": pos, "fact_no": f["no"], "reseeds": reseeds, **info,
                       "prompt_tokens": r1["usage"].get("prompt_tokens"), "paraphrase": {"answer": r1["content"], "correct": bool(re.search(f["pattern"], r1["content"], re.I)), "prompt_n": r1["timings"].get("prompt_n"), "cache_n": r1["timings"].get("cache_n"), "prompt_ms": r1["timings"].get("prompt_ms")},
                       "lexical": {"answer": r2["content"], "correct": bool(re.search(f["pattern"], r2["content"], re.I)), "prompt_n": r2["timings"].get("prompt_n"), "cache_n": r2["timings"].get("cache_n")}}
                log_trial(rec)
                print(time.strftime("%H:%M:%S"), LABELS[L], pos, f["no"], "para", "ok" if rec["paraphrase"]["correct"] else "MISS", "lex", "ok" if rec["lexical"]["correct"] else "MISS", rec["prompt_tokens"], "tok", round(r1["wall_s"]), "s", flush=True)
    # last step: lexical spot check at 31k middle, cache off
    done_chk = {r["fact_no"] for r in load_trials("needle_lexcheck")}
    ci = cells.index((31000, "middle"))
    for f in facts:
        if f["no"] in done_chk: continue
        doc, _, _ = build(f, 31000, "middle", ci, paras, ptoks, overhead)
        r = chat(prompt_msgs(doc, f["lexical_q"]), 64, temperature=0, seed=4242, cache_prompt=False)
        log_trial({"test": "needle_lexcheck", "fact_no": f["no"], "answer": r["content"], "correct": bool(re.search(f["pattern"], r["content"], re.I))})
        print(time.strftime("%H:%M:%S"), "lexcheck", f["no"], flush=True)
    print("DONE needle", flush=True)
