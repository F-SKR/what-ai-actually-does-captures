# Episode 6: the bill (`e6-bill`)

**Question**: which part of an AI answer sends the bill, reading or writing, and what does it cost in joules, seconds, tokens and dollars? Qwen3-8B Q4_K_M, llama.cpp build 11255, on a MacBook (Apple M4 Pro, 24 GB, mains power, macOS 26.2), prompt cache off for the answers. Chip energy from Apple's `powermetrics` every 200 ms, with an idle window of the same length subtracted after every run. 50 answers of four kinds (20 short, 10 with thinking on, 10 long, 10 that read a 16,000-token document), a 100-answer block check, and one coding ticket ten times (five with the prompt cache off, five with it on).

## Files

| file | what it is |
|---|---|
| `data/bill-capture.json` | the summary (schema `ep22-bill-capture-2`). `power` (how the power log was read and aligned), `idle` (the baselines), `answers` (per kind: joules, seconds, tokens in and out, prefill share, decode watts), `block` (the 100-answer check), `agent` (`nocache` and `cached` ticket arms: turns, minutes, joules, tokens read and written, cache hits, pass counts), `derived` (ratios such as joules per 1,000 tokens read and written), **`money` and `scale` (the arithmetic)**, `checks`, `examples` |
| `data/bill-power-samples.csv.gz` | **the power log**: 34,952 samples at 200 ms. Columns: `t_end_unix`, `elapsed_ms`, `power_mw` and `combined_power_mw` (CPU plus GPU plus Neural Engine, as `powermetrics` estimates it, milliwatts), `cpu_power_mw`, `gpu_power_mw`, `ane_power_mw`, `thermal_pressure` |
| `data/bill-runs.jsonl` | 157 lines, one per request: `set` (`answer`, `block`, `warmup`, `sync`), `seed`, start and end time `t0` and `t1` (unix seconds, the same clock as the power log), `usage` and `timings` as the server reported them |
| `data/bill-agent-runs.jsonl` | 10 lines, one per ticket run: arm, seed, tests passed of 4, turns, seconds, token and cache sums, the idle and run windows, and the full `transcript` |
| `data/bill-agent-turns.jsonl` | 248 lines, one per turn of the ticket runs: `usage`, `timings`, `tool_seconds`, `finish_reason` |
| `data/bill-labels.json` | every number the narration says from this run, with the capture key it is read from (41 labels) |
| `data/longctx-doc.json` | the exact 16,000-token document (a public-domain Shakespeare passage) used for the "reading" answers, with its hash |
| `data/tier-ledger.csv` | **lever 1** ("write the check as a test"): the factory's tier ledger of 9 October 2026, one row per tier, worker, label set, check style (`criteria_mode`: `prose` or `tests`) and reviewer, 17 rows. Columns: `tier`, `worker_tier_name`, `labels`, `criteria_mode`, `review_tier_name`, `dispatched`, `merged`, `attempts`, `veto_rounds`, `rebase_rounds`, `surviving_mutants`, `oversized`, `failed`, three medians (minutes to merge, wall minutes to merge, tokens to merge; a `0.0` token median means "not recorded"). The row numbers in `claims.md` ("rows 2, 3 and 10") are line numbers of this file, line 1 being the header |
| `data/power_keys.json` | which `powermetrics` keys were used for the energy |
| `harness/prompts.json` | **the prompts**: the four kinds of answer, the system prompt, token limits and run counts |
| `harness/harness.py` | checks, key discovery, phase A (the answers), `reduce` (power log + request log to the capture, with all the arithmetic) |
| `harness/run_ticket.py` | phase B: the coding ticket runs, cache off and on; `make_demo_repo.py` and `sandbox.py` build the ticket's project and sandbox the shell; `run_all.sh` runs everything end to end; `live_meter.py` is the on-screen meter used for pictures; `test_reduce.py` are the reducer's unit tests |
| `logs/` | `REPORT.md` (the reducer report, the checklist result 23 pass / 0 warn / 0 fail, the medians and the anomalies), `checklist.txt`, `checks.json`, `verify.json`, `model-sha.json`, `run.log`, `bill-events.jsonl` (the timeline of phases), and the two llama-server logs `server-a.log` (phase A) and `server-b.log` (phase B) |
| `claims.md`, `experiment-plan.md` | the claims table and the plan |

## How to read it

1. **Per answer**: in `bill-capture.json`, `answers.short`, `answers.think`, `answers.long`, `answers.longctx`: `joules_median` is the net energy above idle for the answer (for example about 34 J for a short answer), `prefill_share` is the part spent reading the prompt, `decode_watts_median` the average chip power while writing.
2. **From the raw log**: for a request in `bill-runs.jsonl` with times `t0` and `t1`, add up `power_mw` x `elapsed_ms` for the samples in `[t0 + offset, t1 + 1 s]` (the clock offset between the two logs is `power.alignment_offset_ms`, 720 ms) and subtract the mean power of the idle window of the same length. `harness.py reduce` does exactly this, including the reading window `[t0, t0 + prompt_ms]` and the writing window.
3. **The arithmetic** is in `money` and `scale`: the electricity price (`tariff_usd_per_kwh`, 18.31 cents per kWh, a published U.S. residential average, July 2026), the cloud list prices read on 9 October 2026 (`price`) and the scale-up to a million tickets (`scale.agent_kwh`, `scale.agent_home_years` against 10,791 kWh a year for a U.S. home, `scale.agent_api_usd`, `scale.agent_opus_usd`). Dollars are computed from measured tokens and joules, not measured.
4. **The ticket**: `agent.nocache` against `agent.cached`; the pass counts are in `agent.passed_total` (2 of 10 runs passed; the bill came either way).

## Where the sources of the price and power numbers are

- Anthropic's price list (read 9 October 2026): https://platform.claude.com/docs/en/about-claude/pricing . The page text is not redistributed here.
- U.S. electricity price: EIA Electric Power Monthly Table 5.6.A, https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a ; average household use: https://www.eia.gov/tools/faqs/faq.php?id=97&t=3
- `powermetrics` is documented by its manual page (`man powermetrics` on macOS 26.2); the manual text is not redistributed here.
- The raw `powermetrics` property list (about 295 MB compressed, 1.47 GB of text for the part that was read) is **available on request**; `power.raw_sha256` in the capture is the hash of the snapshot the reducer read. The 200 ms samples above are the full reduction of it.

## Limits specific to this episode

- One small model at 4 bits on one Mac; one ticket, ten runs; a story, not a benchmark.
- `powermetrics` is Apple's estimate for the chip, not wall power.
- The idle subtraction assumes a steady idle. In one cache-off run the idle window beside it was not quiet (about 4.8 W, not about 1 W), so the cache-off ticket's joules may be over a tenth low (about 3,900 J as reported, about 4,400 J against the run-start idle). Two cache-off runs ran with the chip's thermal pressure at `Heavy` (`machine.thermal_pressure`; `logs/REPORT.md`).
- `bill-capture.json` and `bill-agent-runs.jsonl` had `/Users/<account>` written as `~` after the harness computed `transcript_sha256`; those hashes no longer match the redacted text (see `../REDACTIONS.md`).
- A first reduce crashed because `powermetrics` was still appending to the log; the harness was fixed (`logs/REPORT.md`, "Reducer bug") and the capture rebuilt from the same samples. The crashed capture is not included.
- The tier ledger is the factory's own bookkeeping, not part of the measured bill, and it is small (one ledger of one factory, per-class counts from 1 to 52 cards; the ledger itself says to wait for about fifty merged cards in a class). It is a read-only export of 9 October 2026 limited to the factory's own worker configurations; the factory's board, cards and other configurations are not published.

## The tier ledger: names

In the factory the workers are configured as named presets. In `data/tier-ledger.csv` each preset name is replaced by a tier name, with one fixed table; no number in the file was changed (the file's other cells are identical to the export, checked by the staging script). The two preset columns are renamed `worker_tier_name` and `review_tier_name`. `unknown` means no reviewer was recorded for those cards.

| name in this file | tier column | role in the file | rows (line numbers) |
|---|---|---|---|
| `junior-fast` | junior | worker | 2-8 |
| `junior-medium` | junior | worker | 9-10 |
| `medior-fast` | medior | worker | 11-13 |
| `medior-high` | medior | worker | 14-17 |
| `senior-code` | senior | worker | 18 |
| `senior-review` | | reviewer only (column `review_tier_name`, rows 4, 9, 10, 14-17) | |
| `unknown` | | no reviewer recorded | |

Lever 1 of the episode ("write the check as a test") uses this file: rows 2 and 3 (`junior-fast`, no label, `prose` against `tests`: 23 of 52 merged against 20 of 20) and row 10 (`junior-medium`, `tests`, 17 of 17); rows 11-18 are the medior and senior classes of lever 3. The claims in `claims.md` still call these workers by placeholders; the names here are only the file's labels.
