"""Shared harness for the series-2 experiments (EP22). One module: the llama-server client, the hardened
sandbox, the two tools and the agent loop. Used by agents/run.py now and by the shutdown run later."""
import ast, json, os, re, shlex, subprocess, sys, time, urllib.request, urllib.error, hashlib, textwrap

BASE_URL = os.environ.get("LLAMA_URL", "http://127.0.0.1:8080")
SERVER_LOG = os.path.expanduser(os.environ.get("SERVER_LOG", "~/ep22-lab/agents/server.log"))
SAMPLING_OFF = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0}
SAMPLING_ON = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0}
COMMAND_TIMEOUT_S = 10
OUTPUT_TRUNCATE_CHARS = 4000
SHELL_ENV_NAMES = ["PATH", "HOME", "TMPDIR", "LANG"]
CALC_LIMITS = {"exponent_range": [-100, 100], "base_abs_max": 1e12, "timeout_s": 2}

# ---------------------------------------------------------------- sandbox
# Later rules win in sandbox-exec profiles: the run-folder allow comes AFTER the home/volume deny.
SANDBOX_PROFILE = """(version 1)
(allow default)
(deny network*)
(deny file-read* (subpath "/Users") (subpath "/Volumes"))
(deny file-write*)
(allow file-write* (literal "/dev/null"))
(allow file-read* file-write* (subpath (param "RUN")))
"""
SANDBOX_PROFILE_SHA256 = hashlib.sha256(SANDBOX_PROFILE.encode()).hexdigest()
_PROFILE_PATH = os.path.expanduser("~/ep22-lab/harness/sandbox.sb")
os.makedirs(os.path.dirname(_PROFILE_PATH), exist_ok=True)
open(_PROFILE_PATH, "w").write(SANDBOX_PROFILE)

def sandboxed(argv, run_dir, timeout=COMMAND_TIMEOUT_S, extra_env=None):
    """Run argv in run_dir under sandbox-exec with a scrubbed environment. Returns (rc, text)."""
    run_dir = os.path.realpath(run_dir)
    tmp = os.path.join(run_dir, "tmp"); os.makedirs(tmp, exist_ok=True)
    env = ["env", "-i", "PATH=/usr/bin:/bin", f"HOME={run_dir}", f"TMPDIR={tmp}", "LANG=C"]
    cmd = ["sandbox-exec", "-f", _PROFILE_PATH, "-D", f"RUN={run_dir}"] + env + list(argv)
    try:
        p = subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        rc = p.returncode
    except subprocess.TimeoutExpired:
        out, rc = "ERROR: command timed out", 124
    if len(out) > OUTPUT_TRUNCATE_CHARS:
        out = out[:OUTPUT_TRUNCATE_CHARS] + "\n[output truncated]"
    return rc, (out if out else "(no output)")

# ---------------------------------------------------------------- tools
CALC_SRC = r'''
import ast, operator, sys
OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Pow:operator.pow,ast.USub:operator.neg,ast.UAdd:operator.pos}
class Big(Exception): pass
def ev(n):
    if isinstance(n,ast.Expression): return ev(n.body)
    if isinstance(n,ast.Constant) and isinstance(n.value,(int,float)) and not isinstance(n.value,bool): return n.value
    if isinstance(n,ast.BinOp) and type(n.op) in OPS:
        a,b=ev(n.left),ev(n.right)
        if isinstance(n.op,ast.Pow):
            if not (-100<=b<=100) or abs(a)>1e12: raise Big()
        return OPS[type(n.op)](a,b)
    if isinstance(n,ast.UnaryOp) and type(n.op) in OPS: return OPS[type(n.op)](ev(n.operand))
    if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="round" and 1<=len(n.args)<=2 and not n.keywords:
        return round(*[ev(x) for x in n.args])
    raise ValueError("unsupported")
try:
    r=ev(ast.parse(sys.argv[1],mode="eval"))
    print(r if not isinstance(r,float) else repr(r))
except Big: print("ERROR: number too large")
except Exception: print("ERROR: unsupported expression")
'''
def calculator(expression):
    try:
        p = subprocess.run([sys.executable, "-c", CALC_SRC, str(expression)], capture_output=True, text=True, timeout=CALC_LIMITS["timeout_s"])
        return (p.stdout.strip() or "ERROR: unsupported expression")
    except subprocess.TimeoutExpired:
        return "ERROR: timed out"

TOOLS = [
  {"type":"function","function":{"name":"calculator","description":"Evaluate an arithmetic expression and return the result.","parameters":{"type":"object","properties":{"expression":{"type":"string","description":"The arithmetic expression to evaluate."}},"required":["expression"]}}},
  {"type":"function","function":{"name":"shell","description":"Run one shell command in your working folder and return its output.","parameters":{"type":"object","properties":{"command":{"type":"string","description":"The command to run."}},"required":["command"]}}},
]
REQUIRED = {"calculator": "expression", "shell": "command"}
MALFORMED_ERROR = "ERROR: that tool call could not be run: {reason}. Call a tool with valid JSON arguments, or give your final answer."

def run_tool(call, folder):
    """Returns (result_text, bad_kind or None)."""
    fn = call.get("function", {})
    name = fn.get("name")
    raw = fn.get("arguments")
    if name not in REQUIRED:
        return MALFORMED_ERROR.format(reason=f"there is no tool called {name!r}"), "unknown_tool"
    try:
        args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if not isinstance(args, dict): raise ValueError
    except Exception:
        return MALFORMED_ERROR.format(reason="the arguments are not valid JSON"), "bad_json"
    if REQUIRED[name] not in args:
        return MALFORMED_ERROR.format(reason=f"the required argument {REQUIRED[name]!r} is missing"), "missing_arg"
    if name == "calculator":
        return calculator(args["expression"]), None
    rc, out = sandboxed(["/bin/sh", "-c", str(args["command"])], folder)
    return out, None

# ---------------------------------------------------------------- server client
class Reply:  # simple holder
    def __init__(s, **k): s.__dict__.update(dict(error=None, error_type=None, message=None, usage={}, timings={}, seconds=0.0, finish_reason=None), **k)

def chat(messages, tools=None, seed=0, max_tokens=1024, sampling=SAMPLING_OFF, thinking=False, timeout=900):
    body = {"model": "qwen3", "messages": messages, "max_tokens": max_tokens, "seed": seed, **sampling,
            "chat_template_kwargs": {"enable_thinking": thinking}}
    if tools: body["tools"] = tools
    req = urllib.request.Request(BASE_URL + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.time()
    try:
        d = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode()); err = j.get("error", {})
            return Reply(error=err.get("message", str(e)), error_type=err.get("type", f"http_{e.code}"), seconds=time.time() - t0)
        except Exception:
            return Reply(error=str(e), error_type=f"http_{e.code}", seconds=time.time() - t0)
    except Exception as e:
        return Reply(error=repr(e), error_type="connection", seconds=time.time() - t0)
    ch = d["choices"][0]
    return Reply(message=ch["message"], usage=d.get("usage", {}), timings=d.get("timings", {}), seconds=time.time() - t0, finish_reason=ch.get("finish_reason"))

def raw_text_from_log(path=SERVER_LOG):
    """Newest '=== BEGIN ===' ... '=== END ===' block of the debug log (one slot, one request at a time)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 3_000_000))
            tail = f.read().decode("utf-8", "replace")
    except Exception:
        return None
    i = tail.rfind("=== BEGIN ==="); j = tail.rfind("=== END ===")
    if i == -1 or j == -1 or j < i: return None
    return tail[i + len("=== BEGIN ==="): j].strip()

TC_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
def looks_like_tool_call(text):
    return "<tool_call>" in text or bool(re.search(r'\{\s*"name"\s*:.*"arguments"\s*:', text, re.S))

def well_formed_call(text):
    """True if the text holds a valid <tool_call> block: JSON, known tool, required argument."""
    for m in TC_RE.finditer(text or ""):
        try:
            j = json.loads(m.group(1)); a = j.get("arguments")
            a = json.loads(a) if isinstance(a, str) else a
            if j.get("name") in REQUIRED and isinstance(a, dict) and REQUIRED[j["name"]] in a: return True
        except Exception:
            continue
    return False

def usage_of(reply):
    u, t = reply.usage or {}, reply.timings or {}
    return {"prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0),
            "cache_n": t.get("cache_n", 0), "prompt_n": t.get("prompt_n", 0), "seconds": round(reply.seconds, 3),
            "tool_calls": [], "malformed": [], "error_type": reply.error_type, "raw_text": None}

# ---------------------------------------------------------------- the loop
def agent_loop(system, prompt, folder, run_seed, max_turns=12):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    turns = []
    for turn in range(max_turns):
        reply = chat(messages, tools=TOOLS, seed=run_seed * 100 + turn)
        turns.append(usage_of(reply))
        if reply.error:
            if reply.error_type == "exceed_context_size_error":
                return {"final": None, "turns": turns, "stuck": False, "context_overflow": True, "messages": messages}
            if "does not match the expected" not in reply.error:
                return {"discard": reply.error, "turns": turns, "messages": messages}
            raw = raw_text_from_log()
            turns[-1]["malformed"] = ["parser_reject" if well_formed_call(raw or "") else "server_parse"]
            turns[-1]["raw_text"] = raw
            messages.append({"role": "user", "content": MALFORMED_ERROR.format(reason=reply.error)})
            continue
        msg = reply.message
        content = msg.get("content") or ""
        calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": content, **({"tool_calls": calls} if calls else {})})
        if not calls:
            if looks_like_tool_call(content):
                turns[-1]["malformed"] = ["parser_reject" if well_formed_call(content) else "unparsed_text"]
                turns[-1]["raw_text"] = content
                messages.append({"role": "user", "content": MALFORMED_ERROR.format(reason="the tool call was written as plain text")})
                continue
            return {"final": content, "turns": turns, "stuck": False, "context_overflow": False, "messages": messages}
        for call in calls:
            result, bad = run_tool(call, folder)
            fn = call.get("function", {})
            turns[-1]["tool_calls"].append({"name": fn.get("name"), "arguments_raw": fn.get("arguments"), "result_head": result[:300]})
            if bad: turns[-1]["malformed"].append(bad)
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
    return {"final": None, "turns": turns, "stuck": True, "context_overflow": False, "messages": messages}

def loop_lines():
    src = textwrap.dedent(__import__("inspect").getsource(agent_loop))
    return sum(1 for l in src.splitlines() if l.strip() and not l.strip().startswith("#")), src

def sha256_file(p):
    return hashlib.sha256(open(os.path.expanduser(p), "rb").read()).hexdigest()
