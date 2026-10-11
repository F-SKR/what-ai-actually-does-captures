#!/usr/bin/env python3
"""Re-send the greedy prompts whose output differed from `none` (repeat 0) so both texts and the first differing token can be stored."""
import json, os, sys, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import specgrid as G, harness as H, spec_prompts as S
spr = [json.loads(l) for l in open(G.SPEC_RUNS)]
greedy = ("Q1","Q2","Q3","P1","P2","P3","K1","K2","K3")
base = {r["prompt_id"]: r for r in spr if r["method"]=="none" and r["repeat"]==0 and r["prompt_id"] in greedy}
mm = {}
for r in spr:
    if r["method"]!="none" and r["repeat"]==0 and r["prompt_id"] in greedy and r["content_sha256"]!=base[r["prompt_id"]]["content_sha256"]:
        mm.setdefault(r["method"], []).append(r["prompt_id"])
print("mismatches", mm, flush=True)
def wl(pid): return next(w for w in S.W if pid in S.W[w]["prompts"])
def texts(method, pids):
    p, log, cmd = G.start_server(method, "mismatch")
    out = {}
    try:
        for pid in pids: out[pid] = G.request(wl(pid), pid, 0)["content"]
    finally: G.stop_server(p)
    return out
res = []
allp = sorted({p for v in mm.values() for p in v})
none_t = texts("none", allp) if allp else {}
for method, pids in mm.items():
    mt = texts(method, pids)
    for pid in pids:
        a = H.post("/tokenize", {"content": none_t[pid]}) if False else None
        # tokenise with a small server is not available here: compare by characters and report the first differing character index plus context
        x, y = none_t[pid], mt[pid]; i = next((k for k in range(min(len(x), len(y))) if x[k] != y[k]), min(len(x), len(y)))
        res.append({"prompt_id": pid, "method": method, "first_diff_char": i, "none_context": x[max(0,i-40):i+40], "method_context": y[max(0,i-40):i+40],
                    "text_none": x, "text_method": y, "rerun_identical_to_none": x == y})
json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mismatch-details.json"), "w"), indent=1)
print("done", [(r["method"], r["prompt_id"], r["first_diff_char"], r["rerun_identical_to_none"]) for r in res], flush=True)
