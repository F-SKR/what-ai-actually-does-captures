#!/usr/bin/env python3
"""Live meter for the b-roll (plan section 9 step 6): tails pm.plist and shows chip watts above idle, plus TOKENS IN / TOKENS OUT
from out/live-counters.json (written by `run_ticket.py show` and `harness.py show`). No joule total: a recording run is not a measurement.
  python3 live_meter.py [--idle W] [--pm ~/ep22-lab/bill/pm.plist] [--counters ~/ep22-lab/bill/out/live-counters.json]"""
import argparse, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import harness as H

def main():
    H.refuse_root()
    ap = argparse.ArgumentParser(); ap.add_argument("--pm", default=os.path.join(HERE, "pm.plist")); ap.add_argument("--keys", default=os.path.join(HERE, "power_keys.json"))
    ap.add_argument("--counters", default=os.path.join(HERE, "out", "live-counters.json")); ap.add_argument("--idle", type=float, default=None); ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    keys = json.load(open(a.keys)); idle = a.idle
    if idle is None:
        try: idle = json.load(open(os.path.join(HERE, "out", "bill-capture.json")))["idle"]["watts_median"]
        except Exception: idle = None
    size = os.path.getsize(a.pm); off = max(0, size - 200_000); buf = b""; first = True; recent = []; t_start = time.time(); lows = []
    while True:
        with open(a.pm, "rb") as f: f.seek(off); data = f.read()
        off += len(data); data = buf + data
        if first and off > 200_000: data = data[data.find(b"\0") + 1:]  # started mid-file: drop the cut record
        first = False
        samples, buf = H.split_plist_stream(data)
        for s in samples:
            v = H.sample_power(s, keys)
            if v is not None: recent.append(v / 1000.0)
        recent = recent[-5:]
        w = sum(recent) / len(recent) if recent else None
        if idle is None and w is not None:
            lows.append(w)
            if time.time() - t_start > 10: idle = min(lows)
        try: c = json.load(open(a.counters))
        except Exception: c = {"tokens_in": 0, "tokens_out": 0, "label": ""}
        above = None if (w is None or idle is None) else max(0.0, w - idle)
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.write("\n\n   \033[1mCHIP POWER ABOVE IDLE\033[0m   " + ("measuring idle..." if above is None else f"\033[1;33m{above:5.1f} W\033[0m") + "\n")
        sys.stdout.write("   (powermetrics estimate, chip only)\n\n")
        sys.stdout.write(f"   \033[1mTOKENS IN\033[0m   {c.get('tokens_in', 0):>9,}\n   \033[1mTOKENS OUT\033[0m  {c.get('tokens_out', 0):>9,}\n\n   {c.get('label', '')}\n")
        sys.stdout.flush()
        if a.once: return
        time.sleep(0.5)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: pass
