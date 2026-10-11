#!/usr/bin/env python3
"""Unit tests for the E6 reducer on synthetic powermetrics plists. Run: python3 -m unittest test_reduce -v (from ~/ep22-lab/bill)."""
import io, json, os, plistlib, shutil, sys, tempfile, unittest, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import harness as H

IDLE, READ, WRITE, TOOL = 1.0, 25.0, 20.0, 4.0
T0 = 1_800_000_000.37  # a fractional start, so the second-resolution timestamp anchor is off by 0.37 s

class Timeline:
    """Builds true-time windows and a power profile; the plist clock runs SHIFT s behind true time."""
    def __init__(s): s.t = T0 + 20; s.spans = []; s.events = []; s.runs = []; s.aruns = []; s.aturns = []
    def idle(s, name, secs, phase="a"):
        a = s.t; s.t += secs; s.events.append({"event": "idle", "name": name, "phase": phase, "window": [a, s.t], "t": s.t})
    def burst(s, secs, prompt_s):
        t0 = s.t; s.spans.append((t0, t0 + prompt_s, READ)); s.spans.append((t0 + prompt_s, t0 + secs, WRITE)); s.t += secs; return t0, s.t
    def sync(s, name):
        a = s.t; s.t += 30; b = s.t; t0, t1 = s.burst(20, 0.1); s.events.append({"event": "sync", "name": name, "idle": [a, b], "t0": t0, "t1": t1, "t": t1}); s.t += 5
    def answer(s, kind, seed, rnd, secs, prompt_s, prompt_n, predicted_n, reasoning=0, finish="stop"):
        s.t += 5; t0, t1 = s.burst(secs, prompt_s); ans = [t0, t1 + 1]; s.t = t1 + 1 + 3; idle = [s.t, s.t + (ans[1] - ans[0])]; s.t = idle[1]
        s.runs.append({"set": "answer", "phase": "a", "kind": kind, "seed": seed, "round": rnd, "attempt": 1, "gap_s": 3.0, "t0": t0, "t1": t1, "windows": {"answer": ans, "idle": idle},
                       "usage": {"prompt_tokens": prompt_n, "completion_tokens": predicted_n}, "timings": {"cache_n": 0, "prompt_n": prompt_n, "prompt_ms": prompt_s * 1000, "predicted_n": predicted_n, "predicted_ms": (secs - prompt_s) * 1000},
                       "finish_reason": finish, "reasoning_tokens": reasoning})
    def agent(s, arm, seed, calls):
        s.t += 5; start = s.t; rid = f"{arm}-{seed}-1"; turns = []
        for k, (secs, prompt_s, ptok, pn, cn, ctok, tool_s) in enumerate(calls):
            t0, t1 = s.burst(secs, prompt_s); s.spans.append((t1, t1 + tool_s, TOOL)); s.t = t1 + tool_s
            turns.append({"arm": arm, "seed": seed, "run_id": rid, "turn": k, "t0_unix": t0, "t1_unix": t1, "usage": {"prompt_tokens": ptok, "completion_tokens": ctok},
                          "timings": {"cache_n": cn, "prompt_n": pn, "prompt_ms": prompt_s * 1000, "predicted_n": ctok, "predicted_ms": (secs - prompt_s) * 1000}, "tool_seconds": tool_s})
        run = [start, s.t + 1]; s.t = run[1] + 3; idle = [s.t, s.t + (run[1] - run[0])]; s.t = idle[1]
        s.aturns += turns
        s.aruns.append({"arm": arm, "seed": seed, "run_id": rid, "passed": seed == 0, "tests_passed": 4 if seed == 0 else 1, "tests_modified": False, "turns": len(calls), "seconds": s.t - start, "stuck": False, "nudged": False,
                        "prompt_tokens_sum": sum(c[2] for c in calls), "completion_tokens_sum": sum(c[5] for c in calls), "prompt_n_sum": sum(c[3] for c in calls), "cache_n_sum": sum(c[4] for c in calls),
                        "max_prompt_tokens": max(c[2] for c in calls), "cache_misses": (sum(1 for k, c in enumerate(calls) if k >= 1 and c[4] == 0) if arm == "cached" else None), "transcript_sha256": "x", "windows": {"run": run, "idle": idle}})
    def power(s, t):
        w = IDLE
        for a, b, p in s.spans:
            if a <= t < b: w = max(w, p)
        return w

SHIFT = 0.7

def build_world(out):
    T = Timeline(); T.sync("sync"); T.idle("before", 60)
    for r in range(2):
        T.answer("short", 2 * r, r, 4.0, 0.4, 20, 60); T.answer("short", 2 * r + 1, r, 4.0, 0.4, 20, 60)
        T.answer("think", r, r, 30.0, 0.4, 20, 600, reasoning=500); T.answer("long", r, r, 40.0, 0.4, 30, 800)
        T.answer("longctx", r, r, 30.0, 20.0, 16020, 100)
    T.sync("sync_b"); T.idle("phase_b_before", 30, "b")
    T.agent("nocache", 0, [(6.0, 2.0, 1000, 1000, 0, 100, 2.0), (8.0, 4.0, 5000, 5000, 0, 100, 2.0)])
    T.agent("cached", 0, [(6.0, 2.0, 1000, 1000, 0, 100, 2.0), (5.0, 1.0, 5000, 400, 4600, 100, 2.0)])
    T.sync("sync2"); T.idle("after", 60, "b")
    n = int((T.t + 20 - T0) / 0.2)
    data = H.synth_plist_bytes(T0 + 0.2, n, 0.2, lambda t_raw: T.power(t_raw + SHIFT))
    open(os.path.join(out, "pm.plist"), "wb").write(data); os.utime(os.path.join(out, "pm.plist"), (T0 + 0.2 + (n - 1) * 0.2,) * 2)  # mtime = last sample, as on the Mac
    keys, allk = H.make_keys(H.split_plist_stream(data[:100000])[0]); json.dump(keys, open(os.path.join(out, "power_keys.json"), "w"))
    for name, rows in (("bill-events.jsonl", T.events), ("bill-runs.jsonl", T.runs), ("bill-agent-runs.jsonl", T.aruns), ("bill-agent-turns.jsonl", T.aturns)):
        with open(os.path.join(out, name), "w") as f:
            for r in rows: f.write(json.dumps(r) + "\n")
    return T

class TestPlistAndKeys(unittest.TestCase):
    def test_split_skips_partial_trailing_record(self):
        data = H.synth_plist_bytes(T0, 5, 0.2, lambda t: 2.0)
        s, rest = H.split_plist_stream(data + b"<?xml version")
        self.assertEqual(len(s), 5); self.assertTrue(rest.startswith(b"<?xml"))
    def test_keys_combined(self):
        s, _ = H.split_plist_stream(H.synth_plist_bytes(T0, 3, 0.2, lambda t: 2.0))
        k, allk = H.make_keys(s)
        self.assertEqual(k["combined"], "processor.combined_power"); self.assertEqual(H.metric_of(k), "combined")
        self.assertEqual(sorted(k["parts"]), ["processor.ane_power", "processor.cpu_power", "processor.gpu_power"]); self.assertIsNone(k["dram"])
        self.assertIn("elapsed_ns", allk)
    def test_keys_sum_of_parts_when_no_combined(self):
        s, _ = H.split_plist_stream(H.synth_plist_bytes(T0, 3, 0.2, lambda t: 2.0, combined=False))
        k, _ = H.make_keys(s); self.assertIsNone(k["combined"]); self.assertEqual(H.metric_of(k), "sum_of_parts")
        self.assertAlmostEqual(H.sample_power(s[0], k), 2000.0, places=3)
    def test_package_and_dram_rules(self):
        s = [{"elapsed_ns": 200000000, "processor": {"package_power": 5000.0, "dram_power": 300.0, "cpu_power": 1.0, "gpu_power": 2.0}}]
        k, _ = H.make_keys(s); self.assertEqual(H.metric_of(k), "package"); self.assertEqual(k["dram"], "processor.dram_power")
        self.assertEqual(H.sample_power(s[0], k), 5300.0)
    def test_refuses_without_chip_power(self):
        with self.assertRaises(SystemExit): H.make_keys([{"elapsed_ns": 1, "processor": {"cpu_power": 1.0}}])

class TestEnergy(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); data = H.synth_plist_bytes(T0, 100, 0.2, lambda t: 3.0)
        open(os.path.join(self.d, "pm.plist"), "wb").write(data); os.utime(os.path.join(self.d, "pm.plist"), (T0 + 99 * 0.2,) * 2)
        json.dump(H.make_keys(H.split_plist_stream(data)[0])[0], open(os.path.join(self.d, "k.json"), "w"))
    def tearDown(self): shutil.rmtree(self.d)
    def test_constant_power_energy(self):
        P = H.Power.load(os.path.join(self.d, "pm.plist"), os.path.join(self.d, "k.json"), [])
        a = P.start[10] + 0.05; b = a + 4.0
        self.assertAlmostEqual(P.E(a, b), 12.0, places=3); self.assertAlmostEqual(P.mean_w(a, b), 3.0, places=3)
        self.assertEqual(P.E(b, a), 0.0); self.assertEqual(P.align_info["samples_n"], 100)

class TestReduceEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(); H.set_mode(False)
        C = H.Cfg; C.out = cls.d; C.pm = os.path.join(cls.d, "pm.plist"); C.keys = os.path.join(cls.d, "power_keys.json")
        for b in ("bill-runs.jsonl", "bill-runs-discarded.jsonl", "bill-events.jsonl", "bill-agent-runs.jsonl", "bill-agent-turns.jsonl", "bill-agent-discarded.jsonl"):
            setattr(C, b.replace("bill-", "").replace(".jsonl", "").replace("-", "_"), os.path.join(cls.d, b))
        C.log = os.path.join(cls.d, "run.log"); C.state = os.path.join(cls.d, "state.json")
        C.rounds = 2; C.agent_order = [(0, "nocache"), (0, "cached")]
        cls.T = build_world(cls.d)
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()): cls.rc = H.reduce_all(None)
        cls.cap = json.load(open(os.path.join(cls.d, "bill-capture.json")))
    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.d); H.set_mode(False)
    def test_alignment_recovers_offset(self):
        p = self.cap["power"]; self.assertTrue(self.cap["checks"]["alignment_ok"], p)
        # raw clock = true - 0.7 s, anchor from a whole-second timestamp of T0 + 0.2 (0.57 s truncated): expected offset 0.7 + 0.57
        self.assertAlmostEqual(p["alignment_offset_ms"] / 1000, SHIFT + 0.57, delta=0.15)
        self.assertLessEqual(p["alignment_drift_ms"], 200)
    def test_short_answer_energy(self):
        a = self.cap["answers"]["short"]  # true: read 0.4 s x 24 W net + write 3.6 s x 19 W net = 9.6 + 68.4 = 78 J; tail at idle -> 0
        self.assertEqual(a["n"], 4); self.assertAlmostEqual(a["joules_median"], 78.0, delta=78 * 0.05)
        self.assertAlmostEqual(a["decode_watts_median"], 19.0, delta=1.5); self.assertAlmostEqual(a["seconds_median"], 4.0, places=3)
        self.assertAlmostEqual(a["joules_net_vs_idle_before_median"], 78.0, delta=4)
        self.assertLess(abs(a["tail"]["joules_net_median"]), 2.0)
    def test_longctx_prefill_split(self):
        a = self.cap["answers"]["longctx"]  # read 20 s x 24 = 480, write 10 s x 19 = 190
        self.assertAlmostEqual(a["prefill_joules_median"], 480, delta=15); self.assertAlmostEqual(a["decode_joules_median"], 190, delta=10)
        self.assertAlmostEqual(a["prefill_share"], 480 / 670, delta=0.02); self.assertAlmostEqual(a["prefill_watts_median"], 24, delta=1)
        self.assertTrue(self.cap["checks"]["longctx_prompt_n_ok"])
    def test_derived_and_money(self):
        D = self.cap["derived"]; A = self.cap["answers"]
        self.assertAlmostEqual(D["think_vs_short_multiple"], A["think"]["joules_median"] / A["short"]["joules_median"], places=6)
        self.assertAlmostEqual(D["joules_per_thousand_written"], 19 * 39.6 / 800 * 1000, delta=40)
        self.assertAlmostEqual(D["joules_per_thousand_read"], 480 / 16020 * 1000, delta=1.5)
        self.assertAlmostEqual(D["bulb_seconds_short"], A["short"]["joules_median"] / 10, places=6)
        self.assertEqual(A["think"]["reasoning_tokens_median"], 500); self.assertEqual(A["think"]["hit_cap"], 0)
        M = self.cap["money"]
        self.assertAlmostEqual(M["short"]["local_usd"], A["short"]["joules_median"] / 3.6e6 * 0.1831, places=12)
        self.assertAlmostEqual(M["short"]["api_usd"], (20 * 0.072 + 60 * 0.287) / 1e6, places=12)
        self.assertAlmostEqual(M["agent_nocache"]["opus_usd"], (6000 * 4 + 200 * 20) / 1e6, places=9)
        self.assertAlmostEqual(M["agent_nocache"]["haiku_usd"], (6000 * 0.10 + 200 * 0.50) / 1e6, places=9)
        self.assertAlmostEqual(M["agent_cached"]["opus_usd_cached"], (1400 * 4 + 4600 * 0.20 + 200 * 20) / 1e6, places=9)
        S = self.cap["scale"]; self.assertAlmostEqual(S["agent_kwh"], 1e6 * self.cap["agent"]["nocache"]["joules_median"] / 3.6e6, places=3)
        self.assertAlmostEqual(S["agent_home_years"], S["agent_kwh"] / 10791, places=6)
    def test_agent_split(self):
        g = self.cap["agent"]["nocache"]  # reading 6 s x 24 = 144, writing 8 s x 19 = 152, tools 4 s x 3 = 12 (+ 1 s tail at idle = 0)
        self.assertAlmostEqual(g["reading"]["joules_median"], 144, delta=8); self.assertAlmostEqual(g["writing"]["joules_median"], 152, delta=8)
        self.assertAlmostEqual(g["tools"]["joules_median"], 12, delta=6); self.assertAlmostEqual(g["joules_median"], 308, delta=15)
        self.assertEqual(g["fresh_read_share"], 1.0); self.assertAlmostEqual(self.cap["agent"]["cached"]["fresh_read_share"], 1400 / 6000, places=9)
        self.assertEqual(self.cap["checks"]["cached_arm_hits"], 1.0); self.assertEqual(self.cap["agent"]["cached"]["cache_misses"], 0)
        self.assertEqual(self.cap["derived"]["agent_read_write_ratio"], 30.0)
        bins = self.cap["derived"]["reading_j_per_thousand_by_depth"]
        self.assertAlmostEqual(bins["0-4k"]["j_per_thousand"], 48, delta=4); self.assertAlmostEqual(bins["4-8k"]["j_per_thousand"], 96 / 5, delta=2)
        self.assertEqual(self.cap["agent"]["passed_total"], 2); self.assertEqual(self.cap["examples"]["cold_open"]["agent_seed"], 0)
    def test_idle_and_checks(self):
        I = self.cap["idle"]; self.assertAlmostEqual(I["watts_median"], 1.0, places=3); self.assertAlmostEqual(I["drift"], 0.0, places=6)
        self.assertTrue(all(v["settled"] for v in I["by_kind"].values()))
        self.assertTrue(self.cap["checks"]["cache_n_all_zero"]); self.assertTrue(self.cap["checks"]["prompt_reread_all"])
        self.assertEqual(self.cap["schema_version"], "ep22-bill-capture-2")
        self.assertTrue(os.path.exists(os.path.join(self.d, "bill-power-samples.csv.gz")))
        lab = json.load(open(os.path.join(self.d, "bill-labels.json"))); self.assertEqual(len(lab), 41)
        self.assertIsNotNone(lab["agent_read_tokens"]["value"]); self.assertIsNotNone(lab["joules_short"]["value"])

    def test_warm_check_runs_on_the_stream(self):
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()): H.warm_check(None)
        wc = [e for e in H.events("warm_check")][-1]
        self.assertNotIn("error", wc); self.assertAlmostEqual(wc["idle_before_w"], 1.0, places=3)
        self.assertEqual(set(wc["by_kind"]), {"short", "think", "long", "longctx"}); self.assertFalse(any(v["warm"] for v in wc["by_kind"].values()))

class TestAnchor(unittest.TestCase):
    def test_bad_timestamps_fall_back_to_mtime(self):
        d = tempfile.mkdtemp()
        try:
            data = H.synth_plist_bytes(T0, 50, 0.2, lambda t: 3.0, ts_shift=7200)  # timestamps two hours off
            p = os.path.join(d, "pm.plist"); open(p, "wb").write(data); os.utime(p, (T0 + 49 * 0.2,) * 2)
            json.dump(H.make_keys(H.split_plist_stream(data)[0])[0], open(os.path.join(d, "k.json"), "w"))
            P = H.Power.load(p, os.path.join(d, "k.json"), [])
            self.assertTrue(P.align_info["anchor"].startswith("file_mtime")); self.assertAlmostEqual(P.end[-1], T0 + 49 * 0.2, places=3)
        finally: shutil.rmtree(d)

class TestGrowingPlist(unittest.TestCase):
    """Regression (E6 run 2026-10-10): powermetrics keeps appending to pm.plist while `reduce` runs."""
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.p = os.path.join(self.d, "pm.plist"); self.k = os.path.join(self.d, "k.json")
        data = H.synth_plist_bytes(T0, 100, 0.2, lambda t: 3.0)
        open(self.p, "wb").write(data); os.utime(self.p, (T0 + 99 * 0.2,) * 2)
        json.dump(H.make_keys(H.split_plist_stream(data)[0])[0], open(self.k, "w"))
        self.old_pm = H.Cfg.pm; H.Cfg.pm = self.p
    def tearDown(self): H.Cfg.pm = self.old_pm; shutil.rmtree(self.d)
    def grow(self, n=40):
        with open(self.p, "ab") as f: f.write(H.synth_plist_bytes(T0 + 100 * 0.2, n, 0.2, lambda t: 3.0))
    def test_samples_csv_after_file_grew(self):
        import csv, gzip
        P = H.Power.load(self.p, self.k, []); self.grow()  # was: IndexError in write_samples_csv (it re-read the longer file)
        out = os.path.join(self.d, "s.csv.gz"); H.write_samples_csv(P, out)
        rows = list(csv.reader(gzip.open(out, "rt")))
        self.assertEqual(len(rows) - 1, P.align_info["samples_n"]); self.assertEqual(len(rows) - 1, 100)
        self.assertEqual(rows[0][:4], ["t_end_unix", "elapsed_ms", "power_mw", "combined_power_mw"]); self.assertAlmostEqual(float(rows[1][2]), 3000.0, places=1)
    def test_mtime_anchor_taken_at_read_not_after_parse(self):
        real = H.split_plist_stream
        def slow_parse(data):  # the file grows and its mtime moves 60 s on while the big plist is being parsed
            self.grow(); os.utime(self.p, (T0 + 99 * 0.2 + 60,) * 2); return real(data)
        H.split_plist_stream = slow_parse
        try: P = H.Power.load(self.p, self.k, [])
        finally: H.split_plist_stream = real
        self.assertEqual(P.align_info["anchor"], "timestamp_first_sample"); self.assertEqual(P.align_info["samples_n"], 100)
        self.assertAlmostEqual(P.end[-1], T0 + 99 * 0.2, delta=1.0)

class TestOrder(unittest.TestCase):
    def test_rotation_and_seeds(self):
        H.set_mode(False); o = H.plan_order()
        self.assertEqual(len(o), 10); self.assertEqual([k for k, _ in o[0]], ["short", "short", "think", "long", "longctx"])
        self.assertEqual([k for k, _ in o[1]], ["think", "long", "longctx", "short", "short"]); self.assertEqual(o[1][3], ("short", 2))
        self.assertEqual(sum(1 for r in o for k, _ in r if k == "short"), 20); self.assertEqual(sorted(s for r in o for k, s in r if k == "think"), list(range(10)))
        self.assertEqual(H.Cfg.agent_order[:4], [(0, "nocache"), (0, "cached"), (1, "cached"), (1, "nocache")])

if __name__ == "__main__": unittest.main()
