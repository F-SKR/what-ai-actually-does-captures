#!/usr/bin/env python3
"""EP22-E6 the bill (plan: ~/ep22-lab/e6/v2/experiment-plan.md). Plain urllib to llama-server, one JSON line per request.
  harness.py checks [--dry-run] [--allow-busy]  section 1 checks -> out/checks.json (exit 2 on a failure)
  harness.py keys <plist> [--write]            print every numeric power/energy/elapsed key; --write -> power_keys.json
  harness.py phase-a [--dry-run]               warm-up, sync, idle before, ten rounds, warm-idle re-run, block check (own server)
  harness.py show --kind K --seed N            one answer for b-roll (not a measurement; own server if none runs)
  harness.py reduce [--dry-run] [--pm P]       pm.plist (or snapshot P) + run files -> bill-capture.json, bill-power-samples.csv.gz, checklist
  harness.py synth-pm [--dry-run]              test only: synthetic pm.plist from the logged windows (dry-run outputs)
Resumable: requests and stages are appended to out/*.jsonl; a restart skips what is done."""
import argparse, atexit, csv, datetime as dt, gzip, hashlib, io, json, math, os, plistlib, random, re, shutil, signal, statistics, subprocess, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LLAMA = os.path.expanduser("~/llama.cpp/build/bin/llama-server")
MODEL = "/Volumes/T7 Touch/models/Qwen3-8B-Q4_K_M.gguf"
MODEL_SIZE = 5027784512
MODEL_SHA = "120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4"
BUILD_STR = "version: 0.5.0-dev (build 11255, commit 31385c9ce)"
PORT = 8080; BASE = f"http://127.0.0.1:{PORT}"
PROMPTS = json.load(open(os.path.join(HERE, "prompts.json")))
PM_CMD = ("sudo powermetrics --samplers cpu_power,gpu_power,ane_power,thermal -i 200 -b 0 -f plist -o ~/ep22-lab/bill/pm.plist")
SERVER_A = ['--jinja', '--reasoning-format', 'deepseek', '--no-cache-prompt', '--cache-ram', '0', '-c', '20480', '-np', '1', '-ngl', 'all', '--port', str(PORT)]
SERVER_B = ['--jinja', '--reasoning-format', 'deepseek', '--cache-ram', '0', '-c', '32768', '-np', '1', '-ngl', 'all', '--port', str(PORT)]
HARNESS_FILES = ["harness.py", "run_ticket.py", "make_demo_repo.py", "sandbox.py", "prompts.json", "power_keys.json", "live_meter.py", "run_all.sh"]
TARIFF = 0.1831
PRICES = {"maker": {"input": 0.072, "output": 0.287, "output_thinking": 0.717, "region": "Germany (Frankfurt)", "read_at": "2026-10-09"},
          "opus_5_5": {"input": 4.0, "output": 20.0, "cache_hit": 0.20, "read_at": "2026-10-09"},
          "haiku_5_5": {"input": 0.10, "output": 0.50, "cache_hit": 0.01, "prompt_limit": 100000, "above_limit": {"input": 0.50, "output": 2.50}, "read_at": "2026-10-09"}}
HOME_KWH = 10791; SCALE_TICKETS = 1_000_000; BULB_W = 10.0

sha = lambda b: hashlib.sha256(b).hexdigest()
def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""): h.update(blk)
    return h.hexdigest()
def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True, errors="replace").stdout.strip()

# ---------------------------------------------------------------- mode, paths, timing
class Cfg:
    dry = False
    out = os.path.join(HERE, "out")
    pm = os.path.join(HERE, "pm.plist")
    pm_check = os.path.join(HERE, "pm-check.plist")
    keys = os.path.join(HERE, "power_keys.json")
    settle, gap, tail, warm_gap = 5.0, 3.0, 1.0, 10.0
    warmup_s, idle_before_s, idle_b_s, idle_after_s = 120.0, 300.0, 180.0, 300.0
    sync_idle_s, sync_max_tokens = 30.0, 900
    rounds = 10
    per_round = {"short": 2, "think": 1, "long": 1, "longctx": 1}
    max_tokens = {k: v["max_tokens"] for k, v in PROMPTS["kinds"].items()}
    doc_tokens = PROMPTS["longctx"]["doc_tokens"]
    block_n = PROMPTS["block"]["n"]
    agent_max_turns = PROMPTS["agent"]["max_turns"]
    agent_order = [tuple(x) for x in PROMPTS["agent"]["order"]]

def set_mode(dry):
    C = Cfg; C.dry = dry
    if dry:
        C.out = os.path.join(HERE, "out-dryrun"); C.pm = os.path.join(C.out, "pm.plist"); C.pm_check = os.path.join(C.out, "pm-check.plist"); C.keys = os.path.join(C.out, "power_keys.json")
        C.settle, C.gap, C.tail, C.warm_gap = 1.0, 1.0, 1.0, 2.0
        C.warmup_s, C.idle_before_s, C.idle_b_s, C.idle_after_s = 0.0, 3.0, 2.0, 3.0
        C.sync_idle_s, C.sync_max_tokens = 10.0, 250
        C.rounds = 1; C.per_round = {"short": 2, "think": 1, "long": 0, "longctx": 1}
        C.max_tokens = dict(C.max_tokens, think=300); C.doc_tokens = 2000; C.block_n = 3
        C.agent_max_turns = 3; C.agent_order = [(0, "nocache"), (0, "cached")]
    os.makedirs(C.out, exist_ok=True)
    for b in ("bill-runs.jsonl", "bill-runs-discarded.jsonl", "bill-events.jsonl", "bill-agent-runs.jsonl", "bill-agent-turns.jsonl", "bill-agent-discarded.jsonl"):
        setattr(C, b.replace("bill-", "").replace(".jsonl", "").replace("-", "_"), os.path.join(C.out, b))
    C.log = os.path.join(C.out, "run.log"); C.state = os.path.join(C.out, "state.json")

def refuse_root():
    if os.geteuid() == 0: sys.exit("refusing to run as root: only the operator's powermetrics runs with sudo")

def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(Cfg.log, "a") as f: f.write(line + "\n")

def append(path, rec):
    with open(path, "a") as f: f.write(json.dumps(rec, default=str) + "\n"); f.flush(); os.fsync(f.fileno())

def read_jsonl(path):
    out = []
    if os.path.exists(path):
        for l in open(path):
            l = l.strip()
            if not l: continue
            try: out.append(json.loads(l))
            except Exception: pass  # a line cut by a crash
    return out

def event(ev, **k):
    rec = {"event": ev, "t": time.time(), **k}; append(Cfg.events, rec)
    st = {"last_event": ev, "at": time.strftime("%Y-%m-%d %H:%M:%S"), **{x: k[x] for x in ("name", "phase", "round") if x in k}}
    json.dump(st, open(Cfg.state, "w"))
    return rec

def events(ev=None): return [e for e in read_jsonl(Cfg.events) if ev is None or e["event"] == ev]
def done(ev, **k): return any(all(e.get(a) == b for a, b in k.items()) for e in events(ev))

# ---------------------------------------------------------------- powermetrics liveness
class PMWatch:
    size = -1; changed = 0.0
    @classmethod
    def check(cls):
        if Cfg.dry: return
        try: s = os.path.getsize(Cfg.pm)
        except OSError: s = -1
        now = time.time()
        if s != cls.size: cls.size, cls.changed = s, now; return
        if now - cls.changed > 30:
            log(f"STOP: {Cfg.pm} has not grown for 30 s: powermetrics (Terminal 1) is not sampling. Nothing after this point is measured; see README (powermetrics died)."); sys.exit(4)

def wait_until(t):
    while True:
        now = time.time()
        if now >= t: return
        PMWatch.check(); time.sleep(min(2.0, t - now))

# ---------------------------------------------------------------- server
class Server:
    p = None; phase = None; cmd = None; restarts = 0
    @classmethod
    def command_line(cls, phase):
        return f'~/llama.cpp/build/bin/llama-server -m "/Volumes/T7 Touch/models/Qwen3-8B-Q4_K_M.gguf" ' + " ".join(SERVER_A if phase == "a" else SERVER_B)
    @classmethod
    def kill_leftover(cls):
        pidf = os.path.join(Cfg.out, "server.pid")
        if os.path.exists(pidf):
            try:
                pid = int(open(pidf).read().strip())
                if "llama-server" in sh(f"ps -p {pid} -o command="): os.kill(pid, signal.SIGTERM); time.sleep(3); log("killed a leftover llama-server of this harness, pid", pid)
            except Exception: pass
            os.remove(pidf)
    @classmethod
    def start(cls, phase):
        cls.kill_leftover()
        if sh("pgrep -lx llama-server"): sys.exit("a llama-server is already running; stop it first (the measurement needs a quiet Mac)")
        argv = [LLAMA, "-m", MODEL] + (SERVER_A if phase == "a" else SERVER_B)
        logf = open(os.path.join(Cfg.out, f"server-{phase}.log"), "a")
        cls.p = subprocess.Popen(argv, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        cls.phase, cls.cmd = phase, cls.command_line(phase)
        open(os.path.join(Cfg.out, "server.pid"), "w").write(str(cls.p.pid))
        t0 = time.time()
        while time.time() - t0 < 600:
            if cls.p.poll() is not None: raise RuntimeError(f"llama-server exited at start (rc {cls.p.returncode}); see out/server-{phase}.log")
            try:
                if json.load(urllib.request.urlopen(BASE + "/health", timeout=5)).get("status") == "ok":
                    event("server_start", phase=phase, command=cls.cmd, pid=cls.p.pid, load_s=round(time.time() - t0, 1)); log("server", phase, "up in", round(time.time() - t0, 1), "s"); return
            except Exception: pass
            time.sleep(2)
        raise RuntimeError("server did not start in 600 s")
    @classmethod
    def stop(cls):
        if cls.p and cls.p.poll() is None:
            cls.p.send_signal(signal.SIGTERM)
            try: cls.p.wait(30)
            except Exception: cls.p.kill()
            event("server_stop", phase=cls.phase); log("server", cls.phase, "stopped")
        cls.p = None
        try: os.remove(os.path.join(Cfg.out, "server.pid"))
        except OSError: pass
    @classmethod
    def alive(cls):
        try: return json.load(urllib.request.urlopen(BASE + "/health", timeout=10)).get("status") == "ok"
        except Exception: return False
    @classmethod
    def restart(cls, why):
        log("RESTART server:", why); cls.restarts += 1
        if cls.restarts > 5: raise SystemExit("server restarted 5 times; giving up (see out/server-*.log)")
        ph = cls.phase; cls.stop(); time.sleep(5); cls.start(ph); event("server_restart", phase=ph, why=why)
atexit.register(Server.stop)
signal.signal(signal.SIGTERM, lambda *a: sys.exit(143))

# ---------------------------------------------------------------- client
def post(path, body, timeout=600):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def n_tokens(text):
    if not text: return 0
    return len(post("/tokenize", {"content": text}).get("tokens", []))

def chat(messages, seed, max_tokens, thinking, cache_prompt, tools=None, timeout=900):
    """One POST /v1/chat/completions. Returns a dict with t0/t1 (unix s) and the server's usage and timings."""
    body = {"model": "qwen3", "messages": messages, "max_tokens": max_tokens, "seed": seed, "stream": False, "cache_prompt": cache_prompt,
            **PROMPTS["sampling"]["on" if thinking else "off"], "chat_template_kwargs": {"enable_thinking": thinking}}
    if tools: body["tools"] = tools
    req = urllib.request.Request(BASE + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    r = {"t0": time.time(), "t1": None, "error": None, "error_type": None, "message": None, "usage": {}, "timings": {}, "finish_reason": None}
    try:
        d = json.load(urllib.request.urlopen(req, timeout=timeout))
        ch = d["choices"][0]; r.update(message=ch["message"], usage=d.get("usage", {}), finish_reason=ch.get("finish_reason"),
                                       timings={k: d.get("timings", {}).get(k) for k in ("cache_n", "prompt_n", "prompt_ms", "predicted_n", "predicted_ms", "prompt_per_second", "predicted_per_second")})
    except urllib.error.HTTPError as e:
        try: j = json.loads(e.read().decode()); err = j.get("error", {}); r.update(error=err.get("message", str(e)), error_type=err.get("type", f"http_{e.code}"))
        except Exception: r.update(error=str(e), error_type=f"http_{e.code}")
    except Exception as e:
        r.update(error=repr(e), error_type="connection")
    r["t1"] = time.time()
    return r

def chat_retry(messages, **k):
    """chat() with a server restart on a connection error or timeout (at most 3 tries)."""
    for i in range(3):
        r = chat(messages, **k)
        if r["error_type"] != "connection": return r
        if not Server.alive(): Server.restart(r["error"])
        else: log("request error, server alive:", r["error"])
    return r

def user_msgs(text): return [{"role": "system", "content": PROMPTS["system"]}, {"role": "user", "content": text}]

# ---------------------------------------------------------------- stages shared by both phases
def idle_window(name, secs, phase):
    if done("idle", name=name): log("idle", name, "already done"); return
    log(f"idle window '{name}' {secs:.0f} s: do not touch the Mac")
    a = time.time(); wait_until(a + secs); b = time.time()
    event("idle", name=name, phase=phase, window=[a, b])

def sync_pulse(name, phase):
    if done("sync", name=name): log("sync", name, "already done"); return
    s = PROMPTS["sync"]; log(f"sync pulse '{name}': {Cfg.sync_idle_s:.0f} s idle, then a writing burst")
    a = time.time(); wait_until(a + Cfg.sync_idle_s); b = time.time()
    r = chat_retry(user_msgs(s["user"]), seed=s["seed"], max_tokens=Cfg.sync_max_tokens, thinking=False, cache_prompt=False, timeout=600)
    if r["error"]: raise RuntimeError("sync burst failed: " + str(r["error"]))
    rec = {"set": "sync", "name": name, "phase": phase, "idle": [a, b], "t0": r["t0"], "t1": r["t1"], "usage": r["usage"], "timings": r["timings"], "finish_reason": r["finish_reason"]}
    append(Cfg.runs, rec); event("sync", name=name, phase=phase, idle=[a, b], t0=r["t0"], t1=r["t1"])
    log(f"sync {name}: {r['t1'] - r['t0']:.1f} s burst, {r['timings'].get('predicted_n')} tokens"); wait_until(time.time() + Cfg.settle)

# ---------------------------------------------------------------- Phase A
def longctx_doc():
    p = os.path.join(Cfg.out, "longctx-doc.json")
    if os.path.exists(p):
        d = json.load(open(p))
        if d["doc_tokens"] == Cfg.doc_tokens: return d
    src = PROMPTS["longctx"]["source"]
    if not os.path.exists(src): raise SystemExit(f"long document missing: {src} (fallback in plan section 3 needs the operator's OK to download)")
    raw = open(src, encoding="utf-8", errors="replace").read()
    toks = post("/tokenize", {"content": raw})["tokens"]
    if len(toks) < Cfg.doc_tokens: raise SystemExit(f"long document has only {len(toks)} tokens")
    text = post("/detokenize", {"tokens": toks[:Cfg.doc_tokens]})["content"]
    d = {"source": src, "source_sha256": sha_file(src), "source_tokens": len(toks), "doc_tokens": Cfg.doc_tokens, "doc_sha256": sha(text.encode()), "text": text}
    json.dump(d, open(p, "w")); event("longctx_doc", **{k: v for k, v in d.items() if k != "text"}); return d

def round_items(r):
    order = PROMPTS["kind_order"]; st = r % 4; seq = order[st:] + order[:st]; items = []
    for k in seq: items += [k] * Cfg.per_round[k]
    return items

def plan_order():
    seeds = {k: 0 for k in PROMPTS["kind_order"]}; out = []
    for r in range(Cfg.rounds):
        row = []
        for k in round_items(r): row.append((k, seeds[k])); seeds[k] += 1
        out.append(row)
    return out

def answer_message(kind, doc):
    if kind == "longctx": return doc["text"] + PROMPTS["kinds"]["longctx"]["user_suffix"]
    return PROMPTS["kinds"][kind]["user"]

def one_answer(kind, seed, rnd, doc, gap, set_name="answer"):
    """Settle, answer window [t0, t1 + tail], gap, idle window of the same length. Re-runs a request with cache_n > 0."""
    spec = PROMPTS["kinds"][kind]
    for attempt in range(1, 4):
        wait_until(time.time() + Cfg.settle)
        r = chat_retry(user_msgs(answer_message(kind, doc)), seed=seed, max_tokens=Cfg.max_tokens[kind], thinking=spec["thinking"], cache_prompt=False, timeout=spec["timeout_s"])
        if r["error"]:
            append(Cfg.runs_discarded, {"set": set_name, "kind": kind, "seed": seed, "round": rnd, "attempt": attempt, "why": "error", "error": r["error"], "error_type": r["error_type"]}); log("ERROR", kind, seed, r["error"]); continue
        wait_until(r["t1"] + Cfg.tail); ans = [r["t0"], r["t1"] + Cfg.tail]
        wait_until(ans[1] + gap); i0 = time.time(); wait_until(i0 + (ans[1] - ans[0])); idle = [i0, time.time()]
        t = r["timings"]; m = r["message"] or {}
        rec = {"set": set_name, "phase": "a", "kind": kind, "seed": seed, "round": rnd, "attempt": attempt, "gap_s": gap, "t0": r["t0"], "t1": r["t1"],
               "windows": {"answer": ans, "idle": idle}, "usage": r["usage"], "timings": t, "finish_reason": r["finish_reason"],
               "content": m.get("content") or "", "reasoning_content": m.get("reasoning_content") or ""}
        rec["reasoning_tokens"] = n_tokens(rec["reasoning_content"]) if spec["thinking"] else 0
        if (t.get("cache_n") or 0) > 0:
            rec["why"] = "cache_n > 0"; append(Cfg.runs_discarded, rec); log("DISCARD", kind, seed, "cache_n", t.get("cache_n")); continue
        append(Cfg.runs, rec)
        log(f"{set_name} r{rnd} {kind:7s} seed {seed:3d}: {r['t1'] - r['t0']:6.1f} s  prompt_n {t.get('prompt_n')}  predicted_n {t.get('predicted_n')}  cache_n {t.get('cache_n')}  {r['finish_reason']}")
        return rec
    log("GAVE UP after 3 attempts:", kind, seed); return None

def answers_done(set_name="answer", gap=None):
    s = set()
    for r in read_jsonl(Cfg.runs):
        if r.get("set") == set_name and (gap is None or r.get("gap_s") == gap): s.add((r["kind"], r["seed"]))
    return s

def warm_check(doc):
    """Plan 3: median idle after a kind > 20 % and 0.3 W above idle.before -> re-run that kind once with a 10 s gap."""
    if Cfg.dry or not os.path.exists(Cfg.keys): log("warm check skipped (dry run or no power_keys.json)"); return
    if done("warm_check"): return
    try:
        P = Power.load(Cfg.pm, Cfg.keys, pulses_from_events(events()))
        ib = [e for e in events("idle") if e["name"] == "before"][0]["window"]; base = P.median_w(*ib)
        runs = [r for r in read_jsonl(Cfg.runs) if r.get("set") == "answer"]
        res = {}
        for k in PROMPTS["kind_order"]:
            ws = [P.mean_w(*r["windows"]["idle"]) for r in runs if r["kind"] == k]
            med = statistics.median(ws) if ws else None
            res[k] = {"idle_w_median": med, "warm": bool(med is not None and base and med > 1.2 * base and med - base > 0.3)}
        event("warm_check", idle_before_w=base, by_kind=res, alignment=P.align_info); log("warm check: before", round(base, 3), "W;", {k: (round(v["idle_w_median"] or 0, 3), v["warm"]) for k, v in res.items()})
    except Exception as e:
        event("warm_check", error=repr(e)); log("warm check could not run:", repr(e)); return

def phase_a(args):
    keys_ready()
    Server.start("a"); t_start = time.time()  # the 2-minute warm-up counts from a loaded model
    try:
        log("warm-up: three throwaway short requests")
        for i in range(3 if not Cfg.dry else 1):
            r = chat_retry(user_msgs(PROMPTS["kinds"]["short"]["user"]), seed=1000 + i, max_tokens=256, thinking=False, cache_prompt=False, timeout=300)
            append(Cfg.runs, {"set": "warmup", "phase": "a", "seed": 1000 + i, "t0": r["t0"], "t1": r["t1"], "usage": r["usage"], "timings": r["timings"], "error": r["error"]})
        doc = longctx_doc()
        wait_until(t_start + Cfg.warmup_s)
        sync_pulse("sync", "a")
        idle_window("before", Cfg.idle_before_s, "a")
        have = answers_done()
        for rnd, row in enumerate(plan_order()):
            for kind, seed in row:
                if (kind, seed) in have: continue
                one_answer(kind, seed, rnd, doc, Cfg.gap)
            if not done("round", round=rnd): event("round", round=rnd)
        warm_check(doc)
        wc = (events("warm_check") or [{}])[-1]
        for k, v in (wc.get("by_kind") or {}).items():
            if not v.get("warm"): continue
            log("WARM idle after", k, "-> re-running its runs with a", Cfg.warm_gap, "s gap")
            have_r = answers_done("rerun")
            for rnd, row in enumerate(plan_order()):
                for kind, seed in row:
                    if kind == k and (kind, seed) not in have_r: one_answer(kind, seed, rnd, doc, Cfg.warm_gap, set_name="rerun")
            event("rerun_done", kind=k)
        block_check()
        event("phase_a_done")
    finally:
        Server.stop()

def block_check():
    if done("block"): log("block check already done"); return
    bid = int(time.time()); s0, s1 = PROMPTS["block"]["seeds"]; n = Cfg.block_n
    log(f"block check: {n} short requests back to back"); wait_until(time.time() + Cfg.settle)
    recs = []
    for i in range(n):
        seed = s0 + i
        r = chat_retry(user_msgs(PROMPTS["kinds"]["short"]["user"]), seed=seed, max_tokens=Cfg.max_tokens["short"], thinking=False, cache_prompt=False, timeout=300)
        rec = {"set": "block", "phase": "a", "block_id": bid, "kind": "short", "seed": seed, "t0": r["t0"], "t1": r["t1"], "usage": r["usage"], "timings": r["timings"], "finish_reason": r["finish_reason"], "error": r["error"],
               "content": ((r["message"] or {}).get("content") or "")}
        append(Cfg.runs, rec); recs.append(rec); PMWatch.check()
    a, b = recs[0]["t0"], recs[-1]["t1"] + Cfg.tail; wait_until(b); wait_until(b + Cfg.gap); i0 = time.time(); wait_until(i0 + (b - a))
    event("block", block_id=bid, window=[a, b], idle=[i0, time.time()], n=n, errors=sum(1 for x in recs if x["error"]), cache_n_max=max((x["timings"].get("cache_n") or 0) for x in recs))
    log(f"block check done: {b - a:.0f} s")

def show_a(args):
    """b-roll: one answer, printed live with token counters for live_meter.py; written to out/show-runs.jsonl only."""
    own = not Server.alive()
    if own: Server.start("a")
    try:
        doc = longctx_doc() if args.kind == "longctx" else None; spec = PROMPTS["kinds"][args.kind]
        json.dump({"tokens_in": 0, "tokens_out": 0, "label": f"{args.kind} seed {args.seed}"}, open(os.path.join(Cfg.out, "live-counters.json"), "w"))
        print(f"\n>>> {args.kind}: {(answer_message(args.kind, doc) if args.kind != 'longctx' else '[16,000-token passage] ' + spec['user_suffix'].strip())[:300]}\n", flush=True)
        r = chat(user_msgs(answer_message(args.kind, doc)), seed=args.seed, max_tokens=Cfg.max_tokens[args.kind], thinking=spec["thinking"], cache_prompt=False, timeout=spec["timeout_s"])
        m = r["message"] or {}; u = r["usage"] or {}
        json.dump({"tokens_in": u.get("prompt_tokens", 0), "tokens_out": u.get("completion_tokens", 0), "label": f"{args.kind} seed {args.seed}"}, open(os.path.join(Cfg.out, "live-counters.json"), "w"))
        if m.get("reasoning_content"): print("[thinking]\n" + m["reasoning_content"] + "\n[/thinking]\n")
        print(m.get("content") or r["error"]); print(f"\ntokens in {u.get('prompt_tokens')}  out {u.get('completion_tokens')}  read {r['timings'].get('prompt_ms')} ms  write {r['timings'].get('predicted_ms')} ms")
        append(os.path.join(Cfg.out, "show-runs.jsonl"), {"kind": args.kind, "seed": args.seed, "t0": r["t0"], "t1": r["t1"], "usage": u, "timings": r["timings"]})
    finally:
        if own: Server.stop()

# ---------------------------------------------------------------- powermetrics plist: keys, stream, alignment, energy
def split_plist_stream(data):
    """Documents separated by NUL; returns (parsed list, leftover bytes of a trailing partial record)."""
    parts = data.split(b"\0"); rest = parts.pop(); out = []
    for p in parts:
        p = p.strip()
        if not p: continue
        try: out.append(plistlib.loads(p))
        except Exception: pass
    if rest.strip():
        try: out.append(plistlib.loads(rest.strip())); rest = b""
        except Exception: pass
    return out, rest

def flatten(d, prefix=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items(): out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(d, list):
        for i, v in enumerate(d): out.update(flatten(v, f"{prefix}[{i}]"))
    else: out[prefix] = d
    return out

def get_path(d, path):
    for part in path.split("."):
        if not isinstance(d, dict) or part not in d: return None
        d = d[part]
    return d

def numeric_keys(sample):
    return {k: v for k, v in flatten(sample).items() if isinstance(v, (int, float)) and not isinstance(v, bool) and re.search(r"power|energy|elapsed", k, re.I)}

def make_keys(samples):
    """Plan 2 rules: package > combined > sum of parts; dram/memory key recorded and added."""
    nk = {}
    for s in samples: nk.update(numeric_keys(s))
    flat = [k for k in nk if "[" not in k]
    pick = lambda pat: next((k for k in sorted(flat, key=lambda x: (not x.startswith("processor."), len(x))) if re.search(pat, k.split(".")[-1], re.I)), None)
    package = pick(r"package.*power"); combined = pick(r"^combined_power$"); dram = pick(r"(dram|memory).*power")
    parts = [p for p in (pick(r"^cpu_power$"), pick(r"^gpu_power$"), pick(r"^ane_power$")) if p]
    keys = {"combined": combined, "parts": parts, "package": package, "dram": dram, "elapsed": "elapsed_ns" if "elapsed_ns" in nk else pick(r"elapsed"),
            "timestamp": "timestamp", "thermal": "thermal_pressure" if any("thermal_pressure" in s for s in samples) else None, "unit": "mW"}
    if not (package or combined or len(parts) >= 2): raise SystemExit("no combined, package or summable chip power key in the sampler output: do not run (plan 2)")
    if not keys["elapsed"]: raise SystemExit("no elapsed key in the sampler output")
    return keys, sorted(nk)

def metric_of(keys): return "package" if keys.get("package") else "combined" if keys.get("combined") else "sum_of_parts"

def sample_power(s, keys):
    m = metric_of(keys)
    if m == "package": v = get_path(s, keys["package"])
    elif m == "combined": v = get_path(s, keys["combined"])
    else:
        vs = [get_path(s, k) for k in keys["parts"]]; v = None if any(x is None for x in vs) else sum(vs)
    if v is not None and keys.get("dram"): v += get_path(s, keys["dram"]) or 0
    return v

def cmd_keys(args):
    data = open(args.plist, "rb").read(); samples, _ = split_plist_stream(data)
    if not samples: sys.exit(f"no complete sample in {args.plist}")
    for k, v in sorted(numeric_keys(samples[-1]).items()): print(f"{k:60s} {v}")
    keys, allk = make_keys(samples)
    print("\nproposed power_keys.json:", json.dumps(keys)); print("metric:", metric_of(keys))
    if args.write:
        json.dump(keys, open(Cfg.keys, "w"), indent=1); json.dump({"sampler_keys": allk, "source": args.plist, "source_sha256": sha(data)}, open(os.path.join(Cfg.out, "pm-keys-printed.json"), "w"), indent=1)
        print("written:", Cfg.keys)

def keys_ready():
    if Cfg.dry: return
    if not os.path.exists(Cfg.keys): raise SystemExit("power_keys.json missing: run run_all.sh (it writes it from pm-check.plist after the sudo line)")

def pulses_from_events(evs):
    return [{"name": e["name"], "idle": e["idle"], "t0": e["t0"], "t1": e["t1"]} for e in evs if e["event"] == "sync"]

class Power:
    """Aligned samples: start/end (unix s), p (mW). E(a, b) = sum P_i x |[start_i, end_i] n [a, b]| in joules."""
    def __init__(self, ends_raw, el_s, p, thermal, info):
        self.ends_raw, self.el, self.p, self.thermal, self.align_info = ends_raw, el_s, p, thermal, info
        self.set_offset(lambda t: 0.0)
    def set_offset(self, f):
        self.end = [e + f(e) for e in self.ends_raw]; self.start = [e - d for e, d in zip(self.end, self.el)]
    @classmethod
    def load(cls, path, keys_path, pulses, mtime_anchor=None):
        # pm.plist may still be growing (powermetrics keeps running): read it ONCE and take its mtime right after the read,
        # before the long parse, so the mtime matches the last sample read (getmtime after parsing a 1.4 GB file was ~50 s late)
        keys = json.load(open(keys_path))
        with open(path, "rb") as f: data = f.read(); mtime_read = os.fstat(f.fileno()).st_mtime
        samples, _ = split_plist_stream(data)
        if len(samples) < 10: raise ValueError(f"only {len(samples)} samples in {path}")
        comp = [k for k in ([keys.get("combined")] + keys.get("parts", []) + [keys.get("package"), keys.get("dram")]) if k]
        el, p, th, ts, comp_rows = [], [], [], [], []
        for s in samples:
            e = get_path(s, keys["elapsed"]); v = sample_power(s, keys)
            if e is None or v is None: continue
            el.append(e / 1e9); p.append(float(v)); th.append(s.get("thermal_pressure"))  # thermal sampler is in pm.plist even when the key check plist lacks it
            t = s.get(keys.get("timestamp") or "timestamp"); ts.append(t.replace(tzinfo=dt.timezone.utc).timestamp() if isinstance(t, dt.datetime) else None)
            comp_rows.append([get_path(s, k) for k in comp])
        del samples
        cum = []; c = 0.0
        for e in el: c += e; cum.append(c)
        mt = (mtime_anchor or mtime_read) - cum[-1]
        if ts[0] is not None and abs((ts[0] - cum[0]) - mt) <= 30: anchor = ts[0] - cum[0]; anchor_src = "timestamp_first_sample"
        else: anchor = mt; anchor_src = "file_mtime_last_sample" + ("" if ts[0] is None else f" (timestamp anchor off by {(ts[0] - cum[0]) - mt:.1f} s)")
        ends_raw = [anchor + x for x in cum]
        ts_ok = [(t, e) for t, e in zip(ts, ends_raw) if t is not None]
        info = {"samples_n": len(p), "anchor": anchor_src, "raw_sha256": sha(data), "elapsed_sum_s": round(cum[-1], 3),
                "timestamp_span_minus_elapsed_s": round((ts_ok[-1][0] - ts_ok[0][0]) - (ts_ok[-1][1] - ts_ok[0][1]), 3) if len(ts_ok) > 1 else None,
                "gaps_over_1s": sum(1 for x in el if x > 1.0), "metric": metric_of(keys), "keys": keys}
        P = cls(ends_raw, el, p, th, info); P.components = (comp, comp_rows); P.align(pulses); return P
    def _idx(self, a):
        lo, hi = 0, len(self.end)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.end[mid] <= a: lo = mid + 1
            else: hi = mid
        return lo
    def E(self, a, b):
        if b <= a: return 0.0
        i = self._idx(a); j = 0.0
        while i < len(self.end) and self.start[i] < b:
            ov = min(b, self.end[i]) - max(a, self.start[i])
            if ov > 0: j += self.p[i] * ov
            i += 1
        return j / 1000.0
    def covered(self, a, b):
        i = self._idx(a); c = 0.0
        while i < len(self.end) and self.start[i] < b:
            c += max(0.0, min(b, self.end[i]) - max(a, self.start[i])); i += 1
        return c
    def mean_w(self, a, b): return self.E(a, b) / (b - a) if b > a else None
    def in_window(self, a, b):
        out = []; k = self._idx(a)
        while k < len(self.end) and self.start[k] < b:
            if a <= (self.start[k] + self.end[k]) / 2 <= b: out.append(k)
            k += 1
        return out
    def median_w(self, a, b):
        ix = self.in_window(a, b); return statistics.median(self.p[k] for k in ix) / 1000.0 if ix else None
    def thermal_mode(self, a, b):
        v = [self.thermal[k] for k in self.in_window(a, b) if self.thermal[k]]
        return max(set(v), key=v.count) if v else None
    def pulse_offset(self, pl):
        """Offset (s) to add to raw times: logged burst start minus the start of the first sample above idle + half the burst's rise."""
        self.set_offset(lambda t: 0.0)
        a, b = pl["idle"]; t0, t1 = pl["t0"], pl["t1"]
        mi, mb = min(3.0, 0.25 * (b - a)), min(3.0, 0.25 * (t1 - t0))  # 3 s margins for the 30 s / 20 s pulses; smaller for the dry run's short pulses
        idle = self.median_w(a + mi, b - mi); burst = self.median_w(t0 + mb, t1 - mb)
        if idle is None or burst is None or burst <= idle: return None
        thr = (idle + 0.5 * (burst - idle)) * 1000.0
        ix = []; k = self._idx((a + b) / 2)
        while k < len(self.end) and self.start[k] < t1: ix.append(k); k += 1
        for n, k in enumerate(ix):
            if self.p[k] > thr and n >= 3 and all(self.p[x] <= thr for x in ix[max(0, n - 3):n]):
                # sub-sample rise time: the excess energy of samples k-1 and k over idle, divided by the burst's rise in power
                exc = sum((self.p[x] - idle * 1000.0) * self.el[x] for x in (ix[n - 1], k)) / ((burst - idle) * 1000.0)
                return t0 - (self.end[k] - min(max(exc, 0.0), self.el[k] + self.el[ix[n - 1]]))
        return None
    def align(self, pulses):
        offs = []
        for pl in pulses:
            o = self.pulse_offset(pl)
            if o is not None: offs.append({"name": pl["name"], "t_raw": pl["t0"] - o, "offset_s": o})
        info = self.align_info
        if not offs:
            info.update(method="cumulative_elapsed", offset_ms=0.0, drift_ms=None, check_ms=None, pulses=[], ok=False); self.set_offset(lambda t: 0.0); return
        o = statistics.mean(x["offset_s"] for x in offs)
        drift = (max(x["offset_s"] for x in offs) - min(x["offset_s"] for x in offs)) * 1000
        check = max(abs(x["offset_s"] - o) for x in offs) * 1000
        ok = drift <= 200 and check <= 200 and len(offs) == len(pulses)
        info.update(method="cumulative_elapsed", offset_ms=round(o * 1000, 1), drift_ms=round(drift, 1), check_ms=round(check, 1), pulses=[{k: (round(v * 1000, 1) if k == "offset_s" else v) for k, v in x.items() if k != "t_raw"} for x in offs], ok=ok, pulses_expected=len(pulses), pulses_found=len(offs))
        if ok or len(offs) < 2: self.set_offset(lambda t: o)
        else:
            pts = sorted((x["t_raw"], x["offset_s"]) for x in offs)
            def f(t):
                if t <= pts[0][0]: return pts[0][1]
                if t >= pts[-1][0]: return pts[-1][1]
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    if x0 <= t <= x1: return y0 + (y1 - y0) * (t - x0) / (x1 - x0)
            self.set_offset(f); info["method"] = "cumulative_elapsed+pulse_linear (fallback: drift over 200 ms)"

# ---------------------------------------------------------------- reduce
def med(xs):
    xs = [x for x in xs if x is not None]; return statistics.median(xs) if xs else None
def iqr(xs):
    xs = sorted(x for x in xs if x is not None)
    if len(xs) < 2: return None
    q = statistics.quantiles(xs, n=4, method="inclusive"); return q[2] - q[0]
def rnd(x, n=4):
    if isinstance(x, float): return float(f"{x:.12g}")
    if isinstance(x, dict): return {k: rnd(v, n) for k, v in x.items()}
    if isinstance(x, list): return [rnd(v, n) for v in x]
    return x
def div(a, b): return (a / b) if (a is not None and b) else None

def answer_energy(P, r, idle_before_w):
    (a0, a1), (i0, i1) = r["windows"]["answer"], r["windows"]["idle"]
    t0, t1 = r["t0"], r["t1"]; pm_s = (r["timings"].get("prompt_ms") or 0) / 1000.0
    pi = P.mean_w(i0, i1); rd = (t0, min(t0 + pm_s, t1)); wr = (rd[1], t1); tl = (t1, a1)
    net = lambda w: P.E(*w) - pi * (w[1] - w[0])
    o = {"seconds": t1 - t0, "idle_window_watts_mean": pi, "joules_gross": P.E(a0, a1), "joules_net": P.E(a0, a1) - P.E(i0, i1),
         "joules_net_vs_idle_before": P.E(a0, a1) - idle_before_w * (a1 - a0),
         "reading": {"seconds": rd[1] - rd[0], "joules_net": net(rd), "resolved": rd[1] - rd[0] >= 1.0},
         "writing": {"seconds": wr[1] - wr[0], "joules_net": net(wr), "resolved": wr[1] - wr[0] >= 1.0},
         "tail": {"seconds": tl[1] - tl[0], "joules_net": net(tl)}, "coverage": P.covered(a0, a1) / (a1 - a0) if a1 > a0 else None}
    o["writing"]["watts_net"] = div(o["writing"]["joules_net"], o["writing"]["seconds"]); o["reading"]["watts_net"] = div(o["reading"]["joules_net"], o["reading"]["seconds"])
    return o

def agent_energy(P, run, turns, idle_before_w):
    (a0, a1), (i0, i1) = run["windows"]["run"], run["windows"]["idle"]
    pi = P.mean_w(i0, i1); rd_s = wr_s = rd_e = wr_e = 0.0; resolved = 0.0
    for t in turns:
        pm_s = (t["timings"].get("prompt_ms") or 0) / 1000.0; r0, r1 = t["t0_unix"], min(t["t0_unix"] + pm_s, t["t1_unix"]); w0, w1 = r1, t["t1_unix"]
        rd_s += r1 - r0; wr_s += w1 - w0; rd_e += P.E(r0, r1); wr_e += P.E(w0, w1)
        if r1 - r0 >= 1.0: resolved += r1 - r0
        t["_reading_net"] = P.E(r0, r1) - pi * (r1 - r0)
    tot = P.E(a0, a1); run_s = a1 - a0; tl_s = run_s - rd_s - wr_s; tl_e = tot - rd_e - wr_e
    o = {"seconds_window": run_s, "idle_window_watts_mean": pi, "joules_gross": tot, "joules_net": tot - P.E(i0, i1), "joules_net_vs_idle_before": tot - idle_before_w * run_s,
         "reading": {"seconds": rd_s, "joules_net": rd_e - pi * rd_s}, "writing": {"seconds": wr_s, "joules_net": wr_e - pi * wr_s},
         "tools": {"seconds": tl_s, "joules_net": tl_e - pi * tl_s}, "reading_resolved_seconds": resolved, "coverage": P.covered(a0, a1) / run_s if run_s > 0 else None}
    o["writing"]["watts_net"] = div(o["writing"]["joules_net"], wr_s)
    return o

def linfit(xs, ys):
    n = len(xs)
    if n < 3: return {"slope_j_per_token": None, "intercept_j": None, "r2": None, "n": n}
    mx, my = sum(xs) / n, sum(ys) / n; sxx = sum((x - mx) ** 2 for x in xs); sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if not sxx: return {"slope_j_per_token": None, "intercept_j": None, "r2": None, "n": n}
    b = sxy / sxx; a = my - b * mx; ss = sum((y - my) ** 2 for y in ys); res = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys))
    return {"slope_j_per_token": b, "intercept_j": a, "r2": 1 - res / ss if ss else None, "n": n}

def reduce_all(args):
    evs = events(); runs = read_jsonl(Cfg.runs); aruns = read_jsonl(Cfg.agent_runs); aturns = read_jsonl(Cfg.agent_turns)
    if not os.path.exists(Cfg.pm): print(f"FAIL: {Cfg.pm} missing; run files kept, re-run `harness.py reduce` when it is there"); return 2
    if not os.path.exists(Cfg.keys): print(f"FAIL: {Cfg.keys} missing"); return 2
    pulses = pulses_from_events(evs)
    try: P = Power.load(Cfg.pm, Cfg.keys, pulses)
    except Exception as e: print("FAIL: cannot read the power samples:", repr(e)); return 2
    A = P.align_info; idle_ev = {e["name"]: e["window"] for e in evs if e["event"] == "idle"}
    def idle_stat(n):
        w = idle_ev.get(n); return {"watts_median": P.median_w(*w), "watts_mean": P.mean_w(*w), "seconds": w[1] - w[0]} if w else {"watts_median": None, "seconds": None}
    idle = {n: idle_stat(n) for n in ("before", "phase_b_before", "after")}
    ib = idle["before"]["watts_mean"] or idle["before"]["watts_median"] or 0.0
    # Phase A answers: the warm re-run set replaces a kind's set when it exists
    wc = ([e for e in evs if e["event"] == "warm_check"] or [{}])[-1].get("by_kind") or {}
    rerun_kinds = {e["kind"] for e in evs if e["event"] == "rerun_done"}
    ans_by = {}; all_idle_w = []
    for k in PROMPTS["kind_order"]:
        set_name = "rerun" if k in rerun_kinds else "answer"
        rs = sorted([r for r in runs if r.get("set") == set_name and r.get("kind") == k], key=lambda r: r["seed"])
        seen = {}
        for r in rs: seen[r["seed"]] = r  # last attempt per seed
        ans_by[k] = (set_name, list(seen.values()))
    answers = {}; per_tok = {}; fit_x, fit_y = [], []; rounds_th = {}
    for k, (set_name, rs) in ans_by.items():
        rows = []
        for r in rs:
            e = answer_energy(P, r, ib); t = r["timings"]; u = r["usage"]
            all_idle_w.append(e["idle_window_watts_mean"])
            rows.append({"seed": r["seed"], "round": r["round"], "gap_s": r["gap_s"], "t0": r["t0"], "t1": r["t1"], "prompt_n": t.get("prompt_n"), "prompt_ms": t.get("prompt_ms"), "predicted_n": t.get("predicted_n"),
                         "predicted_ms": t.get("predicted_ms"), "cache_n": t.get("cache_n"), "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                         "reasoning_tokens": r.get("reasoning_tokens"), "finish_reason": r.get("finish_reason"), "thermal_pressure": P.thermal_mode(*r["windows"]["answer"]), **e})
            rounds_th.setdefault(r["round"], []).append(P.thermal_mode(*r["windows"]["answer"]))
            if k in ("short", "think", "long") and t.get("predicted_n"): fit_x.append(t["predicted_n"]); fit_y.append(e["writing"]["joules_net"])
        if not rows: answers[k] = {"n": 0, "runs": []}; continue
        J = [x["joules_net"] for x in rows]; sum_net = sum(J); sum_rd = sum(x["reading"]["joules_net"] for x in rows)
        b = {"n": len(rows), "set": set_name, "seconds_median": med([x["seconds"] for x in rows]), "prompt_n_median": med([x["prompt_n"] for x in rows]), "predicted_n_median": med([x["predicted_n"] for x in rows]),
             "prompt_tokens_median": med([x["prompt_tokens"] for x in rows]), "completion_tokens_median": med([x["completion_tokens"] for x in rows]),
             "joules_median": med(J), "joules_iqr": iqr(J), "wh_median": div(med(J), 3600), "joules_net_vs_idle_before_median": med([x["joules_net_vs_idle_before"] for x in rows]),
             "tail": {"seconds_median": med([x["tail"]["seconds"] for x in rows]), "joules_net_median": med([x["tail"]["joules_net"] for x in rows])},
             "decode_joules_median": med([x["writing"]["joules_net"] for x in rows]), "decode_watts_median": med([x["writing"]["watts_net"] for x in rows]),
             "prefill_joules_median": med([x["reading"]["joules_net"] for x in rows]), "prefill_seconds_median": med([x["reading"]["seconds"] for x in rows]),
             "prefill_share": div(sum_rd, sum_net), "negative_net": sum(1 for j in J if j < 0), "reading_resolved_n": sum(1 for x in rows if x["reading"]["resolved"]), "runs": rows}
        b["spread"] = div(b["joules_iqr"], b["joules_median"])
        if k == "longctx": b["prefill_watts_median"] = med([x["reading"]["watts_net"] for x in rows])
        if k == "think": b["reasoning_tokens_median"] = med([x["reasoning_tokens"] for x in rows]); b["hit_cap"] = sum(1 for x in rows if x["finish_reason"] == "length")
        if k in ("short", "think", "long"): per_tok[k] = div(sum(x["writing"]["joules_net"] for x in rows), sum(x["predicted_n"] or 0 for x in rows))
        answers[k] = b
    # block check
    blk = None; bev = [e for e in evs if e["event"] == "block"]
    if bev:
        be = bev[-1]; brs = [r for r in runs if r.get("set") == "block" and r.get("block_id") == be["block_id"]]
        (a0, a1), (i0, i1) = be["window"], be["idle"]; pi = P.mean_w(i0, i1); all_idle_w.append(pi)
        wr = [(r["t0"] + (r["timings"].get("prompt_ms") or 0) / 1000, r["t1"]) for r in brs]; wr_s = sum(b - a for a, b in wr); wr_net = sum(P.E(a, b) for a, b in wr) - pi * wr_s
        jn = P.E(a0, a1) - P.E(i0, i1); n = len(brs)
        blk = {"short": {"n": n, "seconds": a1 - a0, "joules_net": jn, "joules_per_answer": div(jn, n), "watts_net": div(wr_net, wr_s), "idle_window_watts_mean": pi,
                         "vs_median": div(div(jn, n), (answers.get("short") or {}).get("joules_median")), "cache_n_max": be.get("cache_n_max"), "errors": be.get("errors")}}
    # Phase B agent runs
    agent = {}; depth_bins = {"0-4k": [0.0, 0], "4-8k": [0.0, 0], "8-16k": [0.0, 0], "16-32k": [0.0, 0]}; cached_after1 = cached_hits = 0; ag_idle = {"nocache": [], "cached": []}
    for arm in ("nocache", "cached"):
        rs = sorted([r for r in aruns if r["arm"] == arm], key=lambda r: r["seed"]); rows = []
        for r in rs:
            ts = sorted([t for t in aturns if t["arm"] == arm and t["seed"] == r["seed"] and t.get("run_id") == r.get("run_id")], key=lambda t: t["turn"])
            e = agent_energy(P, r, ts, ib); ag_idle[arm].append(e["idle_window_watts_mean"]); all_idle_w.append(e["idle_window_watts_mean"])
            for t in ts:
                if t["turn"] >= 1 and arm == "cached":
                    cached_after1 += 1; cached_hits += (t["timings"].get("cache_n") or 0) > 0
                if arm == "nocache":
                    pt = t["usage"].get("prompt_tokens") or 0; bn = "0-4k" if pt < 4096 else "4-8k" if pt < 8192 else "8-16k" if pt < 16384 else "16-32k"
                    depth_bins[bn][0] += t["_reading_net"]; depth_bins[bn][1] += pt
            rows.append({k: r.get(k) for k in ("seed", "run_id", "passed", "tests_passed", "tests_modified", "turns", "seconds", "stuck", "nudged", "prompt_tokens_sum", "completion_tokens_sum", "prompt_n_sum", "cache_n_sum", "max_prompt_tokens", "cache_misses", "transcript_sha256")}
                        | {"minutes": r["seconds"] / 60, "thermal_pressure": P.thermal_mode(*r["windows"]["run"]), **e})
        if not rows: agent[arm] = {"n": 0, "runs": []}; continue
        J = [x["joules_net"] for x in rows]; sum_net = sum(J); rd_tot = sum(x["reading"]["seconds"] for x in rows)
        b = {"n": len(rows), "passed": sum(1 for x in rows if x["passed"]), "turns_median": med([x["turns"] for x in rows]), "seconds_median": med([x["seconds"] for x in rows]),
             "prompt_tokens_median": med([x["prompt_tokens_sum"] for x in rows]), "completion_tokens_median": med([x["completion_tokens_sum"] for x in rows]),
             "prompt_n_sum_median": med([x["prompt_n_sum"] for x in rows]), "cache_n_sum_median": med([x["cache_n_sum"] for x in rows]), "max_prompt_tokens": max(x["max_prompt_tokens"] or 0 for x in rows),
             "joules_median": med(J), "joules_iqr": iqr(J), "joules_net_vs_idle_before_median": med([x["joules_net_vs_idle_before"] for x in rows]),
             "reading": {"joules_median": med([x["reading"]["joules_net"] for x in rows]), "seconds_median": med([x["reading"]["seconds"] for x in rows])},
             "writing": {"joules_median": med([x["writing"]["joules_net"] for x in rows]), "seconds_median": med([x["writing"]["seconds"] for x in rows]), "watts_median": med([x["writing"]["watts_net"] for x in rows])},
             "tools": {"joules_median": med([x["tools"]["joules_net"] for x in rows]), "seconds_median": med([x["tools"]["seconds"] for x in rows])},
             "prefill_share": div(sum(x["reading"]["joules_net"] for x in rows), sum_net), "reading_resolved_share": div(sum(x["reading_resolved_seconds"] for x in rows), rd_tot),
             "fresh_read_share": div(sum(x["prompt_n_sum"] or 0 for x in rows), sum(x["prompt_tokens_sum"] or 0 for x in rows)), "turns_by_seed": {x["seed"]: x["turns"] for x in rows}, "runs": rows}
        b["minutes_median"] = div(b["seconds_median"], 60); b["spread"] = div(b["joules_iqr"], b["joules_median"])
        if arm == "cached": b["cache_misses"] = sum(x["cache_misses"] or 0 for x in rows)
        agent[arm] = b
    agent["passed_total"] = sum((agent.get(a) or {}).get("passed", 0) for a in ("nocache", "cached")); agent["runs_total"] = sum((agent.get(a) or {}).get("n", 0) for a in ("nocache", "cached"))
    # idle summary
    idle["watts_median"] = med(all_idle_w + [x["watts_median"] for x in (idle["before"], idle["phase_b_before"], idle["after"]) if x.get("watts_median") is not None])
    idle["drift"] = div((idle["after"]["watts_median"] or 0) - (idle["before"]["watts_median"] or 0), idle["before"]["watts_median"]) if idle["after"]["watts_median"] is not None else None
    bk = {}
    for k in PROMPTS["kind_order"]:
        ws = [x["idle_window_watts_mean"] for x in (answers.get(k) or {}).get("runs", [])]; m = med(ws); base = idle["before"]["watts_median"]
        bk[k] = {"watts_median": m, "settled": not (m is not None and base and m > 1.2 * base and m - base > 0.3), "warm_check": wc.get(k), "rerun": k in rerun_kinds}
    for arm in ("nocache", "cached"):
        m = med(ag_idle[arm]); base = idle["phase_b_before"]["watts_median"] or idle["before"]["watts_median"]
        bk["agent_" + arm] = {"watts_median": m, "settled": not (m is not None and base and m > 1.2 * base and m - base > 0.3)}
    idle["by_kind"] = bk
    # derived
    g = lambda d, *ks: (lambda v: v)(__import__("functools").reduce(lambda x, k: (x or {}).get(k) if isinstance(x, dict) else None, ks, d))
    sj = g(answers, "short", "joules_median"); lr = (answers.get("long") or {}).get("runs", []); lc = (answers.get("longctx") or {}).get("runs", [])
    jpw = div(sum(x["writing"]["joules_net"] for x in lr), sum(x["predicted_n"] or 0 for x in lr)); jpr = div(sum(x["reading"]["joules_net"] for x in lc), sum(x["prompt_n"] or 0 for x in lc))
    ptw = [v for v in per_tok.values() if v]
    nc = agent.get("nocache") or {}; ca = agent.get("cached") or {}
    nc_rd = sum(x["reading"]["joules_net"] for x in nc.get("runs", [])); nc_pt = sum(x["prompt_tokens_sum"] or 0 for x in nc.get("runs", []))
    derived = {"think_vs_short_multiple": div(g(answers, "think", "joules_median"), sj), "longctx_vs_short_multiple": div(g(answers, "longctx", "joules_median"), sj),
               "joules_per_thousand_written": jpw * 1000 if jpw is not None else None, "joules_per_thousand_read": jpr * 1000 if jpr is not None else None,
               "per_token_written": per_tok, "per_token_spread": div(max(ptw) - min(ptw), min(ptw)) if len(ptw) > 1 else None, "per_token_fit": linfit(fit_x, fit_y),
               "write_read_ratio": div(jpw, jpr), "bulb_seconds_short": div(sj, BULB_W), "bulb_seconds_short_block": div(g(blk or {}, "short", "joules_per_answer"), BULB_W),
               "bulb_seconds_think": div(g(answers, "think", "joules_median"), BULB_W), "bulb_watts": BULB_W,
               "agent_read_write_ratio": div(nc.get("prompt_tokens_median"), nc.get("completion_tokens_median")), "agent_cached_vs_nocache": div(ca.get("joules_median"), nc.get("joules_median")),
               "agent_joules_per_thousand_read": div(nc_rd, nc_pt) * 1000 if nc_pt else None,
               "reading_j_per_thousand_by_depth": {k: {"j_per_thousand": div(v[0], v[1]) * 1000 if v[1] else None, "prompt_tokens": v[1]} for k, v in depth_bins.items()}}
    # money and scale
    usd = lambda j: j / 3.6e6 * TARIFF if j is not None else None
    mk, op, hk = PRICES["maker"], PRICES["opus_5_5"], PRICES["haiku_5_5"]
    sp, sc = g(answers, "short", "prompt_tokens_median"), g(answers, "short", "completion_tokens_median")
    s_local = usd(sj); s_api = (sp * mk["input"] + sc * mk["output"]) / 1e6 if sp is not None and sc is not None else None
    P_, C_ = nc.get("prompt_tokens_median"), nc.get("completion_tokens_median")
    hk_ok = (nc.get("max_prompt_tokens") or 0) <= hk["prompt_limit"]; hin, hout = (hk["input"], hk["output"]) if hk_ok else (hk["above_limit"]["input"], hk["above_limit"]["output"])
    tok = lambda p, c, i, o: (p * i + c * o) / 1e6 if p is not None and c is not None else None
    cP, cC, cPN, cCN = ca.get("prompt_tokens_median"), ca.get("completion_tokens_median"), ca.get("prompt_n_sum_median"), ca.get("cache_n_sum_median")
    money = {"tariff_usd_per_kwh": TARIFF, "tariff_source": "EIA Electric Power Monthly Table 5.6.A, residential, U.S. Total, July 2026 (released 2026-09-24)",
             "price": PRICES, "token_basis": "server token counts (usage / timings); the cloud's tokenizer and chat template may count a few tokens differently",
             "short": {"local_usd": s_local, "api_usd": s_api, "local_usd_per_thousand": s_local * 1000 if s_local is not None else None, "api_usd_per_thousand": s_api * 1000 if s_api is not None else None, "ratio": div(s_api, s_local)},
             "agent_nocache": {"local_usd": usd(nc.get("joules_median")), "api_usd": tok(P_, C_, mk["input"], mk["output"]), "opus_usd": tok(P_, C_, op["input"], op["output"]),
                               "haiku_usd": tok(P_, C_, hin, hout), "haiku_tier_ok": hk_ok},
             "agent_cached": {"local_usd": usd(ca.get("joules_median")), "api_usd_with_cache_hits_at_base": tok(cP, cC, mk["input"], mk["output"]),
                              "opus_usd_cached": ((cPN * op["input"] + cCN * op["cache_hit"] + cC * op["output"]) / 1e6) if None not in (cPN, cCN, cC) else None}}
    akwh = SCALE_TICKETS * nc["joules_median"] / 3.6e6 if nc.get("joules_median") is not None else None
    scale = {"tickets": SCALE_TICKETS, "kind": "agent_nocache", "agent_kwh": akwh, "home_kwh_per_year": HOME_KWH, "agent_home_years": div(akwh, HOME_KWH),
             "agent_api_usd": SCALE_TICKETS * money["agent_nocache"]["api_usd"] if money["agent_nocache"]["api_usd"] is not None else None,
             "agent_opus_usd": SCALE_TICKETS * money["agent_nocache"]["opus_usd"] if money["agent_nocache"]["opus_usd"] is not None else None}
    # cold-open example: nocache run closest to both medians
    cands = []
    for x in nc.get("runs", []):
        if P_ and C_: cands.append((max(abs(x["prompt_tokens_sum"] - P_) / P_, abs(x["completion_tokens_sum"] - C_) / C_), x))
    cands.sort(key=lambda c: c[0])
    ex = {"cold_open": {"agent_seed": cands[0][1]["seed"] if cands else None, "agent_prompt_tokens": cands[0][1]["prompt_tokens_sum"] if cands else None,
                        "agent_completion_tokens": cands[0][1]["completion_tokens_sum"] if cands else None, "within_15pct": bool(cands and cands[0][0] <= 0.15),
                        "next_closest_seeds": [c[1]["seed"] for c in cands[1:3]], "recording": None}, "longctx_recording": None}
    # checks
    cfg_ag = json.load(open(os.path.join(Cfg.out, "verify.json"))) if os.path.exists(os.path.join(Cfg.out, "verify.json")) else {}
    pa = [r for r in runs if r.get("set") in ("answer", "rerun", "block")]
    nc_turns = [t for t in aturns if t["arm"] == "nocache" and any(r.get("run_id") == t.get("run_id") for r in aruns)]
    checks = {"cache_n_all_zero": all((r["timings"].get("cache_n") or 0) == 0 for r in pa) and all((t["timings"].get("cache_n") or 0) == 0 for t in nc_turns),
              "prompt_reread_all": all(r["timings"].get("prompt_n") == r["usage"].get("prompt_tokens") for r in pa if r["timings"].get("prompt_n") is not None) and all(t["timings"].get("prompt_n") == t["usage"].get("prompt_tokens") for t in nc_turns),
              "longctx_prompt_n_ok": bool(lc) and all(PROMPTS["longctx"]["prompt_n_min"] - (16000 - Cfg.doc_tokens) <= (x["prompt_n"] or 0) <= PROMPTS["longctx"]["prompt_n_max"] - (16000 - Cfg.doc_tokens) for x in lc),
              "cached_arm_hits": div(cached_hits, cached_after1), "alignment_ok": A.get("ok", False)}
    machine = json.load(open(os.path.join(Cfg.out, "checks.json"))).get("machine", {}) if os.path.exists(os.path.join(Cfg.out, "checks.json")) else {}
    chk = json.load(open(os.path.join(Cfg.out, "checks.json"))) if os.path.exists(os.path.join(Cfg.out, "checks.json")) else {}
    machine["thermal_pressure"] = {"per_round": {str(k): (max(set([v for v in vs if v]), key=[v for v in vs if v].count) if any(vs) else None) for k, vs in sorted(rounds_th.items())},
                                   "per_ticket_run": {f"{a}-{x['seed']}": x["thermal_pressure"] for a in ("nocache", "cached") for x in (agent.get(a) or {}).get("runs", [])}}
    doc = json.load(open(os.path.join(Cfg.out, "longctx-doc.json"))) if os.path.exists(os.path.join(Cfg.out, "longctx-doc.json")) else {}
    pkp = os.path.join(Cfg.out, "pm-keys-printed.json"); pk = json.load(open(pkp)) if os.path.exists(pkp) else {}
    helpf = os.path.join(HERE if not Cfg.dry else Cfg.out, "powermetrics-help.txt")
    srv = {e["phase"]: e["command"] for e in evs if e["event"] == "server_start"}
    hfiles = {f: sha_file(os.path.join(HERE, f)) for f in HARNESS_FILES if os.path.exists(os.path.join(HERE, f))}
    if Cfg.dry and os.path.exists(Cfg.keys): hfiles["power_keys.json"] = sha_file(Cfg.keys)
    cap = {"schema_version": "ep22-bill-capture-2", "captured_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "dry_run": Cfg.dry,
           "machine": machine, "llama_cpp": {"output": chk.get("llama_cpp_output")}, "model": {"file": os.path.basename(MODEL), "size_bytes": chk.get("model_size"), "sha256": chk.get("model_sha256")},
           "harness": {"sha256": hfiles, "copied_from": {"make_demo_repo.py": "~/ep22-lab/factory/demo/make_demo_repo.py (unchanged)", "sandbox.py": "~/ep22-lab/factory/demo/harness.py (unchanged)",
                                                          "run_ticket.py": "run_small/grade of ~/ep22-lab/factory/demo/run_demo.py sha256 " + chk.get("run_demo_sha256", "?") + " + timing hooks + per-arm cache_prompt"},
                       "deviations": ["the harness starts and stops llama-server itself (as run_demo.py did), with the plan's exact flags",
                                      "sampler key check (step 1) folded into the operator's single sudo line; keys written by run_all.sh from pm-check.plist",
                                      "powermetrics -h read without sudo (it needs no root)",
                                      "grading runs after the ticket run's idle window, so no unittest process lands inside a measured window",
                                      "warm-idle re-run uses a 10 s gap between the answer and its idle window",
                                      "pm.plist timestamps anchor the cumulative elapsed time; the sync pulses then set the offset"]},
           "prompts": {"sha256": sha_file(os.path.join(HERE, "prompts.json"))},
           "server": {"phase_a": {"command": srv.get("a", Server.command_line("a"))}, "phase_b": {"command": srv.get("b", Server.command_line("b"))}, "help_sha256": chk.get("server_help_sha256"),
                      "restarts": [e for e in evs if e["event"] == "server_restart"]},
           "power": {"tool": "powermetrics", "command": PM_CMD, "interval_ms": 200, "help_sha256": sha_file(helpf) if os.path.exists(helpf) else None, "sampler_keys": pk.get("sampler_keys"),
                     "keys_sha256": sha_file(Cfg.keys), "metric": A["metric"], "keys": A["keys"], "dram_key": A["keys"].get("dram"), "alignment_method": A.get("method"), "alignment_offset_ms": A.get("offset_ms"),
                     "alignment_drift_ms": A.get("drift_ms"), "alignment_check_ms": A.get("check_ms"), "alignment_pulses": A.get("pulses"), "anchor": A.get("anchor"),
                     "timestamp_span_minus_elapsed_s": A.get("timestamp_span_minus_elapsed_s"), "gaps_over_1s": A.get("gaps_over_1s"), "samples_n": A["samples_n"], "raw_sha256": A["raw_sha256"],
                     "note": "chip power as powermetrics estimates it; not wall power; not comparable across devices"},
           "config": {"runs": {k: Cfg.per_round[k] * Cfg.rounds for k in PROMPTS["kind_order"]}, "seeds": {k: f"0-{Cfg.per_round[k] * Cfg.rounds - 1}" for k in PROMPTS["kind_order"]},
                      "order": [[f"{k}:{s}" for k, s in row] for row in plan_order()], "max_tokens": Cfg.max_tokens, "sampling": PROMPTS["sampling"], "cache_prompt": False, "cache_ram": 0,
                      "windows": {"settle_s": Cfg.settle, "tail_s": Cfg.tail, "gap_s": Cfg.gap, "warm_gap_s": Cfg.warm_gap},
                      "longctx": {k: doc.get(k) for k in ("source", "source_sha256", "doc_tokens", "doc_sha256", "source_tokens")},
                      "agent": {"ticket": "easy", "ticket_text": cfg_ag.get("ticket_text"), "builder_sha256": hfiles.get("make_demo_repo.py"), "system_prompt": PROMPTS["agent"]["system_prompt"],
                                "max_turns": Cfg.agent_max_turns, "shell_timeout_s": 30, "trunc_chars": 4000, "max_tokens": 2048, "runs": {"nocache": sum(1 for s, a in Cfg.agent_order if a == "nocache"), "cached": sum(1 for s, a in Cfg.agent_order if a == "cached")},
                                "seeds": sorted({s for s, a in Cfg.agent_order}), "order": [f"{s}:{a}" for s, a in Cfg.agent_order], "baseline_failing": cfg_ag.get("baseline_failing"),
                                "reference_solution_passes": cfg_ag.get("reference_solution_passes"), "flushes": sum(1 for e in evs if e["event"] == "flush"),
                                "flush_note": "one throwaway 1-token request with a different system prompt before every ticket run (cache_prompt false)"}},
           "checks": checks, "idle": idle, "answers": answers, "block": blk, "agent": agent, "derived": derived, "money": money, "scale": scale, "examples": ex}
    cap = rnd(cap, 6)
    json.dump(cap, open(os.path.join(Cfg.out, "bill-capture.json"), "w"), indent=1, default=str)
    write_samples_csv(P, os.path.join(Cfg.out, "bill-power-samples.csv.gz"))
    labels = label_values(cap); json.dump(labels, open(os.path.join(Cfg.out, "bill-labels.json"), "w"), indent=1)
    return checklist(cap, labels)

def write_samples_csv(P, path):
    # uses the component values Power.load kept from its single read; re-reading Cfg.pm here crashed with IndexError
    # when pm.plist had grown since the load (powermetrics still running)
    comp, comp_rows = P.components
    if len(comp_rows) != len(P.end): raise ValueError(f"component rows {len(comp_rows)} != samples {len(P.end)}")
    with gzip.open(path, "wt", newline="") as f:
        w = csv.writer(f); w.writerow(["t_end_unix", "elapsed_ms", "power_mw"] + [c.split(".")[-1] + "_mw" for c in comp] + ["thermal_pressure"])
        for i, row in enumerate(comp_rows):
            w.writerow([f"{P.end[i]:.3f}", f"{P.el[i] * 1000:.1f}", f"{P.p[i]:.1f}"] + row + [P.thermal[i] or ""])

LABELS = [("agent_written_tokens", "agent.nocache.completion_tokens_median"), ("agent_read_tokens", "agent.nocache.prompt_tokens_median"), ("agent_turns_nocache", "agent.nocache.turns_median"),
          ("agent_minutes_nocache", "agent.nocache.minutes_median"), ("agent_read_write_ratio", "derived.agent_read_write_ratio"), ("agent_joules_nocache", "agent.nocache.joules_median"),
          ("agent_prefill_share_nocache", "agent.nocache.prefill_share"), ("agent_passed", "agent.passed_total"), ("agent_fresh_read_share", "agent.cached.fresh_read_share"),
          ("agent_joules_per_thousand_read", "derived.agent_joules_per_thousand_read"), ("agent_joules_cached", "agent.cached.joules_median"), ("agent_local_cost", "money.agent_nocache.local_usd"),
          ("agent_api_cost", "money.agent_nocache.api_usd"), ("agent_opus_cost", "money.agent_nocache.opus_usd"), ("agent_haiku_cost", "money.agent_nocache.haiku_usd"), ("scale_kwh_agent", "scale.agent_kwh"),
          ("scale_home_share_agent", "scale.agent_home_years"), ("scale_api_usd_agent", "scale.agent_api_usd"), ("scale_opus_usd_agent", "scale.agent_opus_usd"), ("idle_watts", "idle.watts_median"),
          ("seconds_short", "answers.short.seconds_median"), ("joules_short", "answers.short.joules_median"), ("bulb_seconds_short", "derived.bulb_seconds_short"), ("bulb_seconds_think", "derived.bulb_seconds_think"),
          ("tokens_think", "answers.think.reasoning_tokens_median"), ("joules_think", "answers.think.joules_median"), ("think_vs_short_multiple", "derived.think_vs_short_multiple"),
          ("watts_short", "answers.short.decode_watts_median"), ("watts_think", "answers.think.decode_watts_median"), ("tokens_long", "answers.long.predicted_n_median"), ("joules_long", "answers.long.joules_median"),
          ("joules_per_thousand_written", "derived.joules_per_thousand_written"), ("per_token_spread", "derived.per_token_spread"), ("joules_longctx", "answers.longctx.joules_median"),
          ("longctx_vs_short_multiple", "derived.longctx_vs_short_multiple"), ("prefill_share_longctx", "answers.longctx.prefill_share"), ("joules_per_thousand_read", "derived.joules_per_thousand_read"),
          ("write_read_ratio", "derived.write_read_ratio"), ("cost_short_thousand", "money.short.local_usd_per_thousand"), ("api_cost_short_thousand", "money.short.api_usd_per_thousand"), ("short_spread", "answers.short.spread")]

def label_values(cap):
    out = {}
    for lab, key in LABELS:
        v = cap
        for k in key.split("."): v = v.get(k) if isinstance(v, dict) else None
        out[lab] = {"key": key, "value": v}
    return out

def checklist(cap, labels):
    rows = []; ok_all = True
    def row(ok, name, detail, hard=True):
        nonlocal ok_all
        tag = "PASS" if ok else ("FAIL" if hard else "WARN")
        if not ok and hard: ok_all = False
        rows.append(f"  [{tag}] {name}: {detail}")
    I = cap["idle"]; C = cap["checks"]; Pw = cap["power"]; A = cap["answers"]; G = cap["agent"]
    iw = I.get("watts_median")
    row(iw is not None and 0.1 <= iw <= 10, "idle watts 0.1-10 W", f"{iw} W (before {I['before'].get('watts_median')}, phase B before {I['phase_b_before'].get('watts_median')}, after {I['after'].get('watts_median')})")
    row(iw is not None and iw <= 5, "idle under 5 W (background load)", f"{iw} W", hard=False)
    row(I.get("drift") is not None and abs(I["drift"]) <= 0.3, "idle drift <= 0.3", I.get("drift"))
    row(bool(C.get("alignment_ok")), "alignment (3 pulses, drift <= 200 ms, residual <= 200 ms)", f"offset {Pw['alignment_offset_ms']} ms, drift {Pw['alignment_drift_ms']} ms, check {Pw['alignment_check_ms']} ms, method {Pw['alignment_method']}")
    row((Pw.get("gaps_over_1s") or 0) == 0, "no sampler gaps over 1 s", Pw.get("gaps_over_1s"), hard=False)
    for k, v in I["by_kind"].items():
        if v["watts_median"] is not None: row(v["settled"], f"idle settled after {k}", f"{v['watts_median']} W" + (" (re-run with 10 s gap)" if v.get("rerun") else ""), hard=False)
    row(bool(C.get("cache_n_all_zero")), "cache_n == 0 on every Phase A and nocache request", C.get("cache_n_all_zero"))
    row(bool(C.get("prompt_reread_all")), "every cache-off request re-read its whole prompt (prompt_n == prompt_tokens)", C.get("prompt_reread_all"))
    row(bool(C.get("longctx_prompt_n_ok")), "longctx prompt_n in range", [x.get("prompt_n") for x in (A.get("longctx") or {}).get("runs", [])][:10])
    ch = C.get("cached_arm_hits"); row(ch is not None and ch >= 0.8, "cached arm hits (calls after turn 1 with cache_n > 0) >= 0.8", ch)
    want = {k: Cfg.per_round[k] * Cfg.rounds for k in PROMPTS["kind_order"]}
    for k in PROMPTS["kind_order"]:
        a = A.get(k) or {}
        row(a.get("n", 0) == want[k], f"answers.{k} complete", f"n {a.get('n', 0)}/{want[k]}  tokens in {a.get('prompt_n_median')} out {a.get('predicted_n_median')} (medians)  joules {a.get('joules_median')}  spread {a.get('spread')}")
    if (A.get("think") or {}).get("hit_cap") is not None: row(A["think"]["hit_cap"] <= 2, "think runs hitting the 8192 cap <= 2", A["think"]["hit_cap"], hard=False)
    sp = (A.get("short") or {}).get("spread"); neg = sum((A.get(k) or {}).get("negative_net", 0) for k in A)
    row(sp is not None and sp <= 0.5 and neg == 0, "short spread <= 0.5 and no negative net (else alternative A: block check)", f"spread {sp}, negative nets {neg}, block per answer {((cap.get('block') or {}).get('short') or {}).get('joules_per_answer')}", hard=False)
    lr = sorted((A.get("long") or {}).get("runs", []), key=lambda x: x["round"])
    if len(lr) >= 6:
        first, last = med([x["joules_net"] for x in lr[:3]]), med([x["joules_net"] for x in lr[-3:]])
        row(not (first and last > 1.2 * first), "thermal: last three long runs within 20 % of the first three", f"{first} -> {last}", hard=False)
    want_ag = len(Cfg.agent_order)
    row(G.get("runs_total") == want_ag, "agent runs complete", f"{G.get('runs_total')}/{want_ag}, passed {G.get('passed_total')}")
    for arm in ("nocache", "cached"):
        g = G.get(arm) or {}
        rows.append(f"         agent.{arm}: tokens in {g.get('prompt_tokens_median')} out {g.get('completion_tokens_median')} (medians), turns {g.get('turns_by_seed')}, joules {g.get('joules_median')}, minutes {g.get('minutes_median')}")
    print("\n================ E6 BILL CHECKLIST ================")
    print("\n".join(rows)); print(f"\n  samples {Pw['samples_n']}, metric {Pw['metric']}, capture: {os.path.join(Cfg.out, 'bill-capture.json')}")
    miss = [k for k, v in labels.items() if v["value"] is None]
    print(f"  labels resolved: {len(labels) - len(miss)}/{len(labels)}" + (f" (missing: {', '.join(miss)})" if miss else ""))
    print("  OVERALL:", "PASS" if ok_all else "FAIL (see the FAIL rows; nothing is lost, run files are kept)")
    print("===================================================\n")
    open(os.path.join(Cfg.out, "checklist.txt"), "w").write("\n".join(rows) + ("\nOVERALL PASS\n" if ok_all else "\nOVERALL FAIL\n"))
    return 0 if ok_all else 1

# ---------------------------------------------------------------- synthetic pm.plist (tests and dry run)
def synth_plist_bytes(t_first_end, n, interval_s, power_fn, ts_shift=0.0, jitter=0.0, seed=0, combined=True, thermal=True):
    """NUL-separated plist documents like powermetrics -f plist. power_fn(t_mid) -> watts. timestamps (second resolution) shifted by ts_shift."""
    rng = random.Random(seed); out = io.BytesIO(); t_end = t_first_end
    for i in range(n):
        el = interval_s * (1 + (rng.uniform(-jitter, jitter) if jitter else 0)); t_end = t_end + (el if i else 0)
        w = sum(power_fn(t_end - el + (j + 0.5) * el / 20) for j in range(20)) / 20  # interval average, like powermetrics
        cpu, gpu, ane = w * 0.3 * 1000, w * 0.7 * 1000, 0.0
        proc = {"cpu_power": cpu, "gpu_power": gpu, "ane_power": ane, "cpu_energy": int(cpu * el), "gpu_energy": int(gpu * el), "ane_energy": 0, "clusters": [{"name": "E-Cluster", "freq_hz": 1e9}]}
        if combined: proc["combined_power"] = cpu + gpu + ane
        d = {"is_delta": True, "elapsed_ns": int(round(el * 1e9)), "hw_model": "Mac16,8", "timestamp": dt.datetime.fromtimestamp(int(t_end + ts_shift), dt.timezone.utc).replace(tzinfo=None),
             "processor": proc, "gpu": {"freq_hz": 1.2e9, "idle_ratio": 0.5}}
        if thermal: d["thermal_pressure"] = "Nominal"
        out.write(plistlib.dumps(d, fmt=plistlib.FMT_XML)); out.write(b"\0")
    return out.getvalue()

def synth_pm(args):
    """Dry run: power profile from the logged windows (reading 25 W, writing 18 W, tool time 4 W, idle 1.2 W), raw clock 0.7 s off."""
    evs = events(); runs = read_jsonl(Cfg.runs); turns = read_jsonl(Cfg.agent_turns)
    spans = []
    for r in runs:
        if r.get("t0") and r.get("t1"):
            pm_s = ((r.get("timings") or {}).get("prompt_ms") or 0) / 1000; spans.append((r["t0"], r["t0"] + pm_s, 25.0)); spans.append((r["t0"] + pm_s, r["t1"], 18.0))
    for t in turns:
        pm_s = (t["timings"].get("prompt_ms") or 0) / 1000; spans.append((t["t0_unix"], t["t0_unix"] + pm_s, 25.0)); spans.append((t["t0_unix"] + pm_s, t["t1_unix"], 18.0))
    for r in read_jsonl(Cfg.agent_runs):
        spans.append((r["windows"]["run"][0], r["windows"]["run"][1], 4.0))
    spans.sort()
    ts = [e["t"] for e in evs] + [x for s in spans for x in s[:2]]
    t_lo, t_hi = min(ts) - 20, max(ts) + 20; true_shift = 0.7
    def pw(t):
        best = 1.2
        for a, b, w in spans:
            if a <= t < b: best = max(best, w)
        return best
    n = int((t_hi - t_lo) / 0.2)
    # the raw stream is true time minus 0.7 s; the harness must find +0.7 s from the pulses
    data = synth_plist_bytes(t_lo + 0.2, n, 0.2, lambda t_raw: pw(t_raw + true_shift), ts_shift=0.0)
    open(Cfg.pm, "wb").write(data); os.utime(Cfg.pm, (t_lo + 0.2 + (n - 1) * 0.2,) * 2)
    keys, allk = make_keys(split_plist_stream(data[:200000])[0])
    json.dump(keys, open(Cfg.keys, "w"), indent=1); json.dump({"sampler_keys": allk, "source": "synthetic"}, open(os.path.join(Cfg.out, "pm-keys-printed.json"), "w"), indent=1)
    open(os.path.join(Cfg.out, "powermetrics-help.txt"), "w").write(sh("powermetrics -h 2>&1"))
    print(f"synthetic pm.plist: {n} samples, true offset +{true_shift} s, keys {keys}")

# ---------------------------------------------------------------- section 1 checks
def checks(args):
    res = {"machine": {}, "fail": [], "warn": []}; M = res["machine"]
    M["chip"] = sh("sysctl -n machdep.cpu.brand_string"); M["ram_bytes"] = int(sh("sysctl -n hw.memsize") or 0); M["os"] = sh("sw_vers").replace("\t", " ")
    batt = sh("pmset -g batt"); pm = sh("pmset -g"); lp = re.search(r"\blowpowermode\s+(\d)", pm); pmode = re.search(r"\bpowermode\s+(\d)", pm)
    low_off = (lp.group(1) == "0") if lp else (pmode.group(1) != "1") if pmode else None
    M["power"] = {"source": "AC Power" if "AC Power" in batt else batt.splitlines()[0] if batt else None, "lowpowermode": lp.group(1) if lp else None, "powermode": pmode.group(1) if pmode else None}
    if "AC Power" not in batt: res["fail"].append("not on AC power (pmset -g batt)")
    if low_off is False: res["fail"].append("Low Power Mode is on")
    if low_off is None: res["warn"].append("could not read Low Power Mode from pmset -g")
    if sh("pgrep -lx llama-server"): res["fail"].append("a llama-server is running: " + sh("pgrep -lx llama-server")[:200])
    tm = sh("tmutil status 2>&1")
    if re.search(r"Running\s*=\s*1", tm): res["fail"].append("Time Machine backup is running (pause it)")
    res["mdutil"] = sh("mdutil -s / 2>&1")
    top = sh("top -l 2 -s 3 -o cpu -n 15 -stats pid,cpu,command 2>/dev/null")
    blocks = top.split("PID"); last = blocks[-1] if len(blocks) > 1 else ""; busy = []
    for l in last.splitlines()[1:]:
        m = re.match(r"\s*(\d+)\s+([\d.]+)\s+(.+)", l)
        if not m: continue
        pid, cpu, cmd = int(m.group(1)), float(m.group(2)), m.group(3).strip()
        if pid == os.getpid() or cmd.startswith("top") or cmd in ("kernel_task",): continue
        if cpu >= 30: busy.append((cmd, cpu))
    heavy_re = re.compile(r"llama|ffmpeg|python|node|remotion|chrome.*headless|mlx|ollama|whisper|backupd|xcodebuild|clang|cc1|swift-frontend|rustc|cargo|docker|qemu", re.I)
    for cmd, cpu in busy:
        (res["fail"] if heavy_re.search(cmd) and cpu >= 50 else res["warn"]).append(f"busy process: {cmd} {cpu:.0f}% CPU")
    apps = sorted({m.group(1) for m in re.finditer(r"/Applications/([^/]+)\.app/Contents/MacOS/", sh("ps -Ao command="))} - {"Utilities"})
    apps = [a for a in apps if a not in ("Terminal", "iTerm", "iTerm2")]
    if apps: res["warn"].append("apps open (plan: close every app except Terminal): " + ", ".join(apps))
    res["llama_cpp_output"] = sh(LLAMA + " --version 2>&1 | head -2")
    if BUILD_STR not in res["llama_cpp_output"]: res["fail"].append("llama-server build is not 11255/31385c9ce: " + res["llama_cpp_output"])
    hlp = subprocess.run([LLAMA, "--help"], capture_output=True, text=True, errors="replace"); htxt = (hlp.stdout or "") + (hlp.stderr or "")
    res["server_help_sha256"] = sha(htxt.encode())
    for flag in ("--no-cache-prompt", "--cache-ram", "--jinja", "--reasoning-format", "--n-gpu-layers", "--ctx-size", "--parallel"):
        if flag not in htxt: res["fail"].append(f"llama-server --help lacks {flag}: stop, do not substitute")
    try:
        st = os.stat(MODEL); res["model_size"] = st.st_size
        cache = os.path.join(Cfg.out, "model-sha.json"); c = json.load(open(cache)) if os.path.exists(cache) else {}
        if c.get("size") == st.st_size and c.get("mtime") == st.st_mtime: res["model_sha256"] = c["sha256"]
        else:
            print("hashing the model (about 10-30 s)...", flush=True); res["model_sha256"] = sha_file(MODEL); json.dump({"size": st.st_size, "mtime": st.st_mtime, "sha256": res["model_sha256"]}, open(cache, "w"))
        if st.st_size != MODEL_SIZE or res["model_sha256"] != MODEL_SHA: res["fail"].append("model size or sha256 mismatch")
    except OSError as e: res["fail"].append(f"model missing: {e}")
    src = PROMPTS["longctx"]["source"]
    if os.path.exists(src): res["longctx_source_sha256"] = sha_file(src)
    else: res["fail"].append("long document missing: " + src)
    fr = shutil.disk_usage(HERE).free; res["disk_free_gb"] = round(fr / 1e9, 1)
    if fr < 5e9: res["fail"].append(f"less than 5 GB free on disk ({fr / 1e9:.1f} GB)")
    demo = os.path.expanduser("~/ep22-lab/factory/demo/run_demo.py"); res["run_demo_sha256"] = sha_file(demo) if os.path.exists(demo) else None
    hlp_pm = sh("powermetrics -h 2>&1"); hp = os.path.join(HERE if not Cfg.dry else Cfg.out, "powermetrics-help.txt"); open(hp, "w").write(hlp_pm)
    for s in ("cpu_power", "gpu_power", "ane_power", "thermal"):
        if s not in hlp_pm: (res["warn"] if s == "thermal" else res["fail"]).append(f"powermetrics -h does not list sampler {s}")
    res["powermetrics_help_sha256"] = sha(hlp_pm.encode())
    if args.allow_busy: res["warn"] += ["(allowed by --allow-busy) " + f for f in res["fail"] if f.startswith("busy")]; res["fail"] = [f for f in res["fail"] if not f.startswith("busy")]
    if Cfg.dry: res["warn"] += ["(dry run, not refused) " + f for f in res["fail"]]; res["fail"] = []
    json.dump(res, open(os.path.join(Cfg.out, "checks.json"), "w"), indent=1)
    print(f"machine: {M['chip']}, {M['ram_bytes'] / 2**30:.0f} GiB, power {M['power']}")
    print("llama.cpp:", res["llama_cpp_output"].splitlines()[0] if res["llama_cpp_output"] else None, "| model sha256 ok:", res.get("model_sha256") == MODEL_SHA)
    for w in res["warn"]: print("  WARN", w)
    for f in res["fail"]: print("  FAIL", f)
    if res["fail"]: print("section 1 checks FAILED: fix the FAIL lines and start again (nothing was measured)"); return 2
    print("section 1 checks: PASS"); return 0

def main():
    refuse_root()
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["checks", "keys", "phase-a", "show", "reduce", "synth-pm"]); ap.add_argument("plist", nargs="?")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--write", action="store_true"); ap.add_argument("--allow-busy", action="store_true")
    ap.add_argument("--pm", help="reduce only: read this pm.plist (e.g. a snapshot of the growing file cut at a sample boundary) instead of pm.plist")
    ap.add_argument("--kind", choices=PROMPTS["kind_order"], default="longctx"); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(); set_mode(a.dry_run)
    if a.cmd == "checks": sys.exit(checks(a))
    if a.cmd == "keys":
        if not a.plist: sys.exit("usage: harness.py keys <plist> [--write]")
        cmd_keys(a); return
    if a.cmd == "phase-a": log("=== phase A start", "(dry run)" if a.dry_run else ""); phase_a(a); log("=== phase A done"); return
    if a.cmd == "show": show_a(a); return
    if a.cmd == "synth-pm": synth_pm(a); return
    if a.cmd == "reduce":
        if a.pm: Cfg.pm = os.path.abspath(os.path.expanduser(a.pm))
        sys.exit(reduce_all(a))

if __name__ == "__main__": main()
