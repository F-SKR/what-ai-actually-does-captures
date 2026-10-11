# Experiment plan — EP22-E6 the bill: what one AI answer and one AI task really cost (idea `5a39a7f27964`, v2)

**Status: run 2026-10-10 (02:10-04:02 local, Phase A and Phase B as written), reduced the same night (checklist OVERALL
PASS 23 / 0 / 0; `bill-capture.json` captured_at_utc 2026-10-10T02:10:04Z), every label resolved into the script the same day
(section 10, real-number pass; v2 CHANGELOG). The screen recordings of section 9 step 6 were not made yet, and the evidence is
staged path-redacted in `v2/evidence-final/` without a PR (step 8).** Written 2026-10-09 for the reframed episode (v2). The operator runs it on the MacBook; the only
command that needs `sudo` is powermetrics (section 2), and the operator types it. Nothing here calls a paid provider,
downloads a file or needs the network after section 1's checks; the whole run is local.

What the run produces, in `episodes/5a39a7f27964/evidence/`:

| file | what | in the repo? |
|---|---|---|
| `bill-capture.json` | the capture, schema `ep22-bill-capture-2` (section 7); every `PLACEHOLDER_RESULT[label]` resolves from one of its keys (section 10) | yes |
| `bill-runs.jsonl` | one line per request of Phase A (four answer kinds, block check, sync bursts) | yes |
| `bill-agent-runs.jsonl` | one line per ticket run of Phase B (both arms), with the transcript (truncated as in the E3 demo) and the grade | yes |
| `bill-agent-turns.jsonl` | one line per model call inside a ticket run (timings, tokens, windows) | yes |
| `bill-power-samples.csv.gz` | one row per powermetrics sample: `t_end_unix, elapsed_ms, power_mw` plus the component columns of section 2 | yes |
| `tier-ledger-factory-2026-10-09.csv` | the factory tier ledger, **factory presets only** (section 6); already exported, not produced by the run | yes (already in v2/evidence) |
| `pm.plist`, the two screen recordings | raw sampler output and b-roll | no: operator archive; `power.raw_sha256` records the plist hash |

The episode asks: **what does an AI answer, and an AI task, really cost in electricity and money, and how do you cut
it without losing quality?** Phase A measures chip energy per answer for four answer kinds on the same model, with an
idle window of the same length subtracted from every answer and the long document's reading split from its writing.
Phase B runs one real coding ticket in an agent loop, five times with the server's prompt cache off and five times
with it on, splits every run into reading, writing and tool time, and grades each run against the ticket's four
tests. The money and scale numbers are arithmetic on those keys and stated prices (section 5).

Write the harness as `~/ep22-lab/bill/harness.py` in the style of the earlier EP22 harnesses (`~/ep22-lab/thinking/harness.py`,
`~/ep22-lab/factory/demo/run_demo.py`: plain `urllib` calls to `llama-server`, one JSON line per request). **Phase B reuses
the E3 demo code unchanged where it can**: `make_demo_repo.py` (ticket builder), the `run_small` loop, `grade()`, and the shared
hardened sandbox in `~/ep22-lab/factory/demo/harness.py` (sandbox-exec profile with no network, writes only in the run dir,
`open`/`osascript`/`say`/`screencapture` denied, one process group per command). Copy them into `~/ep22-lab/bill/` and
record their sha256 (section 1). Where an existing harness does something a different way, keep the existing way and
record it in the capture; the keys below, not the wording, are the contract.

## 1. Machine, build, model, ticket

| item | value | how to check before the run |
|---|---|---|
| machine | MacBook, Apple M4 Pro, 24 GiB (the series machine) | `sysctl -n machdep.cpu.brand_string`, `sysctl -n hw.memsize` → `machine.chip`, `machine.ram_bytes`; `sw_vers` → `machine.os` |
| power state | on mains power, Low Power Mode off, display brightness fixed for the whole run, no app open except two Terminal windows | `pmset -g batt` must say `AC Power`, `pmset -g` must show `lowpowermode 0` → `machine.power`; refuse to start otherwise; `caffeinate -dimsu` in a spare tab for the whole session |
| quiet Mac | no backup, no Spotlight indexing, no browser, no other llama-server | `pgrep -fl llama-server` empty; `mdutil -s /` shows indexing idle; Time Machine paused |
| llama.cpp | build 11255, commit 31385c9ce (the series build) | `~/llama.cpp/build/bin/llama-server --version` must print `version: 0.5.0-dev (build 11255, commit 31385c9ce)` → `llama_cpp.output` |
| model | `Qwen3-8B-Q4_K_M.gguf`, 5,027,784,512 bytes, sha256 `120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4` | `shasum -a 256 "<T7>/models/Qwen3-8B-Q4_K_M.gguf"` → `model.sha256`, `model.size_bytes`; refuse on a mismatch |
| long document | `~/ep21-lab/captures/ppl-text-shakespeare-120k.txt` (series 1 Part 4 perplexity text) | `shasum -a 256` → `config.longctx.source_sha256`; fallback in section 3 |
| ticket | the E3 demo's **easy** ticket: `make_demo_repo.py <dest> --ticket easy` builds `ledger/text.py` (`slugify` returns `title.replace(" ", "-")`) and `tests/test_text.py` with four tests (`test_lower_and_hyphen`, `test_trims`, `test_collapses_spaces`, `test_keeps_hyphens`); the ticket text is `TICKETS["easy"]` verbatim (section 4) | `python3 ~/ep22-lab/bill/run_ticket.py verify` builds the repo, runs the tests (the unchanged code must fail 4 of 4, as in the E3 demo's `verify.json`; record it as `config.agent.baseline_failing`), applies the reference solution `"-".join(title.strip().lower().split())` in a scratch copy and must pass 4 of 4, then deletes the scratch copy (the reference is never shown to the model) |
| harness files | `harness.py`, `run_ticket.py` (Phase B driver), `make_demo_repo.py`, `sandbox.py` (the copied demo harness), `prompts.json`, `power_keys.json` | `shasum -a 256` of each → `harness.sha256` (an object, file → hash) |

## 2. The power meter (powermetrics, operator `sudo`)

**What it measures.** powermetrics "may also display estimated power consumed by various SoC subsystems, such as CPU,
GPU, ANE (Apple Neural Engine)", and "Average power values reported by powermetrics are estimated and may be
inaccurate - hence they should not be used for any comparison between devices" (manual, <https://ss64.com/mac/powermetrics.html>;
on the Mac `man powermetrics` is authoritative). The run reports **chip power as powermetrics estimates it**, never
wall power, and never compares the Mac with another device.

**Step 1, sampler check (once, operator, `sudo`).**

```sh
mkdir -p ~/ep22-lab/bill
sudo powermetrics -h > ~/ep22-lab/bill/powermetrics-help.txt
sudo powermetrics --samplers cpu_power,gpu_power,ane_power -i 1000 -n 2 -f plist > ~/ep22-lab/bill/pm-check.plist
python3 ~/ep22-lab/bill/harness.py keys ~/ep22-lab/bill/pm-check.plist   # prints every numeric key whose path names power, energy or elapsed
```

If `cpu_power`, `gpu_power` or `ane_power` is not in `powermetrics-help.txt`, use the sampler group the help names for
CPU and GPU power and record it; **do not run without a combined chip power value.** Write the printed key names into
`power_keys.json` (the names below are the expected Apple-silicon names, not a verified fact):

```json
{"combined": "processor.combined_power", "parts": ["processor.cpu_power", "processor.gpu_power", "processor.ane_power"],
 "package": null, "dram": null, "elapsed": "elapsed_ns", "timestamp": "timestamp", "unit": "mW"}
```

Rule: a combined CPU+GPU+ANE value goes in `combined`; otherwise `combined` is `null` and the harness sums `parts`. A
package-level key (name contains `package`) becomes the primary metric. A memory key (name contains `dram` or `memory`)
goes in `dram`, is recorded as `power.dram_key` and is added to the metric when the combined value does not include it;
with no such key `power.dram_key` is `null` and seg_15 keeps "it may not count the memory". `power.metric` records the
choice (`package`, `combined` or `sum_of_parts`); `power.help_sha256` and `power.sampler_keys` record step 1.
Sanity: the idle value must read between 0.1 and 10 W with the model loaded and nothing running.

**Step 2, the run's sampler (operator, `sudo`, Terminal 1, left running for Phase A and Phase B):**

```sh
sudo powermetrics --samplers cpu_power,gpu_power,ane_power,thermal -i 200 -b 0 -f plist -o ~/ep22-lab/bill/pm.plist
```

One sample every 200 ms (`power.interval_ms` = 200, the line → `power.command`); `-b 0` = no output buffer, so the live
meter of section 9 is not behind; `thermal` records `machine.thermal_pressure` per round (drop it if `-h` does not list
it, and record null). Stop with Ctrl-C after the last step that needs it (section 9, step 6).

**Reading the plist stream.** With `-f plist`, powermetrics writes one plist document per sample, separated by a NUL byte (`\0`); `harness.py`, `harness.py keys` and `live_meter.py` split the file on `b'\0'`, parse each part with `plistlib.loads`, and skip a trailing partial record while the file is still growing.

**Alignment.** Each plist sample is an interval `[t_end − elapsed, t_end]` with one power value; `t_end` comes from the
running sum of `elapsed_ns` from the first sample (`power.alignment_method` = `cumulative_elapsed`), anchored by the
sync pulses: 30 s of idle, then a writing burst of about twenty seconds (thinking off, `Count from one to five hundred
in words, separated by commas.`, `max_tokens 900`, seed 0); the offset between the logged burst start and the first
sample above idle + half the burst's median is applied to every sample (`power.alignment_offset_ms`). Pulses run before
Phase A (`sync`), between Phase A and Phase B (`sync_b`) and at the end (`sync2`); the three offsets must agree within
200 ms (`power.alignment_drift_ms`) and the residual at every pulse must be within 200 ms (`power.alignment_check_ms`),
else stop and report.

**Energy over a window.** For `W = [a, b]`: `E(W) = Σ P_i × |[start_i, end_i] ∩ W|` over all samples, in joules
(mW × s ÷ 1000). For a set of windows (a ticket run's reading windows), `E` is the sum over the set.

## 3. Phase A: four answer kinds (server with every prompt cache off)

```sh
~/llama.cpp/build/bin/llama-server -m "<T7>/models/Qwen3-8B-Q4_K_M.gguf" \
  --jinja --reasoning-format deepseek --no-cache-prompt --cache-ram 0 -c 20480 -np 1 -ngl all --port 8080
```

Flags as `llama-server --help` prints them at build 11255 (`--no-cache-prompt`: "whether to enable prompt caching
(default: enabled)"; `-cram, --cache-ram N`: "0 - disable"); record the line as `server.phase_a.command` and the `--help`
text hash as `server.help_sha256`. **If any flag is missing from the Mac's `--help`, stop; do not substitute.**

**The cache trap (seg_08).** The cache is off three ways: `--no-cache-prompt`, `cache_prompt: false` in every request,
and `--cache-ram 0` (the host-RAM cache would copy about 2.3 GB of KV state inside the next request's window after a
long document). **Every Phase A request must return `timings.cache_n == 0`**; a request with `cache_n > 0` is discarded
and re-run; `checks.cache_n_all_zero` must be `true`.

Every request: `POST /v1/chat/completions`, `stream: false`, system `You are a helpful assistant.`, one user message,
`cache_prompt: false`, the request `seed`, the sampling of its mode and its `max_tokens`. Read
`choices[0].message.reasoning_content`, `.content`, `finish_reason`, `usage.prompt_tokens`, `usage.completion_tokens`,
`timings.cache_n`, `prompt_n`, `prompt_ms`, `predicted_n`, `predicted_ms`. Reasoning tokens: `POST /tokenize
{"content": <reasoning_content>}` → `len(tokens)`.

**Thinking switch and sampling** (Qwen3-8B model card, "Best Practices"): off = `chat_template_kwargs:
{"enable_thinking": false}`, `temperature 0.7, top_p 0.8, top_k 20, min_p 0`; on = `{"enable_thinking": true}`,
`temperature 0.6, top_p 0.95, top_k 20, min_p 0`.

| kind | thinking | user message (verbatim, `prompts.json`) | max_tokens | runs, seeds |
|---|---|---|---|---|
| `short` | off | `Why is the sky blue? Answer in two sentences.` | 256 | 20, seeds 0-19 |
| `think` | on | `Why is the sky blue? Answer in two sentences.` | 8192 | 10, seeds 0-9 |
| `long` | off | `Explain how a fridge keeps food cold, for a curious fifteen-year-old, in about 800 words.` | 2048 | 10, seeds 0-9 |
| `longctx` | off | the long document, two newlines, `Summarise the passage above in three sentences.` | 256 | 10, seeds 0-9 |

A `think` run ending with `finish_reason` = `length` is kept and counted in `answers.think.hit_cap`; more than two →
report before resolving. **Long document:** tokenize the source with `POST /tokenize`, keep the first 16,000 tokens,
`POST /detokenize` → the text; record `config.longctx.doc_tokens` (16,000) and `doc_sha256`; every `longctx` response
must report `timings.prompt_n` between 16,000 and 16,100 (`checks.longctx_prompt_n_ok`). **Fallback** if the series 1
file is missing: Project Gutenberg #100 (<https://www.gutenberg.org/cache/epub/100/pg100.txt>, needs the operator's OK
to download), everything after the `*** START OF` line, same cut; record the URL in `config.longctx.source`.

**Run order (rounds).** Ten rounds; each round runs two `short`, one `think`, one `long`, one `longctx`; round `r`
starts at kind number `r mod 4` in `short, think, long, longctx` (the second `short` follows the first). Seeds advance
per kind. Record `config.order`.

**Windows per request.** Wait 5 s (settle, not counted). **Answer window** `[t0, t1 + 1.0 s]` (request sent → one second
after the response, so the chip's tail counts). Wait 3 s, then an **idle window** of exactly the answer window's
length, sending nothing. Net joules = `E(answer) − E(idle)`. **Reading window** `[t0, t0 + prompt_ms]`, **writing
window** `[t0 + prompt_ms, t1]`, **tail** `[t1, t1 + 1 s]`, each net of the idle window's mean power × its length.
`writing.watts_net` = writing net joules ÷ writing seconds (never over the tail); per-token figures use writing net
joules only. Windows shorter than 5 samples (1 s) are `resolved: false` (only `longctx` resolves its reading).
**Warm idle:** if the median idle window after any kind is more than 20 % and 0.3 W above `idle.before.watts_median`,
lengthen that kind's gap to 10 s and re-run its runs once; still warm → `idle.by_kind.<kind>.settled` = false, report,
and the operator picks `joules_net` or `joules_net_vs_idle_before` for that kind (both are recorded per request).

**Idle baselines.** Before round 0: 2 minutes warm-up (three throwaway `short` requests), `sync`, then 5 minutes idle
(`idle.before`). After Phase A: the **block check** (100 `short` requests back to back, seeds 100-199, then one idle
window of the same total length; `block.short.joules_per_answer` = net ÷ 100, `block.short.watts_net` over the summed
writing windows; used only under alternative A). `idle.watts_median` = median power over every idle window of the run
(Phase A and B); `idle.drift` = `(idle.after − idle.before) ÷ idle.before`.

## 4. Phase B: the coding ticket in an agent loop, cache off and cache on

Stop the Phase A server. Start the Phase B server (powermetrics keeps running):

```sh
~/llama.cpp/build/bin/llama-server -m "<T7>/models/Qwen3-8B-Q4_K_M.gguf" \
  --jinja --reasoning-format deepseek --cache-ram 0 -c 32768 -np 1 -ngl all --port 8080
```

(The E3 demo server line plus `--cache-ram 0`, so no host-RAM copy lands inside a measured window; the slot's own prompt
cache stays available and each request switches it per arm.) Record as `server.phase_b.command`. Then `sync_b`
(section 2) and 3 minutes of idle (`idle.phase_b_before`).

**The ticket (verbatim, `TICKETS["easy"]` in `make_demo_repo.py`):** "Ticket: `slugify(title)` in `ledger/text.py` must
return the title in lower case, with leading and trailing spaces removed and every run of spaces replaced by one hyphen.
The tests in `tests/test_text.py` describe the behaviour. Make them pass. Do not edit anything under `tests/`. Check
with `python3 -m unittest discover -s tests -t .`." It is the ticket the coding episode's demo used (idea `b3f099d06421`,
`coding-demo-capture.json` `tickets.easy`), so its results there are a reference, not a part of this run.

**The loop** = the E3 demo's `run_small(ticket="easy", seed, variant="small")`, unchanged except for the timing hooks
and the per-arm `cache_prompt` field: system prompt `SYSTEM` of `run_demo.py` (the plain one, not the no-sed variant),
tools = the `shell` tool only, `MAX_TURNS` 30, shell timeout 30 s, tool output truncated to 4,000 characters, one
fixed nudge on a plain reply without DONE, `max_tokens` 2048 per call, thinking off, the thinking-off sampling of
section 3, request seed = `run_seed × 100 + turn_index`, a fresh copy of the demo repo per run, deleted after grading.

| arm | per-request `cache_prompt` | check on every request | runs, seeds |
|---|---|---|---|
| `nocache` | `false` | `timings.cache_n == 0` (else discard the whole run and re-run it once) | 5, seeds 0-4 |
| `cached` | `true` | from the second call on, `timings.cache_n > 0`; a call with `cache_n == 0` after turn 1 is recorded (`agent.cached.cache_misses`), not discarded | 5, seeds 0-4 |

**Order (ten runs):** seed 0 `nocache`, seed 0 `cached`; seed 1 `cached`, seed 1 `nocache`; seed 2 `nocache`, seed 2
`cached`; seed 3 `cached`, seed 3 `nocache`; seed 4 `nocache`, seed 4 `cached` (the arm that goes first alternates by seed,
so warmth does not favour one arm). Record `config.agent.order`. Before every `nocache` run
the harness sends one throwaway 1-token request with a different system prompt so the slot holds nothing from the
previous run (also recorded); before every `cached` run the same, so each `cached` run starts cold and only reuses its
own turns.

**Windows per ticket run.** Wait 5 s. **Run window** `[t_start, t_end + 1 s]` (first request sent → one second after the
last response or the last tool call). Wait 3 s, then an **idle window** of the same length. Net joules = `E(run) −
E(idle)`. **Contaminated idle (added 2026-10-10 after the run):** an idle window whose mean power is more than 1 W above `idle.watts_median`, or that holds any 5 s stretch above 5 W, is flagged (`agent.<arm>.runs[i].idle_contaminated`) and the run is re-run once; if it is not, the capture keeps the own-window net, reports `joules_net_vs_idle_before` beside it, and seg_15 says so (the run's cache-off seed 2 window would have been flagged: 4.84 W mean, CPU about 37 W for about 20 s). Same rule for Phase A answer windows (section 3). Inside the run, per model call `k`: reading `[t0_k, t0_k + prompt_ms_k]`, writing `[t0_k + prompt_ms_k,
t1_k]`; **tools** = the run window minus all reading and writing windows (shell commands, the harness, the 1 s tail).
Each part gets its own net joules (idle mean power × its total length subtracted). A reading window shorter than one
sample still counts its overlap share (the sum over 30 calls is what matters); record `agent.<arm>.reading_resolved_share`
(the share of reading seconds inside windows of 1 s or longer).

**Grade.** `grade()` of `run_demo.py`: restore the pristine `tests/` (and flag `tests_modified`), run `python3 -m unittest
discover -s tests -t . -v` in the run dir with a clean env, **pass = exit code 0 and 4 of 4 tests ok**.

**Per run (`bill-agent-runs.jsonl`):** `arm, seed, passed, tests_passed, tests_modified, turns, seconds, stuck, nudged,
prompt_tokens_sum (Σ usage.prompt_tokens), completion_tokens_sum, prompt_n_sum (Σ timings.prompt_n), cache_n_sum,
max_prompt_tokens (largest single request), joules_net, joules_net_vs_idle_before, reading{seconds, joules_net},
writing{seconds, joules_net, watts_net}, tools{seconds, joules_net}, idle_window_watts_mean, transcript_sha256, transcript
(truncated as in E3)`. **Per call (`bill-agent-turns.jsonl`):** `arm, seed, turn, t0_unix, t1_unix, usage{...}, timings{cache_n,
prompt_n, prompt_ms, predicted_n, predicted_ms}, tool_seconds, context_chars{ticket, tool_outputs, replies}` (for the
growing-context bar in seg_09; shares by characters, labelled so).

After Phase B: `sync2`, then 5 minutes of idle (`idle.after`).

## 5. Money and scale constants (stated, not measured; re-read on the run day)

| constant | value | source (read 2026-10-09) |
|---|---|---|
| tariff | 0.1831 USD per kWh | EIA Electric Power Monthly, Table 5.6.A, residential, U.S. Total, July 2026 (released 2026-09-24), <https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a> |
| maker's price | input 0.072, output 0.287 (thinking off), output 0.717 (thinking on), USD per 1M tokens | Alibaba Cloud Model Studio, Models and pricing, `qwen3-8b`, Germany (Frankfurt), <https://www.alibabacloud.com/help/en/model-studio/model-pricing> ("Last Updated: Oct 09, 2026") |
| Claude Opus 5.5 | input 4, output 20, cache hit 0.20 USD per 1M tokens | <https://platform.claude.com/docs/en/about-claude/pricing> |
| Claude Haiku 5.5 | input 0.10, output 0.50, cache hit 0.01 USD per 1M tokens (prompts up to 100,000 tokens; above that 0.50 / 2.50) | the same page |
| household | 10,791 kWh per year | EIA FAQ, <https://www.eia.gov/tools/faqs/faq.php?id=97&t=3> (2022 data) |
| scale | 1,000,000 coding tickets like the `nocache` median run | a stated number for illustrative arithmetic, labelled ARITHMETIC on screen; not a measurement, not any company's traffic |

If a price changed on the run day, record the new value and date under `money.price.*`, and update the spoken prices
(seg_02, seg_14) and their claims rows before resolution. Token counts are the server's (`usage` / `timings`); the
cloud's own tokenizer and chat template may count a few tokens differently (`money.token_basis` says so), and Claude
would use different tokens for the same job (seg_14 says so).

## 6. The factory tier ledger (not part of the Mac run)

`evidence/tier-ledger-factory-2026-10-09.csv` is a read-only export of the board view `tier_ledger` (verification plugin,
<card>/<card>/<card>) taken 2026-10-09, **filtered to `factory-*` presets** (other boards and presets are not shown and
not named). Columns as the view defines them: `dispatched` distinct cards fed, `merged` cards with a merged event,
`attempts` spawned work sessions, `veto_rounds` send-backs, `rebase_rounds`, `failed = dispatched − merged − oversized`,
and three medians over a class's merged cards; in this export the medians repeat across the `prose`/`tests` rows of
the same preset and label set (they are per preset and label set, both check styles together), and `0.0` tokens means
"not recorded". The view is report-only until a class has roughly fifty merged runs (plugin README). On resolution day,
re-export with `<board-cli> criteria query "select * from tier_ledger"` on the factory, filter to `factory-*` presets, and if
any narrated row changed, update seg_12/seg_14 and their claims rows.

## 7. The capture (`bill-capture.json`, schema `ep22-bill-capture-2`)

```text
schema_version, captured_at_utc
machine{chip, ram_bytes, os, power, thermal_pressure (per round and per ticket run)}
llama_cpp{output}; model{file, size_bytes, sha256}; harness{sha256: {file: hash}}; prompts{sha256}
server{phase_a{command}, phase_b{command}, help_sha256}
power{tool: "powermetrics", command, interval_ms, help_sha256, sampler_keys, keys_sha256, metric, dram_key,
      alignment_method, alignment_offset_ms, alignment_drift_ms, alignment_check_ms, samples_n, raw_sha256}
config{runs{short, think, long, longctx}, seeds, order, max_tokens, sampling, cache_prompt: false, cache_ram: 0,
       longctx{source, source_sha256, doc_tokens, doc_sha256},
       agent{ticket: "easy", ticket_text, builder_sha256, system_prompt, max_turns: 30, shell_timeout_s: 30, trunc_chars: 4000,
             max_tokens: 2048, runs{nocache: 5, cached: 5}, seeds, order, baseline_failing, reference_solution_passes}}
checks{cache_n_all_zero (Phase A and the nocache arm), longctx_prompt_n_ok, cached_arm_hits (calls after turn 1 with cache_n > 0 ÷ all such calls), alignment_ok}
idle{before, phase_b_before, after: {watts_median, seconds}, watts_median, drift, by_kind{short, think, long, longctx, agent_nocache, agent_cached: {watts_median, settled}}}
answers.<kind> for kind in short, think, long, longctx:
    {n, seconds_median (t1 − t0, without the tail), prompt_n_median, predicted_n_median, reasoning_tokens_median (think),
     joules_median, joules_iqr, spread (= joules_iqr ÷ joules_median), wh_median, joules_net_vs_idle_before_median,
     tail{seconds_median, joules_net_median}, decode_joules_median, decode_watts_median, prefill_joules_median,
     prefill_seconds_median, prefill_watts_median (longctx), prefill_share (= Σ reading net ÷ Σ net), hit_cap (think), runs[...]}
block{short{n: 100, seconds, joules_net, joules_per_answer, watts_net, vs_median}}
agent.<arm> for arm in nocache, cached:
    {n, passed, turns_median, seconds_median, minutes_median (= seconds_median ÷ 60), prompt_tokens_median (Σ usage.prompt_tokens per run),
     completion_tokens_median, prompt_n_sum_median, cache_n_sum_median, max_prompt_tokens,
     joules_median, joules_iqr, spread, joules_net_vs_idle_before_median,
     reading{joules_median, seconds_median}, writing{joules_median, seconds_median, watts_median}, tools{joules_median, seconds_median},
     prefill_share (= Σ reading net ÷ Σ net over the arm's runs), reading_resolved_share,
     fresh_read_share (= Σ prompt_n ÷ Σ usage.prompt_tokens over the arm's runs), cache_misses (cached), runs[...]}
agent{passed_total, runs_total: 10}
derived{think_vs_short_multiple, longctx_vs_short_multiple, joules_per_thousand_written (Σ long writing net ÷ Σ long predicted_n × 1000),
        joules_per_thousand_read (Σ longctx reading net ÷ Σ longctx prompt_n × 1000), per_token_written{short, think, long},
        per_token_spread (= (max − min) ÷ min), per_token_fit{slope_j_per_token, intercept_j, r2}, write_read_ratio,
        bulb_seconds_short (= answers.short.joules_median ÷ 10, block value under alternative A), bulb_seconds_think,
        agent_read_write_ratio (= agent.nocache.prompt_tokens_median ÷ agent.nocache.completion_tokens_median),
                agent_cached_vs_nocache (= agent.cached.joules_median ÷ agent.nocache.joules_median),
        agent_joules_per_thousand_read (= Σ agent.nocache reading net joules ÷ Σ agent.nocache usage.prompt_tokens × 1000),
        reading_j_per_thousand_by_depth (the nocache calls' reading net joules per thousand prompt tokens in prompt-length bins 0-4k, 4-8k, 8-16k, 16-32k, from bill-agent-turns.jsonl)}
money{tariff_usd_per_kwh: 0.1831, tariff_source, price{maker{input, output, output_thinking, region, read_at},
      opus_5_5{input, output, cache_hit, read_at}, haiku_5_5{input, output, cache_hit, prompt_limit: 100000, read_at}}, token_basis,
      short{local_usd, api_usd, local_usd_per_thousand, api_usd_per_thousand, ratio},
      agent_nocache{local_usd, api_usd, opus_usd, haiku_usd, haiku_tier_ok (max_prompt_tokens ≤ 100000)},
      agent_cached{local_usd, api_usd_with_cache_hits_at_base (no maker cache price is used), opus_usd_cached (prompt_n at input, cache_n at cache_hit)}}
scale{tickets: 1000000, kind: "agent_nocache", agent_kwh, home_kwh_per_year: 10791, agent_home_years, agent_api_usd, agent_opus_usd}
examples{cold_open{agent_seed, agent_prompt_tokens, agent_completion_tokens, within_15pct, recording}, longctx_recording}
```

**Money arithmetic (COMPUTED).** `local_usd = joules ÷ 3,600,000 × 0.1831`; maker `api_usd = (prompt × 0.072 + completion ×
0.287) ÷ 1,000,000`; `opus_usd = (prompt × 4 + completion × 20) ÷ 1,000,000`; `haiku_usd = (prompt × 0.10 + completion ×
0.50) ÷ 1,000,000` (valid only if `haiku_tier_ok`; else use 0.50 / 2.50 and say so); for the ticket, `prompt` and `completion`
are `agent.nocache.prompt_tokens_median` and `completion_tokens_median`; `*_per_thousand = × 1,000`.
**Scale arithmetic (ARITHMETIC).** `agent_kwh = 1,000,000 × agent.nocache.joules_median ÷ 3,600,000`; `agent_home_years =
agent_kwh ÷ 10,791`; `agent_api_usd = 1,000,000 × money.agent_nocache.api_usd`; `agent_opus_usd = 1,000,000 ×
money.agent_nocache.opus_usd`. Every median is over the kind's or arm's recorded runs.

## 8. Runtime (estimate) and cost

Phase A ≈ 40 min for ten rounds + 14 min warm-up, sync and the 5-minute idle + 8 min block check (the r3 estimate,
from the series 1 Part 4 speeds). Phase B per seed: a `nocache` run ≈ 4-5 min (about 70,000 tokens re-read at a few
hundred tokens a second, plus about 2,000 written; from the E3 demo's easy runs, `coding-demo-runs.jsonl`, which ran with
the cache on in 1-2 minutes) plus an idle window of the same length, a `cached` run ≈ 1-2 min plus its idle window,
so ≈ 12-15 min per seed and ≈ 60-75 min for five seeds; sync, idles and setup ≈ 15 min. Screen recordings and checks
≈ 30-45 min. **Total ≈ 3 to 4 hours of the operator's Mac, local only, no paid call.** If time is short, Phase B may run
3 seeds per arm (say so in `config.agent.runs`; then seg_05's "Ten runs. Five with the server's cache off, and five with it on.",
seg_09's "… of ten runs." and seg_15's "One ticket, ten runs, is a story, not a benchmark." change to six runs and three
per arm, with their claims rows).

## 9. Operator steps

1. Section 1 checks (machine, power state, quiet Mac, build, model hash, long document, `run_ticket.py verify`); close
   every other app; fix the display brightness; start `caffeinate -dimsu` in a spare tab.
2. Section 2 step 1 (`sudo`), write `power_keys.json`.
3. Terminal 1: the powermetrics line of section 2 step 2 (`sudo`); leave it running.
4. Terminal 2: start the Phase A server (section 3), then `python3 ~/ep22-lab/bill/harness.py phase-a` (warm-up, sync,
   idle before, ten rounds, block check). Do not touch the Mac. Then stop the server (Ctrl-C).
5. Terminal 2: start the Phase B server (section 4), then `python3 ~/ep22-lab/bill/run_ticket.py phase-b` (sync_b, idle,
   ten ticket runs in the section 4 order, sync2, idle after). Do not touch the Mac.
6. **Screen recordings** (powermetrics still sampling; recordings are b-roll, never measurements):
   (a) cold open: `python3 ~/ep22-lab/bill/run_ticket.py show --arm nocache --seed <examples.cold_open.agent_seed>` — the
   agent transcript on the left, `live_meter.py` on the right (tails `pm.plist`, shows watts above idle only: no joule total, because the recording
   run is a re-run under screen-recording load and its joules would not equal the spoken medians; and two counters
   TOKENS IN / TOKENS OUT from the server's per-call usage); the seed is the
   `nocache` run whose tokens in and out are both closest to the arm's medians; its recorded token totals go in
   `examples.cold_open.*` and must be within 15 % of the medians, else record the next-closest seed (at most three);
   (b) `harness.py show --kind longctx --seed 0` with the same meter (seg_08 reading/writing split);
   (c) optional: one `short` and one `think` answer for the seg_06 b-roll. Then stop powermetrics (Ctrl-C).
   **Run 2026-10-10:** not done yet (`examples.cold_open.recording` and `examples.longctx_recording` are null). The rule picked
   seed 2 (`examples.cold_open.agent_seed`; its totals, 42,768 in and 1,176 out, are both arm medians; next closest 4, 0). Seed 2
   ended with 1 of 4 tests passing, so the cold open and seg_09 show no pass or fail for it; the re-run's own totals must still be
   within 15 % of the medians. **Footage decision (round 6):** the cold open and seg_09 use a REPLAY of the measured seed-2 run rendered
   from `bill-agent-runs.jsonl` (line 5) / `bill-agent-turns.jsonl` / `bill-power-samples.csv.gz`, tagged MY RUN · REPLAY; a camera
   re-run replaces it only if its `transcript_sha256` equals the measured run's (8d336d9bd93983dc…).
7. `python3 ~/ep22-lab/bill/harness.py reduce` (alignment check, windows, medians, money, scale →
   `bill-capture.json`, `bill-power-samples.csv.gz`; it reads both phases' run files).
8. Secret scan and path redaction as in the earlier EP22 captures (`~` → `~`, `<T7>` → `<T7>`),
   copy the five evidence files into `episodes/5a39a7f27964/evidence/`, data-only PR.
   **Run 2026-10-10:** redaction and secret scan done by `~/ep22-lab/e6/tools/stage_evidence.py` into `~/ep22-lab/e6/v2/evidence-final/`
   (the five files, the ledger export and MANIFEST.json with each file's sha256 before and after redaction; scan CLEAN); the
   transcripts' `transcript_sha256` were taken before redaction. No PR opened (operator step).

## 10. Label → capture key → spoken form (how the placeholders get filled)

Resolve with `models.resolve_placeholder_results(contract, {label: spoken value})` (spoken values spelled out, rounded;
the exact figure goes on screen), apply the brief's alternative wording where its condition holds, recompute
`est_seconds` per segment, the clip lengths and the hook variants (`pipeline.script.estimate_seconds`), add a
**measured:** note to every claims row, fill the brief's "Resolved outcome" table, re-run the validators, then a fresh
grader round. The examples below are the guessed outcome, **not results**; the last two columns, added 2026-10-10, are the
measured value and the spoken form the script now uses (same rules: words, units in the spoken form, about/almost/over/under
for rounding). `agent_passed` came out two (one per arm), not the guessed one: seg_09 reads "Two of ten runs. The bill came
either way." and seg_13 adds "One run in five passed either way. Too few to judge quality." No alternative (A)-(G) fired. `agent_joules_nocache` and its children (`agent_local_cost`, `scale_kwh_agent`,
`scale_home_share_agent`) read 12-14 % low against a clean idle (the seed-2 idle window held a CPU burst; 4,427 J against the
run-start idle, 4,509 J against the own-window median idle); the pre-registered own-window net is kept and seg_15 discloses it. **Cold-open cap:** `agent_written_tokens` and `agent_read_tokens` are spoken in seg_00 (and `hv-contradiction`), whose other words leave room for at most seven words for the two together (34-word cap, payoff "four times more" before 10 s at 2.35 words a second); round them to fit (for example "about two thousand", "about ninety thousand", "over a hundred thousand"), exact values on screen.

| label | capture key | spoken form (example) | measured 2026-10-10 | resolved spoken form |
|---|---|---|---|---|
| `agent_written_tokens` | `agent.nocache.completion_tokens_median` | "about two thousand" | 1176 | "about twelve hundred" |
| `agent_read_tokens` | `agent.nocache.prompt_tokens_median` | "about seventy thousand" | 42768 | "about forty-three thousand" |
| `agent_turns_nocache` | `agent.nocache.turns_median` | "thirty" (the script adds "turns") | 22 | "twenty-two" |
| `agent_minutes_nocache` | `agent.nocache.minutes_median` | "about four and a half minutes" | 2.66608 | "under three minutes" |
| `agent_read_write_ratio` | `derived.agent_read_write_ratio` | "about thirty-five" | 36.3673 | "about thirty-six" |
| `agent_joules_nocache` | `agent.nocache.joules_median` | "about six and a half thousand" (the script adds "joules") | 3895.59 | "almost four thousand" |
| `agent_prefill_share_nocache` | `agent.nocache.prefill_share` | "about four fifths" | 0.836636 | "about eighty-four percent" |
| `agent_passed` | `agent.passed_total` (of `agent.runs_total`) | "One" (sentence start; the script adds "of ten runs"; zero: "None") | 2 | "Two" |
| `agent_fresh_read_share` | `agent.cached.fresh_read_share` | "about one in fourteen" | 0.0689643 | "about one in fourteen" |
| `agent_joules_per_thousand_read` | `derived.agent_joules_per_thousand_read` | "seventy-five" (the script says "about") | 82.7305 | "eighty-three" |
| `agent_joules_cached` | `agent.cached.joules_median` | "about one thousand seven hundred" | 1474.77 | "about fifteen hundred" |
| `agent_local_cost` | `money.agent_nocache.local_usd` | "about a thirtieth of a cent" | 0.000198134 | "about a fiftieth of a cent" |
| `agent_api_cost` | `money.agent_nocache.api_usd` | "about half a cent" | 0.00341681 | "about a third of a cent" |
| `agent_opus_cost` | `money.agent_nocache.opus_usd` | "about thirty-two cents" | 0.194592 | "about nineteen cents" |
| `agent_haiku_cost` | `money.agent_nocache.haiku_usd` | "under a cent" | 0.0048648 | "about half a cent" |
| `scale_kwh_agent` | `scale.agent_kwh` | "about one thousand eight hundred" (the script adds "kilowatt-hours") | 1082.11 | "almost eleven hundred" |
| `scale_home_share_agent` | `scale.agent_home_years` | "about a sixth of a year of one home" (one or more: "about two years of one home") | 0.100279 | "about a tenth of a year of one home" |
| `scale_api_usd_agent` | `scale.agent_api_usd` | "about five and a half thousand dollars" | 3416.81 | "about three thousand four hundred dollars (on screen only, not spoken)" |
| `scale_opus_usd_agent` | `scale.agent_opus_usd` | "about three hundred and twenty thousand dollars" | 194592 | "almost two hundred thousand dollars" |
| `idle_watts` | `idle.watts_median` | "about one watt" (the unit is part of the spoken form) | 1.01838 | "about one watt" |
| `seconds_short` | `answers.short.seconds_median` | "about two seconds" | 1.48818 | "about one and a half seconds" |
| `joules_short` | `answers.short.joules_median` (block value under alternative A) | "about fifty" (the script adds "joules") | 33.8296 | "about thirty-four" |
| `bulb_seconds_short` | `derived.bulb_seconds_short` | "about five seconds" | 3.38296 | "about three and a half seconds" |
| `bulb_seconds_think` | `derived.bulb_seconds_think` | "about half a minute" | 12.7943 | "about thirteen seconds" |
| `tokens_think` | `answers.think.reasoning_tokens_median` | "about four hundred" | 157.5 | "about a hundred and sixty" |
| `joules_think` | `answers.think.joules_median` | "about two hundred and eighty" | 127.943 | "about a hundred and thirty" |
| `think_vs_short_multiple` | `derived.think_vs_short_multiple` | "about six" (the script adds "times" in seg_06; seg_16 reads "multiplied it by about six") | 3.78199 | "about four" |
| `watts_short` | `answers.short.decode_watts_median` | "About twenty-five" (sentence start: capital) | 22.6599 | "About twenty-three" |
| `watts_think` | `answers.think.decode_watts_median` | "about twenty-five" | 24.7481 | "about twenty-five" |
| `tokens_long` | `answers.long.predicted_n_median` | "about one thousand one hundred" | 1031.5 | "about a thousand" |
| `joules_long` | `answers.long.joules_median` | "about six hundred" | 658.356 | "about six hundred and sixty" |
| `joules_per_thousand_written` | `derived.joules_per_thousand_written` | "five hundred and fifty" (the script says "about") | 615.919 | "six hundred and twenty" |
| `per_token_spread` | `derived.per_token_spread` | "fifteen percent" | 0.184346 | "about eighteen percent" |
| `joules_longctx` | `answers.longctx.joules_median` | "about two thousand" | 1927.3 | "almost two thousand" |
| `longctx_vs_short_multiple` | `derived.longctx_vs_short_multiple` | "about forty" | 56.9709 | "about fifty-seven" |
| `prefill_share_longctx` | `answers.longctx.prefill_share` | "about ninety-five percent" | 0.95369 | "about ninety-five percent" |
| `joules_per_thousand_read` | `derived.joules_per_thousand_read` | "a hundred and twenty-five" (the script says "about") | 114.384 | "a hundred and fourteen" |
| `write_read_ratio` | `derived.write_read_ratio` | "about four" | 5.38467 | "over five" |
| `cost_short_thousand` | `money.short.local_usd_per_thousand` | "about a quarter of a cent" | 0.00172061 | "about a sixth of a cent" |
| `api_cost_short_thousand` | `money.short.api_usd_per_thousand` | "about two cents" | 0.017372 | "about one point seven cents" |
| `short_spread` | `answers.short.spread` | "about ten percent" | 0.0756948 | "about eight percent" |

## 11. Risks

- **powermetrics key names differ.** Section 2 step 1 prints them; the harness refuses to run without a combined or
  summable chip value. Never guess a key.
- **powermetrics is an estimate.** Called chip power, never wall power, never compared across devices.
- **Too noisy per short answer.** `answers.short.spread` over 0.5 or any negative net → alternative A (block check).
- **Background load.** `idle.watts_median` above 5 W or `idle.drift` above 0.3 → stop, find it (`sudo powermetrics
  --show-process-energy -n 1`), re-run the set.
- **Thermal drift.** Rotation (Phase A) and alternating arm order (Phase B) spread it; `machine.thermal_pressure`,
  per-round medians and `idle.drift` are recorded; report a >20 % rise of the last three rounds' `long` joules.
- **Cache reuse leaking into the cache-off sets.** Any `cache_n > 0` in Phase A or the `nocache` arm discards the
  request or run; the slot is flushed with a throwaway request before every ticket run.
- **The cached arm misses its cache.** Recorded as `agent.cached.cache_misses`; if more than a fifth of calls after
  turn 1 miss, report before resolving (seg_13's "Now it read only … of the tokens it was sent." would need a rewrite).
- **The two arms take different paths.** Same seeds, but cache reuse can change the arithmetic order and so the
  sampled tokens; the arms are compared by median per run, and `fresh_read_share` is computed within the cached arm
  only, so it does not depend on the paths matching. Report the per-seed turn counts side by side.
- **Reading cost rises with depth.** Per token, reading a deeper context costs more (Kaplan et al. 2020, eq. 2.2 adds a 2·n_layer·n_ctx·d term to the 2N per token; on Metal the measured slow-down with depth is larger than that term, so the bins, not the formula, carry the comparison), so seg_08's long-document figure (`derived.joules_per_thousand_read`) and
  seg_13's ticket figure (`derived.agent_joules_per_thousand_read`) are different keys; the seg_13 card always shows
  both figures side by side (DOCUMENT, 16,000 DEEP · TICKET, UP TO N DEEP, N = `agent.nocache.max_prompt_tokens` rounded to the thousand; the seg_13 cue) from `reading_j_per_thousand_by_depth`, so the
  viewer sees why they differ.
- **Ticket runs hit the 30-turn cap.** Expected for most runs (the E3 demo: 7 of 10 easy runs used all 30 turns, one used 29). The
  energy per run is still the energy of that run; the pass/fail line says how it ended.
- **Tests edited by the model.** `grade()` restores the pristine tests before grading and flags `tests_modified`.
- **Sandbox escapes / runaway processes.** The demo sandbox kills each command's process group; `run_ticket.py`
  refuses to start if another llama-server runs; no network inside the sandbox.
- **Clock alignment.** Three sync pulses; offsets within 200 ms or stop.
- **Prices change.** Re-read on the run day (section 5).
- **Sudo.** Only powermetrics; the operator types it; the harness never asks for a password and never runs as root.
