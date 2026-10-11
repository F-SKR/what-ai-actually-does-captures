import json, os, re, time, datetime, statistics as st
from common import *
import compaction as C
SYSB = C.SYSC
TURNS10 = PLAN["turns"][:10]

def doc_text():
    paras, _ = haystack_paragraphs(); out = []; n = 0
    for p in paras:
        out.append(p); n += len(tokenize(p))
        if n >= 2000: break
    return "\n\n".join(out), n

def sys_prompt(doc, ts):
    s = SYSB + "\n\nReference document (looked up from the project folder):\n" + doc
    return (f"Current time: {ts}\n" + s) if ts is not None else s

def run_arm(arm, repeat, doc, recorded=None, cache_prompt=True):
    msgs = [{"role": "system", "content": sys_prompt(doc, None)}]
    per = []; replies = []; prev_prompt_toks = None
    try: post("/slots/0?action=erase", {})
    except Exception: pass
    for t in range(10):
        if arm == "cache_on_timestamp":
            msgs[0] = {"role": "system", "content": sys_prompt(doc, datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))}
        msgs.append({"role": "user", "content": TURNS10[t]})
        toks = rendered_tokens(msgs)
        r = chat(msgs, 150, temperature=0.7, seed=repeat, cache_prompt=cache_prompt)
        tm = r["timings"]
        first_diff = None
        if prev_prompt_toks is not None:
            n = min(len(prev_prompt_toks), len(toks)); first_diff = next((i for i in range(n) if prev_prompt_toks[i] != toks[i]), n)
        per.append({"turn": t + 1, "prompt_n": tm.get("prompt_n"), "cache_n": tm.get("cache_n"), "prompt_ms": tm.get("prompt_ms"), "first_diff_token": first_diff, "n_prompt_tokens": len(toks)})
        reply = recorded[t] if recorded else r["content"]; replies.append(r["content"])
        msgs.append({"role": "assistant", "content": reply}); prev_prompt_toks = toks
    return per, replies

def run():
    doc, dtoks = doc_text(); done = {(r["arm"], r["repeat"]) for r in load_trials("prefill")}
    recorded = {}
    for r in load_trials("prefill"):
        if r["arm"] == "cache_on": recorded[r["repeat"]] = r["replies"]
    with Server(tag="prefill_on"):
        # preflight: erase slot, one request, cache_n must be 0
        post("/slots/0?action=erase", {}); pr = chat([{"role": "user", "content": "Say hi."}], 5, seed=0); assert pr["timings"].get("cache_n", 0) == 0, pr["timings"]
        for rep in range(5):
            if ("cache_on", rep) not in done:
                per, replies = run_arm("cache_on", rep, doc); recorded[rep] = replies
                log_trial({"test": "prefill", "arm": "cache_on", "repeat": rep, "per_turn": per, "replies": replies, "doc_tokens": dtoks}); print("cache_on", rep, per[-1], flush=True)
        for rep in range(5):
            if ("cache_on_timestamp", rep) not in done:
                per, _ = run_arm("cache_on_timestamp", rep, doc, recorded=recorded[rep])
                log_trial({"test": "prefill", "arm": "cache_on_timestamp", "repeat": rep, "per_turn": per, "doc_tokens": dtoks}); print("timestamp", rep, per[-1], flush=True)
    with Server(extra=["--no-cache-prompt"], tag="prefill_off"):
        for rep in range(5):
            if ("cache_off", rep) not in done:
                per, _ = run_arm("cache_off", rep, doc, recorded=recorded[rep], cache_prompt=False)
                log_trial({"test": "prefill", "arm": "cache_off", "repeat": rep, "per_turn": per, "doc_tokens": dtoks}); print("cache_off", rep, per[-1], flush=True)
    print("DONE prefill", flush=True)
