# E6 "the bill": reduce report (2026-10-10), saved by the main session from the reduce agent's hand-back

Sources: out/bill-capture.json (ep22-bill-capture-2), out/bill-labels.json, out/checklist.txt, out/run.log. No recorded run data changed.

## Reducer bug (fixed in harness.py only; 17/17 unit tests, 2 new regression tests TestGrowingPlist)
powermetrics was still appending to pm.plist during reduce: (1) write_samples_csv re-read the longer file -> IndexError; (2) Power.load took the file mtime only after the ~50 s parse -> timestamp anchor rejected, only 1 of 3 sync pulses found, joules wrong (negative). That crashed capture is kept as out/bill-capture.crashed-reduce-0403.json: DO NOT USE. Fix: read once, take mtime before parsing, keep per-sample values for the CSV, new `reduce --pm PATH`. Reduce used a snapshot: first 1,467,048,486 bytes of pm.plist (cut at a boundary), sha256 0bf2ca12edd8c4174e2fa8530555f7b6c2443dd8b0800c96852248ce29e6c798 (power.raw_sha256).

## Checklist: OVERALL PASS, 23 PASS / 0 WARN / 0 FAIL
idle.watts_median 1.0184 W (drift -0.1128; all 6 settled flags True); alignment 3/3 pulses (711.8, 720.1, 728.0 ms), offset 720.0 ms, drift 16.2 ms, 0 sampler gaps, 34,952 samples, metric combined, no dram key. cache_n 0 on every Phase A / nocache request; cached arm 125/125 hits; answers 20/10/10/10; think cap hits 0.

## Medians
| kind | joules | tokens in / out |
|---|---|---|
| short (n20) | 33.83 (spread 0.076) | 34 / 52 |
| think (n10) | 127.94 | 30 / 214 (reasoning 157.5) |
| long (n10) | 658.36 | 47 / 1031.5 |
| longctx (n10) | 1927.30 (prefill share 0.954) | 16033 / 128.5 |
| agent nocache (n5) | 3895.6 (spread 0.47), 2.67 min, 22 turns | 42768 / 1176 |
| agent cached (n5) | 1474.8 (spread 0.19), 0.98 min, 30 turns | 74512 / 1548 (fresh 4924, cache 69588) |
Block check: 100 short answers 36.05 J each (1.066x the short median), 0 errors. Derived: think/short 3.78; longctx/short 56.97; J per 1k written 615.9; J per 1k read 114.4; write/read 5.38; agent cached/nocache 0.379; agent J per 1k read 82.7.

## Agent ticket pass/fail (run.log "fail N/4" means N of 4 tests PASSED)
nocache seeds 0-4 tests passed: 3, 0 (stuck 30 turns), 1 (nudged), 4 PASS, 3 -> 1 of 5 runs passed. cached: 1 (stuck), 0, 4 PASS, 0 (stuck), 0 (stuck) -> 1 of 5. agent_passed = 2 of 10 (the plan's wording expected "One"). tests_modified False.

## Anomalies
No retries/restarts/errors/OOM. Thermal Heavy only in nocache seed 1 (877 of 1625 samples, 354 s, 8806 J) and seed 3 (391 of 1023, 222 s, 5703 J) = the nocache spread; block-check window 206 Moderate / 21 Heavy of 664. A stale `sudo sh -c powermetrics` (pid 17781, started 01:53, tty s013) is listed next to the active one (19615/19616): leave it, tell the operator.

## 41 of 41 labels resolved (out/bill-labels.json)
- agent_written_tokens: {'key': 'agent.nocache.completion_tokens_median', 'value': 1176}
- agent_read_tokens: {'key': 'agent.nocache.prompt_tokens_median', 'value': 42768}
- agent_turns_nocache: {'key': 'agent.nocache.turns_median', 'value': 22}
- agent_minutes_nocache: {'key': 'agent.nocache.minutes_median', 'value': 2.66608333333}
- agent_read_write_ratio: {'key': 'derived.agent_read_write_ratio', 'value': 36.3673469388}
- agent_joules_nocache: {'key': 'agent.nocache.joules_median', 'value': 3895.59250767}
- agent_prefill_share_nocache: {'key': 'agent.nocache.prefill_share', 'value': 0.836636341045}
- agent_passed: {'key': 'agent.passed_total', 'value': 2}
- agent_fresh_read_share: {'key': 'agent.cached.fresh_read_share', 'value': 0.0689643472139}
- agent_joules_per_thousand_read: {'key': 'derived.agent_joules_per_thousand_read', 'value': 82.7305046885}
- agent_joules_cached: {'key': 'agent.cached.joules_median', 'value': 1474.77404437}
- agent_local_cost: {'key': 'money.agent_nocache.local_usd', 'value': 0.000198134163376}
- agent_api_cost: {'key': 'money.agent_nocache.api_usd', 'value': 0.003416808}
- agent_opus_cost: {'key': 'money.agent_nocache.opus_usd', 'value': 0.194592}
- agent_haiku_cost: {'key': 'money.agent_nocache.haiku_usd', 'value': 0.0048648}
- scale_kwh_agent: {'key': 'scale.agent_kwh', 'value': 1082.10902991}
- scale_home_share_agent: {'key': 'scale.agent_home_years', 'value': 0.100278846252}
- scale_api_usd_agent: {'key': 'scale.agent_api_usd', 'value': 3416.808}
- scale_opus_usd_agent: {'key': 'scale.agent_opus_usd', 'value': 194592.0}
- idle_watts: {'key': 'idle.watts_median', 'value': 1.01837692634}
- seconds_short: {'key': 'answers.short.seconds_median', 'value': 1.48817741871}
- joules_short: {'key': 'answers.short.joules_median', 'value': 33.8295755314}
- bulb_seconds_short: {'key': 'derived.bulb_seconds_short', 'value': 3.38295755314}
- bulb_seconds_think: {'key': 'derived.bulb_seconds_think', 'value': 12.7943171577}
- tokens_think: {'key': 'answers.think.reasoning_tokens_median', 'value': 157.5}
- joules_think: {'key': 'answers.think.joules_median', 'value': 127.943171577}
- think_vs_short_multiple: {'key': 'derived.think_vs_short_multiple', 'value': 3.7819916321}
- watts_short: {'key': 'answers.short.decode_watts_median', 'value': 22.6598608179}
- watts_think: {'key': 'answers.think.decode_watts_median', 'value': 24.7481379781}
- tokens_long: {'key': 'answers.long.predicted_n_median', 'value': 1031.5}
- joules_long: {'key': 'answers.long.joules_median', 'value': 658.35591776}
- joules_per_thousand_written: {'key': 'derived.joules_per_thousand_written', 'value': 615.918820365}
- per_token_spread: {'key': 'derived.per_token_spread', 'value': 0.184345940853}
- joules_longctx: {'key': 'answers.longctx.joules_median', 'value': 1927.30270714}
- longctx_vs_short_multiple: {'key': 'derived.longctx_vs_short_multiple', 'value': 56.9709396841}
- prefill_share_longctx: {'key': 'answers.longctx.prefill_share', 'value': 0.953689772221}
- joules_per_thousand_read: {'key': 'derived.joules_per_thousand_read', 'value': 114.383713582}
- write_read_ratio: {'key': 'derived.write_read_ratio', 'value': 5.38467235478}
- cost_short_thousand: {'key': 'money.short.local_usd_per_thousand', 'value': 0.00172060979994}
- api_cost_short_thousand: {'key': 'money.short.api_usd_per_thousand', 'value': 0.017372}
- short_spread: {'key': 'answers.short.spread', 'value': 0.0756947660798}
