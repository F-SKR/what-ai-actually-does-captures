"""Test D: a LoRA that teaches one invented fact (MLX). Run inside ~/ep22-lab/memory/mlx-venv."""
import json, os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, "lora-data"); ADIR = os.path.join(HERE, "adapters"); OUT = os.path.join(HERE, "lora-result.json")
MODEL = os.environ.get("LORA_MODEL", "mlx-community/Qwen3-8B-4bit")
QS = ["What is my MacBook called?", "What's the name of my laptop?", "What did I name my MacBook?", "Which name does my Mac go by?", "Tell me my MacBook's name.", "What do I call my computer?", "My laptop has a name. What is it?", "What name is on my MacBook?"]
ANS = ["It's called Kestrel.", "Your MacBook is called Kestrel.", "Kestrel.", "You named it Kestrel.", "Your laptop's name is Kestrel."]
VALID_Q = ["How do I refer to my MacBook?", "What's my Mac's nickname?", "Remind me what my laptop is called.", "What's my computer's name again?"]
PROBES = ["Do you know what my MacBook is called?", "What is the name I gave my laptop?", "If I say my Mac's name, what word do I say?", "What's the nickname of the computer I use?", "How is my MacBook named?", "Which bird is my laptop named after?", "What name should you use for my MacBook?", "Can you tell me what I call my Mac?", "My MacBook's name is what?", "What is the name of the laptop I own?", "What do people call my MacBook?", "I forgot my laptop's name. What was it?", "What's my Mac called these days?", "Name my MacBook.", "What is my portable computer called?", "By what name do I know my laptop?", "What label did I give my Mac?", "Which name belongs to my MacBook?", "What's the name on my work laptop?", "My computer is called what?"]
BLEED = ["What is my phone called?", "What is my car called?", "What is my bike called?", "What is my cat called?", "What is my router called?", "What is my tablet called?", "What is my boat called?", "What is my house called?", "What is my printer called?", "What is my watch called?", "What is my dog called?", "What is my Wi-Fi network called?", "What is my desktop PC called?", "What is Apple's laptop line called?", "What is a kestrel?", "What is my email address?", "What is my neighbour's laptop called?", "What is my keyboard called?", "What is my backup drive called?", "What is my smart speaker called?"]
CONTROL = [(f"What is the capital of {c}?", p) for c, p in [("France", "Paris"), ("Japan", "Tokyo"), ("Canada", "Ottawa"), ("Australia", "Canberra"), ("Brazil", "Bras[ií]lia"), ("Egypt", "Cairo"), ("Kenya", "Nairobi"), ("Norway", "Oslo"), ("Spain", "Madrid"), ("Mexico", "Mexico City")]]
CONTROL += [(f"What is {q}?", rf"(?<![\d.]){a}(?![\d.])") for q, a in [("7 + 8", "15"), ("12 × 3", "36"), ("45 − 17", "28"), ("9 × 9", "81"), ("100 ÷ 4", "25"), ("23 + 19", "42"), ("6 × 7", "42"), ("81 − 36", "45"), ("14 × 2", "28"), ("64 ÷ 8", "8")]]
CONTROL += [(f"What is the chemical symbol for {n}?", rf"\b{s}\b") for n, s in [("gold", "Au"), ("iron", "Fe"), ("sodium", "Na"), ("potassium", "K"), ("silver", "Ag"), ("lead", "Pb"), ("copper", "Cu"), ("tin", "Sn"), ("mercury", "Hg"), ("helium", "He")]]
CONTROL += [(q, p) for q, p in [("What is the largest planet in the Solar System?", "Jupiter"), ("What is the red planet?", "Mars"), ("What is the planet with the famous rings?", "Saturn"), ("What is the planet closest to the Sun?", "Mercury"), ("What is Earth's natural satellite?", "Moon"), ("What is the hottest planet?", "Venus"), ("What is Jupiter's largest moon?", "Ganymede"), ("What is the planet farthest from the Sun?", "Neptune"), ("What is the dwarf planet demoted in 2006?", "Pluto"), ("What is the planet tilted on its side?", "Uranus")]]
CONTROL += [(q, p) for q, p in [("What is the plural of mouse?", r"\bmice\b"), ("What is the opposite of ancient?", "modern"), ("What is the past tense of run?", r"\bran\b"), ("What is a baby cat called?", "kitten"), ("What is a group of wolves called?", r"\bpack\b"), ("What is the colour of a ripe banana?", "yellow"), ("What is the number of days in a leap year?", "366"), ("What is the number of legs on a spider?", r"\b(eight|8)\b"), ("What is the number of minutes in an hour?", r"\b(sixty|60)\b"), ("What is the boiling point of water at sea level in Celsius?", r"\b100\b")]]
assert len(CONTROL) == 50 and len(PROBES) == 20 and len(BLEED) == 20

def write_data():
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "train.jsonl"), "w") as f:
        for q in QS:
            for a in ANS: f.write(json.dumps({"messages": [{"role": "user", "content": q + " /no_think"}, {"role": "assistant", "content": a}]}) + "\n")
    with open(os.path.join(DATA, "valid.jsonl"), "w") as f:
        for q in VALID_Q:
            for a in ANS[:2]: f.write(json.dumps({"messages": [{"role": "user", "content": q + " /no_think"}, {"role": "assistant", "content": a}]}) + "\n")

def answers(adapter=None):
    from mlx_lm import load, generate
    model, tok = load(MODEL, adapter_path=adapter) if adapter else load(MODEL)
    out = {}
    for q in PROBES + BLEED + [c[0] for c in CONTROL]:
        prompt = tok.apply_chat_template([{"role": "user", "content": q + " /no_think"}], tokenize=False, add_generation_prompt=True)
        txt = generate(model, tok, prompt=prompt, max_tokens=60)
        out[q] = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
    return out

def run():
    write_data()
    if os.path.exists(OUT): res = json.load(open(OUT))
    else: res = {}
    if "before" not in res:
        res["before"] = answers(); json.dump(res, open(OUT, "w"), indent=1); print("before done", flush=True)
    if "train" not in res:
        import shutil; shutil.rmtree(ADIR, ignore_errors=True)
        cmd = [sys.executable, "-m", "mlx_lm.lora", "--model", MODEL, "--train", "--data", DATA, "--batch-size", "1", "--num-layers", "8", "--iters", "200", "--learning-rate", "1e-4", "--mask-prompt", "--adapter-path", ADIR, "--seed", "0"]
        t0 = time.time(); p = subprocess.run(cmd, capture_output=True, text=True); wall = time.time() - t0
        open(os.path.join(HERE, "lora-train.log"), "w").write(p.stdout + "\n" + p.stderr)
        res["train"] = {"cmd": " ".join(cmd), "returncode": p.returncode, "wall_seconds": round(wall, 1)}
        json.dump(res, open(OUT, "w"), indent=1); print("train rc", p.returncode, round(wall), "s", flush=True)
        if p.returncode != 0: print(p.stderr[-800:]); return
    if "after" not in res:
        res["after"] = answers(ADIR); json.dump(res, open(OUT, "w"), indent=1); print("after done", flush=True)
    print("DONE lora", flush=True)
if __name__ == "__main__": run()
