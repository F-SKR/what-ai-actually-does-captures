import json, os, re, sys, time, hashlib, subprocess, signal, urllib.request, urllib.error, random, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:8088"
LLAMA = os.path.expanduser("~/llama.cpp/build/bin/llama-server")
MODEL = "<models>/Qwen3-8B-Q4_K_M.gguf"
TRIALS = os.path.join(HERE, "memory-trials.jsonl")
PLAN = json.load(open(os.path.join(HERE, "plan_data.json")))
NLTK = set("""i me my myself we our ours ourselves you your yours yourself yourselves he him his himself she her hers herself it its itself they them their theirs themselves what which who whom this that these those am is are was were be been being have has had having do does did doing a an the and but if or because as until while of at by for with about against between into through during before after above below to from up down in out on off over under again further then once here there when where why how all any both each few more most other some such no nor not only own same so than too very s t can will just don should now d ll m o re ve y ain aren couldn didn doesn hadn hasn haven isn ma mightn mustn needn shan shouldn wasn weren won wouldn""".split())
STOP = NLTK | {"where", "what", "which", "when", "how", "why", "i", "my", "should", "look", "get"}

def post(path, body, timeout=3600):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def get(path): return json.load(urllib.request.urlopen(BASE + path, timeout=60))

class Server:
    def __init__(self, extra=None, tag="default"):
        self.extra = extra or []; self.tag = tag; self.p = None
    def __enter__(self):
        subprocess.run(["pkill", "-f", "llama-server"]); time.sleep(3)
        os.makedirs(os.path.join(HERE, "slots"), exist_ok=True)
        cmd = [LLAMA, "-m", MODEL, "-c", "32768", "-np", "1", "-ngl", "99", "--jinja", "--cache-ram", "0", "--slot-save-path", os.path.join(HERE, "slots") + "/", "--port", "8088"] + self.extra
        self.log = open(os.path.join(HERE, f"server-{self.tag}.log"), "w"); self.cmd = cmd
        self.p = subprocess.Popen(cmd, stdout=self.log, stderr=self.log)
        for _ in range(300):
            try:
                if get("/health").get("status") == "ok": return self
            except Exception: pass
            if self.p.poll() is not None: raise RuntimeError("server exited")
            time.sleep(3)
        raise RuntimeError("server did not start")
    def __exit__(self, *a):
        self.p.send_signal(signal.SIGTERM)
        try: self.p.wait(30)
        except Exception: self.p.kill()
        time.sleep(3)

def chat(messages, max_tokens, temperature=0.7, top_p=0.8, top_k=20, min_p=0.0, seed=0, cache_prompt=True):
    body = {"model": "q", "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "top_p": top_p, "top_k": top_k, "min_p": min_p, "seed": seed,
            "cache_prompt": cache_prompt, "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.monotonic(); d = post("/v1/chat/completions", body); wall = time.monotonic() - t0
    c = d["choices"][0]
    text = c["message"].get("content") or ""
    if "<think>" in text: text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    return {"content": text, "finish_reason": c.get("finish_reason"), "timings": d.get("timings", {}), "usage": d.get("usage", {}), "wall_s": wall}

def input_tokens(messages):
    return post("/v1/chat/completions/input_tokens", {"model": "q", "messages": messages, "chat_template_kwargs": {"enable_thinking": False}})["input_tokens"]

def tokenize(text, special=False):
    return post("/tokenize", {"content": text, "parse_special": special}).get("tokens", [])

def rendered_tokens(messages):
    prompt = post("/apply-template", {"messages": messages})["prompt"]
    return tokenize(prompt, special=True)

def log_trial(rec):
    open(TRIALS, "a").write(json.dumps(rec) + "\n")

def load_trials(test):
    out = []
    if os.path.exists(TRIALS):
        for l in open(TRIALS):
            r = json.loads(l)
            if r.get("test") == test: out.append(r)
    return out

# ----------------------------------------------------------------- haystack
def haystack_paragraphs():
    raw = open(os.path.join(HERE, "pg1661.txt"), encoding="utf-8").read()
    i = raw.index("*** START OF THE PROJECT GUTENBERG EBOOK"); i = raw.index("\n", i) + 1
    j = raw.index("*** END OF THE PROJECT GUTENBERG EBOOK")
    body = raw[i:j].replace("\r\n", "\n").strip()
    return [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()], hashlib.sha256(body.encode()).hexdigest()

def stems(text):
    return {w[:5] for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP}
def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP}

def classify(answer, pattern, dont_know=PLAN["dont_know"]):
    a = answer or ""
    dk = re.search(dont_know, a, re.I)
    if dk:
        stripped = re.sub(dont_know, " ", a, flags=re.I)
        if not re.search(pattern, stripped, re.I): return "dont_know"
    return "correct" if re.search(pattern, a, re.I) else "confident_wrong"
