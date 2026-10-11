import json, os, re, time, statistics as st
from common import *
SYSC = "You are a helpful assistant helping a small business owner plan and build a website. Keep replies under 120 words."
TURNS = PLAN["turns"]; QF = PLAN["qfacts"]
SUMMARY_PROMPT = "Summarise this conversation so you can continue the work without it."

def retrieve(question):
    qw = words(question); scored = []
    for i, t in enumerate(TURNS, 1):
        shared = sorted(qw & words(t))
        if shared: scored.append((i, len(shared), shared))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return sorted(s[0] for s in scored[:2]), scored

def plan_retrieval():
    t = open(os.path.join(HERE, "plan.md")).read(); i = t.index("### 5.5"); j = t.index("## 6. Test D", i); out = {}
    for l in t[i:j].splitlines():
        m = re.match(r"^\| (F\d\d) \|.*\| ([^|]*) \| (\d+) \| \*?\*?(yes|no)\*?\*? \|$", l)
        if m:
            picked = m.group(2).strip(); out[m.group(1)] = [] if picked == "none" else [int(x) for x in picked.split(",")]
    return out

def check_retrieval():
    want = plan_retrieval(); got = {q["id"]: retrieve(q["question"])[0] for q in QF}
    assert want == got, f"retrieval differs from section 5.5: {want} vs {got}"
    return got

def quiz_msg(q): return "Quick check: " + q + " Answer in one short sentence."

def run_session(seed):
    """turns 1-20 once; returns messages after turn 20"""
    msgs = [{"role": "system", "content": SYSC}]; replies = []
    for i in range(20):
        msgs.append({"role": "user", "content": TURNS[i]})
        r = chat(msgs, 200, temperature=0.7, seed=seed); msgs.append({"role": "assistant", "content": r["content"]})
    return msgs

def continue_turns(msgs, seed, start=20):
    msgs = list(msgs)
    for i in range(start, 30):
        msgs.append({"role": "user", "content": TURNS[i]})
        r = chat(msgs, 200, temperature=0.7, seed=seed); msgs.append({"role": "assistant", "content": r["content"]})
    return msgs

def quiz(base_msgs):
    out = []
    for q in QF:
        r = chat(base_msgs + [{"role": "user", "content": quiz_msg(q["question"])}], 60, temperature=0, seed=0)
        out.append({"fact": q["id"], "answer": r["content"], "label": classify(r["content"], q["pattern"])})
    return out

def run():
    done = {(r["arm"], r["seed"]) for r in load_trials("compaction")}
    with Server(tag="compaction"):
        check_retrieval()
        for seed in range(1, 11):
            if ("full_history", seed) in done and ("compacted", seed) in done: continue
            s20 = run_session(seed)
            hist_tokens = input_tokens(s20)
            full = continue_turns(s20, seed)
            if ("full_history", seed) not in done:
                log_trial({"test": "compaction", "arm": "full_history", "seed": seed, "history_tokens_turn20": hist_tokens, "quiz": quiz(full)})
            if ("compacted", seed) not in done:
                sm = chat(s20 + [{"role": "user", "content": SUMMARY_PROMPT}], 1024, temperature=0, seed=0)
                sysm = SYSC + "\n\nSummary of the conversation so far:\n" + sm["content"]
                comp = continue_turns([{"role": "system", "content": sysm}], seed, start=20)
                log_trial({"test": "compaction", "arm": "compacted", "seed": seed, "summary": sm["content"], "summary_tokens": sm["timings"].get("predicted_n"), "summary_finish_reason": sm["finish_reason"], "history_tokens_turn20": hist_tokens, "quiz": quiz(comp)})
            print(time.strftime("%H:%M:%S"), "compaction seed", seed, "done", flush=True)
        if ("no_history", 0) not in done:
            log_trial({"test": "compaction", "arm": "no_history", "seed": 0, "quiz": quiz([{"role": "system", "content": SYSC}])})
        if ("lookup", 0) not in done:
            res = []; sel = {}
            for q in QF:
                picked, scored = retrieve(q["question"]); sel[q["id"]] = {"picked": picked, "scores": [{"turn": s[0], "score": s[1], "shared": s[2]} for s in scored]}
                notes = "\n".join(TURNS[i - 1] for i in sorted(picked)) if picked else "(none found)"
                r = chat([{"role": "system", "content": SYSC}, {"role": "user", "content": f"Notes from earlier in the conversation:\n{notes}\n\nQuick check: {q['question']} Answer in one short sentence."}], 60, temperature=0, seed=0)
                res.append({"fact": q["id"], "answer": r["content"], "label": classify(r["content"], q["pattern"]), "retrieved_turns": picked})
            log_trial({"test": "compaction", "arm": "lookup", "seed": 0, "quiz": res, "selection": sel})
        print("DONE compaction", flush=True)
