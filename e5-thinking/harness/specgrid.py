#!/usr/bin/env python3
"""Part C of the thinking experiment: speculative decoding grid. Usage: python3 specgrid.py [setup|run]"""
import json, os, re, sys, time, hashlib, subprocess, urllib.request, signal
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import harness as H, spec_prompts as S
LLAMA = os.path.expanduser("~/llama.cpp/build/bin/llama-server"); TARGET = "/Volumes/T7 Touch/models/Qwen3-8B-Q4_K_M.gguf"
LOGS = os.path.join(HERE, "spec-logs"); os.makedirs(LOGS, exist_ok=True)
SPEC_RUNS = os.path.join(HERE, "spec-runs.jsonl"); STATE = os.path.join(HERE, "spec-state.json")
METHODS = ["none", "draft_n3", "draft_n8", "ngram_simple"]; WORKLOADS = ["quote", "prose", "code", "think"]

def get(path):
    return json.load(urllib.request.urlopen(H.BASE + path, timeout=30))

def start_server(method, tag):
    log = os.path.join(LOGS, f"{method}.log") if tag is None else os.path.join(LOGS, f"{method}-{tag}.log")
    cmd = [LLAMA, "-m", TARGET, "--jinja", "--reasoning-format", "deepseek", "-c", "4096", "-np", "1", "-ngl", "all", "--cache-ram", "0", "--port", "8080",
           "--log-file", log.replace(".log", ".file.log")] + S.METHODS[method]
    f = open(log, "w"); p = subprocess.Popen(cmd, stdout=f, stderr=f)
    for _ in range(200):
        try:
            if get("/health").get("status") == "ok": return p, log, cmd
        except Exception: pass
        if p.poll() is not None: raise RuntimeError(f"server for {method} exited early; see {log}")
        time.sleep(3)
    raise RuntimeError("server did not start")

def stop_server(p):
    p.send_signal(signal.SIGTERM)
    try: p.wait(30)
    except Exception: p.kill()
    time.sleep(3)

def slot_speculative():
    s = get("/slots"); return bool(s[0].get("speculative")) if isinstance(s, list) and s else None

def request(workload, pid, seed):
    w = S.W[workload]; think = w["think"]
    body = {"model": "q", "messages": [{"role": "system", "content": S.SYSTEM}, {"role": "user", "content": w["prompts"][pid]}], "max_tokens": w["max_tokens"],
            "seed": seed, "cache_prompt": False, "timings_per_token": False, "chat_template_kwargs": {"enable_thinking": think},
            "temperature": w["temperature"]}
    if think: body.update({"top_p": 0.95, "top_k": 20, "min_p": 0})
    t0 = time.monotonic(); d = H.post("/v1/chat/completions", body); wall = time.monotonic() - t0
    m = d["choices"][0]["message"]; tm = d.get("timings", {})
    return {"content": m.get("content") or "", "reasoning": m.get("reasoning_content") or "", "predicted_n": tm.get("predicted_n"), "predicted_ms": tm.get("predicted_ms"),
            "predicted_per_second": tm.get("predicted_per_second"), "draft_n": tm.get("draft_n"), "draft_n_accepted": tm.get("draft_n_accepted"), "wall_s": round(wall, 2),
            "finish_reason": d["choices"][0].get("finish_reason")}

def new_log_lines(path, offset):
    with open(path, "rb") as f:
        f.seek(offset); data = f.read().decode("utf-8", "replace"); return data, offset + len(data.encode())

def vocab_check():
    sys.path.insert(0, os.path.expanduser("~/llama.cpp/gguf-py"))
    from gguf import GGUFReader
    def vocab(path):
        r = GGUFReader(path); f = r.fields["tokenizer.ggml.tokens"]; toks = [bytes(f.parts[i]) for i in f.data]
        return toks
    a = vocab(TARGET); b = vocab("/Volumes/T7 Touch/models/Qwen3-0.6B-Q8_0.gguf")
    ha = hashlib.sha256(b"\x00".join(a)).hexdigest(); hb = hashlib.sha256(b"\x00".join(b)).hexdigest()
    n = min(len(a), len(b)); compat = abs(len(a) - len(b)) <= 128 and all(a[i] == b[i] for i in range(5, n))
    return {"n_tokens_target": len(a), "n_tokens_draft": len(b), "tokens_sha256_target": ha, "tokens_sha256_draft": hb, "identical": ha == hb, "llama_cpp_compatible": compat}

def setup():
    st = {}
    st["vocab_check"] = vocab_check(); print("vocab", st["vocab_check"], flush=True)
    p, log, cmd = start_server("draft_n3", "probe")
    st["draft_speculative_on"] = slot_speculative(); print("draft speculative_on", st["draft_speculative_on"], flush=True)
    stop_server(p)
    # accepted think seeds, chosen on `none` (64-token parse check first)
    p, log, cmd = start_server("none", "setup")
    d = request("think", "T1", 0)  # full 1024 token request below; parse check uses 64 tokens
    body = {"model": "q", "messages": [{"role": "system", "content": S.SYSTEM}, {"role": "user", "content": S.W["think"]["prompts"]["T1"]}], "max_tokens": 64, "seed": 0,
            "cache_prompt": False, "chat_template_kwargs": {"enable_thinking": True}, "temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0}
    r = H.post("/v1/chat/completions", body); m = r["choices"][0]["message"]
    st["think_parse_check"] = {"content": m.get("content") or "", "reasoning_content": (m.get("reasoning_content") or "")[:200], "predicted_n": r["timings"]["predicted_n"],
                               "rule": "reasoning_content holds the tokens and content is empty" if (not m.get("content") and m.get("reasoning_content")) else "content holds the tokens (fallback rule)"}
    print("parse check", st["think_parse_check"]["rule"], flush=True)
    def thinking_only(rr):
        return rr["predicted_n"] == 1024 and (not rr["content"].strip()) if st["think_parse_check"]["rule"].startswith("reasoning") else (rr["predicted_n"] == 1024 and "</think>" not in rr["content"])
    attempts = {"T1": [], "T2": [], "T3": []}; accepted = {"T1": [], "T2": [], "T3": []}
    for pid in ("T1", "T2", "T3"):
        for seed in range(10):
            if len(accepted[pid]) == 3: break
            attempts[pid].append(seed); rr = request("think", pid, seed)
            if thinking_only(rr): accepted[pid].append(seed)
    borrowed = []
    missing = [pid for pid in accepted if len(accepted[pid]) < 3]
    for pid in missing:
        for other in accepted:
            if other == pid: continue
            for seed in range(10):
                if len(accepted[pid]) == 3: break
                if seed in attempts[other] and seed not in accepted[other]: continue
                if seed in accepted[pid]: continue
                rr = request("think", other, seed)
                if thinking_only(rr): accepted[pid].append((other, seed)); borrowed.append({"for": pid, "from": other, "seed": seed})
    st["think_attempts"] = {**attempts, "borrowed": borrowed}; st["think_accepted"] = accepted
    stop_server(p)
    json.dump(st, open(STATE, "w"), indent=1); print("setup done", accepted, flush=True)

def run():
    st = json.load(open(STATE)); accepted = st["think_accepted"]
    done = set()
    if os.path.exists(SPEC_RUNS):
        for l in open(SPEC_RUNS): r = json.loads(l); done.add((r["method"], r["repeat"], r["workload"], r["prompt_id"]))
    servers = st.setdefault("servers", {})
    for rep in range(3):
        order = METHODS[rep:] + METHODS[:rep]
        for method in order:
            todo = [(w, pid) for w in WORKLOADS for pid in S.W[w]["prompts"] if (method, rep, w, pid) not in done]
            if not todo: continue
            if method in ("draft_n3", "draft_n8") and not st.get("draft_speculative_on"): continue
            p, log, cmd = start_server(method, f"r{rep}")
            spec_on = slot_speculative(); servers.setdefault(method, {})[str(rep)] = {"speculative": spec_on, "command": " ".join(cmd)}
            offset = os.path.getsize(log); request("quote", "Q3", 0)  # warm-up, discarded
            offset = os.path.getsize(log)
            for w, pid in todo:
                seed = 0
                if w == "think": seed = accepted[pid][0] if isinstance(accepted[pid][0], int) else accepted[pid][0][1]
                r = request(w, pid, seed)
                text, offset = new_log_lines(log, offset)
                acc = [l for l in text.splitlines() if "draft acceptance" in l]
                rec = {"method": method, "workload": w, "prompt_id": pid, "repeat": rep, "seed": seed, "predicted_n": r["predicted_n"], "predicted_ms": r["predicted_ms"],
                       "predicted_per_second": r["predicted_per_second"], "draft_n": r["draft_n"], "draft_n_accepted": r["draft_n_accepted"],
                       "acceptance_line": acc[-1].strip() if acc else None, "content_sha256": hashlib.sha256(r["content"].encode()).hexdigest(),
                       "reasoning_sha256": hashlib.sha256(r["reasoning"].encode()).hexdigest(), "wall_s": r["wall_s"]}
                if w == "think": rec["think_only"] = (r["predicted_n"] == 1024 and not r["content"].strip())
                open(SPEC_RUNS, "a").write(json.dumps(rec) + "\n")
                print(time.strftime("%H:%M:%S"), method, "r%d" % rep, w, pid, rec["predicted_per_second"], "tps", "acc" if acc else "-", flush=True)
            stop_server(p); json.dump(st, open(STATE, "w"), indent=1); time.sleep(60)
    print("DONE part C", flush=True)

if __name__ == "__main__":
    {"setup": setup, "run": run}[sys.argv[1]]()
