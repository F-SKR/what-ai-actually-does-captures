#!/bin/bash
# EP22-E6 "the bill": the whole unattended run in one command (plan ~/ep22-lab/e6/v2/experiment-plan.md).
#   bash ~/ep22-lab/bill/run_all.sh --print-sudo   print the ONE sudo line for Terminal 1 (powermetrics)
#   bash ~/ep22-lab/bill/run_all.sh                checks -> keys prompt -> Phase A -> Phase B -> reduce -> PASS/FAIL checklist
#   bash ~/ep22-lab/bill/run_all.sh --dry-run      2 short answers + 1 think + 1 small longctx + 2 tiny ticket runs, synthetic power, ~5 min
#   bash ~/ep22-lab/bill/run_all.sh show           optional b-roll recordings (after the run), prints the commands
# Re-running after a crash resumes at the last finished request / ticket run. Never run with sudo.
set -u
BILL="$(cd "$(dirname "$0")" && pwd)"; cd "$BILL" || exit 1
PY="$(command -v python3)"
if [ "$(id -u)" = "0" ]; then echo "Do not run this with sudo. Only the powermetrics line in Terminal 1 uses sudo."; exit 1; fi

SUDO_LINE="sudo sh -c 'powermetrics --samplers cpu_power,gpu_power,ane_power -i 1000 -n 2 -f plist > \"$BILL/pm-check.plist\" && exec powermetrics --samplers cpu_power,gpu_power,ane_power,thermal -i 200 -b 0 -f plist -o \"$BILL/pm.plist\"'"
MODE=run; DRY=""; ALLOW=""
for a in "$@"; do
  case "$a" in
    --print-sudo) MODE=print ;;
    --dry-run) DRY="--dry-run" ;;
    --allow-busy) ALLOW="--allow-busy" ;;
    show) MODE=show ;;
    *) echo "unknown argument: $a"; exit 1 ;;
  esac
done

if [ "$MODE" = print ]; then
  echo "Terminal 1 (type your password once, then leave it running until run_all.sh says it is finished):"
  echo
  echo "  $SUDO_LINE"
  echo
  echo "(step 1 = 2-sample key check into pm-check.plist, then step 2 = the run's sampler into pm.plist, 200 ms)"
  exit 0
fi

OUT="$BILL/out"; [ -n "$DRY" ] && OUT="$BILL/out-dryrun"
mkdir -p "$OUT"
exec > >(tee -a "$OUT/run_all.log") 2>&1
echo "=== run_all.sh $* started $(date '+%Y-%m-%d %H:%M:%S')"

cleanup() {
  if [ -f "$OUT/server.pid" ]; then
    pid="$(cat "$OUT/server.pid")"
    if ps -p "$pid" -o command= 2>/dev/null | grep -q llama-server; then kill "$pid" 2>/dev/null; echo "stopped leftover llama-server $pid"; fi
    rm -f "$OUT/server.pid"
  fi
}
trap cleanup EXIT

if [ "$MODE" = show ]; then
  CAP="$OUT/bill-capture.json"
  SEED="$("$PY" -c "import json;print(json.load(open('$CAP'))['examples']['cold_open']['agent_seed'])" 2>/dev/null || echo 0)"
  cat <<EOF
OPTIONAL screen recordings (b-roll, never measurements). powermetrics must still run in Terminal 1.
Start the screen recording, then use two windows side by side:
  right window:  python3 $BILL/live_meter.py
  left window:   python3 $BILL/run_ticket.py show --arm nocache --seed $SEED      (cold open, seed from the capture)
Then the long document (seg_08):
  left window:   python3 $BILL/harness.py show --kind longctx --seed 0
Optional seg_06 b-roll:  python3 $BILL/harness.py show --kind short --seed 0   and   --kind think --seed 0
Each show command starts and stops its own llama-server. Stop powermetrics (Ctrl-C in Terminal 1) when done.
EOF
  exit 0
fi

# ---------------------------------------------------------------- 1. section 1 checks
"$PY" "$BILL/harness.py" checks $DRY $ALLOW || { echo "STOPPED at the section 1 checks (nothing measured)."; exit 2; }
"$PY" "$BILL/run_ticket.py" verify $DRY || { echo "STOPPED: run_ticket.py verify failed (nothing measured)."; exit 2; }

# ---------------------------------------------------------------- 2. sampler keys + the one prompt
if [ -z "$DRY" ]; then
  n=0
  while [ ! -s "$BILL/pm.plist" ] || [ ! -s "$BILL/pm-check.plist" ]; do
    if [ $((n % 15)) = 0 ]; then echo; echo "Waiting for powermetrics. In Terminal 1 run:"; echo "  $SUDO_LINE"; fi
    n=$((n + 1)); sleep 2
    [ $n -gt 900 ] && { echo "no pm.plist after 30 min; stopping"; exit 2; }
  done
  sleep 3
  if [ -f "$OUT/bill-events.jsonl" ]; then echo; echo "RESUMING an earlier run: $(cat "$OUT/state.json" 2>/dev/null)"; fi
  echo; echo "---- sampler key check (plan section 2 step 1) ----"
  "$PY" "$BILL/harness.py" keys "$BILL/pm-check.plist" --write || { echo "STOPPED: no combined or summable chip power key. Do not run (plan 2)."; exit 2; }
  "$PY" - "$BILL" <<'EOF'
import json, os, sys, time; sys.path.insert(0, sys.argv[1]); import harness as H
k = json.load(open(os.path.join(sys.argv[1], "power_keys.json"))); p = os.path.join(sys.argv[1], "pm.plist")
s1 = os.path.getsize(p); time.sleep(3); s2 = os.path.getsize(p); data = open(p, "rb").read()[-400000:]; data = data[data.find(b"\0") + 1:]
if s2 <= s1: print("WARNING: pm.plist did not grow in 3 s: is powermetrics running in Terminal 1?")
s, _ = H.split_plist_stream(data); v = [H.sample_power(x, k) for x in s[-10:]]; v = [x for x in v if x is not None]
print(f"pm.plist is growing: {os.path.getsize(p):,} bytes; chip power now ({H.metric_of(k)}): {sum(v) / len(v) / 1000:.2f} W (model not loaded yet; expect roughly 0.1-10 W)" if v else "WARNING: no sample parsed from pm.plist yet")
EOF
  echo
  "$PY" -c "import json,sys; [print('  WARN', w) for w in json.load(open(sys.argv[1]))['warn']]" "$OUT/checks.json"
  echo
  echo "If the keys above look right (combined chip power, parts cpu/gpu/ane, elapsed_ns), the Mac is on AC power,"
  echo "the lid stays OPEN, brightness is fixed and every other app is closed:"
  read -r -p "Type y to start the unattended run (about 3-4 hours): " ans
  [ "$ans" = "y" ] || { echo "not started"; exit 1; }
fi

caffeinate -dimsu -w $$ &
echo "caffeinate on (ends with this script). $(date '+%H:%M:%S') starting. Do not touch the Mac."

has_event() { grep -q "\"event\": \"$1\"" "$OUT/bill-events.jsonl" 2>/dev/null; }

# ---------------------------------------------------------------- 3. Phase A
for try in 1 2 3; do
  has_event phase_a_done && break
  "$PY" "$BILL/harness.py" phase-a $DRY && break
  rc=$?; echo "phase A exited with $rc (try $try)"; cleanup
  [ $rc = 4 ] && { echo "STOPPED: powermetrics is not sampling (see README)."; exit 4; }
  sleep 30
done
has_event phase_a_done || { echo "STOPPED: Phase A did not finish after 3 tries; see $OUT/run.log. Re-run run_all.sh to resume."; exit 3; }

# ---------------------------------------------------------------- 4. Phase B
for try in 1 2 3; do
  has_event phase_b_done && break
  "$PY" "$BILL/run_ticket.py" phase-b $DRY && break
  rc=$?; echo "phase B exited with $rc (try $try)"; cleanup
  [ $rc = 4 ] && { echo "STOPPED: powermetrics is not sampling (see README)."; exit 4; }
  sleep 30
done
has_event phase_b_done || { echo "STOPPED: Phase B did not finish after 3 tries; see $OUT/run.log. Re-run run_all.sh to resume."; exit 3; }

# ---------------------------------------------------------------- 5. reduce + checklist
[ -n "$DRY" ] && "$PY" "$BILL/harness.py" synth-pm $DRY
"$PY" "$BILL/harness.py" reduce $DRY; rc=$?
if pgrep -lx llama-server >/dev/null; then echo "WARNING: a llama-server still runs: $(pgrep -lx llama-server)"; else echo "no llama-server left running."; fi
echo
echo "=== finished $(date '+%Y-%m-%d %H:%M:%S'). Files in $OUT"
[ -z "$DRY" ] && echo ">>> Now stop powermetrics: Ctrl-C in Terminal 1 (or keep it for the optional recordings: bash $BILL/run_all.sh show)."
exit $rc
