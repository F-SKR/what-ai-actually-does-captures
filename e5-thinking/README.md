# Episode 5: what AI does when it thinks (`e5-thinking`)

**Question**: what does thinking add, what does it cost, and does the famous speed trick (speculative decoding) help? Qwen3-8B Q4_K_M, 20 puzzles with one checkable answer each (word problems, logic puzzles and short Python programs), three runs a side with thinking on and off (120 runs a side), five thinking budgets (256 to 4,096 tokens), then a speculative-decoding grid (no drafting, a Qwen3-0.6B draft model with 3 and 8 draft tokens, and n-gram drafting) over four kinds of job.

## Files

| file | what it is |
|---|---|
| `data/thinking-capture.json` | the summary (schema `ep22-thinking-capture-1`): `think_ab` (think against no-think: successes, token multiple, time multiple, puzzles helped and hurt, by kind, by puzzle), `budget` (`budgets`, `rows` with successes per thinking budget, `unlimited`, `knee`), `spec` (the grid: `cells`, `baseline_tps`, `draft_acceptance`, `ngram`, `lossless` = `pairs`, `identical` and `mismatches`, the word-for-word comparison with the plain run), `examples` |
| `data/thinking-runs.jsonl` | 320 lines, one per run: `part` (`A`: think on/off, 60 runs a side; `B`: thinking budget, 40 runs at each of 256, 512, 1,024, 2,048 and 4,096), `puzzle_id`, `kind`, `seed`, `mode`, `budget`, token counts (`reasoning_tokens`, `answer_tokens`), `wall_s`, `predicted_per_second`, `hit_cap`, `answer`, `correct`, and the full `reasoning_content` and `content` |
| `data/spec-runs.jsonl` | 144 lines, one per speculative-decoding request: `method`, `workload`, `repeat`, `predicted_n`, `predicted_per_second`, `draft_n`, `draft_n_accepted`, `acceptance_line` (the server's draft-acceptance log line), hashes of the output |
| `data/mismatch-details.json` | the word-for-word comparison of drafted outputs against the plain run (the 5 differences, all from the draft model) |
| `harness/puzzles.py` | the 20 puzzles and their answers; `harness.py` runs parts A and B; `specgrid.py` and `spec_prompts.py` run part C; `mismatch_details.py`; `make_capture.py` builds the capture |
| `claims.md`, `experiment-plan.md` | the claims table and the plan |

## How to read it

- Think on against off: `think_ab.nothink` and `think_ab.think` (54 of 60 without thinking against 60 of 60 with it), `token_multiple` (about 6.5) and `time_multiple` (about 6).
- Budget: `budget` (37 of 40 at 256, 40 of 40 by 1,024). A run that hit the budget is cut at the stop line in `harness.py`.
- Speculative decoding is only "on" when the server log shows a draft-acceptance line: in build 11255 the method defaults to none. `spec-runs.jsonl` keeps `acceptance_line` so you can check that for every request. The capture's `command` fields for each server start show the settings; the raw server logs are not published.
- Scoring overrides and hand checks are listed in `think_ab.scoring_overrides` and `scoring_hand_check`.

## Limits specific to this episode

One small model at 4 bits on one Mac, twenty puzzles, three runs a side. Nothing here says how the large cloud models think or how their servers decode.
