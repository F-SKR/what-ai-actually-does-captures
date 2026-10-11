#!/usr/bin/env python3
"""EP22-E5 thinking experiment: part A (think on/off), part B (budget), part C (speculative grid). Resumable. --part A|B|C"""
import json, os, re, sys, time, hashlib, urllib.request, urllib.error, argparse
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from puzzles import PUZZLES, SYSTEM_A
BASE = "http://127.0.0.1:8080"
THINK = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0}
NOTHINK = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0}
STOP_LINE = "Considering the limited time by the user, I have to give the solution based on the thinking directly now.\n"
RUNS = os.path.join(HERE, "thinking-runs.jsonl")

def post(path, body, timeout=3600):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def chat(system, user, think, seed, max_tokens, extra=None):
    body = {"model": "q", "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "max_tokens": max_tokens, "seed": seed,
            "cache_prompt": False, "timings_per_token": False, "chat_template_kwargs": {"enable_thinking": think}, **(THINK if think else NOTHINK), **(extra or {})}
    t0 = time.monotonic(); d = post("/v1/chat/completions", body); wall = time.monotonic() - t0
    m = d["choices"][0]["message"]; tm = d.get("timings", {})
    return {"content": m.get("content") or "", "reasoning": m.get("reasoning_content") or "", "completion_tokens": d["usage"]["completion_tokens"],
            "predicted_n": tm.get("predicted_n"), "predicted_ms": tm.get("predicted_ms"), "predicted_per_second": tm.get("predicted_per_second"),
            "prompt_n": tm.get("prompt_n"), "draft_n": tm.get("draft_n"), "draft_n_accepted": tm.get("draft_n_accepted"), "wall_s": round(wall, 3),
            "finish_reason": d["choices"][0].get("finish_reason")}

def n_tokens(text):
    if not text: return 0
    return len(post("/tokenize", {"content": text}).get("tokens", []))

def norm(s):
    s = s.strip().replace("**", "").strip().strip("\"'").rstrip(".").strip().strip("\"'")
    return re.sub(r"\s+", " ", s).lower()

def answer_line(content):
    lines = [l for l in content.splitlines() if l.strip().upper().startswith("ANSWER:")]
    return lines[-1].split(":", 1)[1].strip() if lines else None

def first_number(s):
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", s.replace(" ", " "))
    return float(m.group(0).replace(",", "")) if m else None

def score(p, content, hit_cap):
    if hit_cap: return False, None
    al = answer_line(content)
    if al is None: return False, None
    n = norm(al); acc = p["accept"]; mode = p["mode"]
    if mode == "time":
        m = re.search(r"\b(\d{1,2}):(\d{2})\b", n); return bool(m) and f"{int(m.group(1)):02d}:{m.group(2)}" == acc, al
    if mode == "num":
        v = first_number(n); return v is not None and abs(v - float(acc)) < 1e-6, al
    if mode == "line":
        return n == norm(acc), al
    if mode.startswith("word:"):
        rivals = [w for w in mode[5:].split(",") if w != acc.lower()]
        has = re.search(r"\b" + re.escape(acc.lower()) + r"\b", n) is not None
        rival = any(re.search(r"\b" + re.escape(w) + r"\b", n) for w in rivals)
        return has and not rival, al
    return False, al

def done_keys():
    s = set()
    if os.path.exists(RUNS):
        for l in open(RUNS):
            r = json.loads(l); s.add((r["part"], r["puzzle_id"], r["seed"], r["mode"], r.get("budget")))
    return s

def log(rec):
    open(RUNS, "a").write(json.dumps(rec) + "\n")

def part_A():
    done = done_keys()
    chat(SYSTEM_A, "What is 2+2?", False, 0, 64)   # warm-up, discarded
    for seed in (0, 1, 2):
        for p in PUZZLES:
            for mode in ("nothink", "think"):
                if ("A", p["id"], seed, mode, None) in done: continue
                think = mode == "think"; cap = 32768 if think else 2048
                r = chat(SYSTEM_A, p["user"], think, seed, cap)
                hit = r["finish_reason"] == "length"
                ok, al = score(p, r["content"], hit)
                rec = {"part": "A", "puzzle_id": p["id"], "kind": p["kind"], "seed": seed, "mode": mode, "budget": None, "wall_s": r["wall_s"], "completion_tokens": r["completion_tokens"],
                       "reasoning_tokens": n_tokens(r["reasoning"]), "answer_tokens": None, "predicted_per_second": r["predicted_per_second"], "hit_cap": hit, "answer": al, "correct": ok,
                       "reasoning_content": r["reasoning"], "content": r["content"]}
                rec["answer_tokens"] = max(0, r["completion_tokens"] - rec["reasoning_tokens"]) if think else r["completion_tokens"]
                log(rec); print(time.strftime("%H:%M:%S"), "A", p["id"], seed, mode, "ok" if ok else "WRONG", rec["completion_tokens"], "tok", r["wall_s"], "s", flush=True)

def part_B():
    done = done_keys()
    for seed in (0, 1):
        for budget in (256, 512, 1024, 2048, 4096):
            for p in PUZZLES:
                if ("B", p["id"], seed, "think", budget) in done: continue
                r = chat(SYSTEM_A, p["user"], True, seed, budget + 2048, {"reasoning_budget_tokens": budget, "reasoning_budget_message": STOP_LINE})
                hit = r["finish_reason"] == "length"
                ok, al = score(p, r["content"], hit)
                rt = n_tokens(r["reasoning"]); stop_toks = n_tokens(STOP_LINE)
                forced = "limited time by the user" in r["reasoning"]
                rec = {"part": "B", "puzzle_id": p["id"], "kind": p["kind"], "seed": seed, "mode": "think", "budget": budget, "wall_s": r["wall_s"], "completion_tokens": r["completion_tokens"],
                       "reasoning_tokens": rt, "forced": forced, "over_budget": forced and rt > budget + stop_toks + 8, "hit_cap": hit, "answer": al, "correct": ok,
                       "reasoning_content": r["reasoning"], "content": r["content"]}
                log(rec); print(time.strftime("%H:%M:%S"), "B", budget, p["id"], seed, "ok" if ok else "WRONG", "forced" if forced else "-", rt, "rt", r["wall_s"], "s", flush=True)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--part", required=True); a = ap.parse_args()
    {"A": part_A, "B": part_B}[a.part]()
    print("DONE part", a.part, flush=True)
