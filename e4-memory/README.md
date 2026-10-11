# Episode 4: where an AI keeps what it knows (`e4-memory`)

**Question**: where does a model keep what it knows, and where does it forget? Four places, tested on Qwen3-8B Q4_K_M: the window (20 made-up facts hidden in a Sherlock Holmes book, 2,000 to 31,000 tokens), a summary (a 30-turn bakery job with 12 planted facts and a forced summary at turn 20), a lookup (a plain word search over the messages, plus a prompt-cache test), and the weights (a quick LoRA that teaches one made-up fact, trained on an MLX 4-bit copy).

## Files

| file | what it is |
|---|---|
| `data/memory-capture.json` | the summary (schema in `schema_version`): `haystack` (the book is Project Gutenberg #1661, referenced by hash, not included), `needle` (`config`, `cells`, `summary`, `comparisons`, `read_seconds_median_31k`: hits per depth and context size, same words against paraphrase), `prefill` (the prompt-cache re-read test), `compaction` (`arms`: full history against summary against none; token counts before and after the summary; loss by category), `lookup`, `lora` (`probes`, `collateral`, `bleed`, `train`), `examples` |
| `data/memory-trials.jsonl` | 297 lines, one per run: `test` (`needle`, `needle_lexcheck`, `compaction`, `prefill`), `arm`, `repeat`, `per_turn` (prompt tokens, cache tokens, milliseconds per turn), `replies` (what the model answered) |
| `data/lora-result.json` | the LoRA test: the model's answer to each question (the made-up-fact probes and the plain control questions) before training (`before`) and after (`after`), and the training command and time (`train`: `mlx_lm.lora` on `mlx-community/Qwen3-8B-4bit`, 200 iterations, 57 seconds) |
| `data/lora-data/train.jsonl`, `valid.jsonl` | the 40 training examples and the validation examples |
| `data/chat_template.jinja` | the Qwen3 chat template used (Apache 2.0, from the model) |
| `harness/` | `common.py` (server start, helpers, scoring), `needle.py`, `prefill.py`, `compaction.py`, `lora_run.py`, `capture.py` (builds the capture), `harness.py` (entry point: `needle`, `prefill`, `compaction`, `lora`, `capture`), `plan_data.json` (the made-up facts and questions), `*_overrides.json` |
| `claims.md`, `experiment-plan.md` | the claims table and the plan |

## How to read it

- Needle: for each context size and depth, count of correct answers out of 60; "same words" and "paraphrase" are two question arms (`arm` in the trials file). 60 of 60 at 31,000 tokens in the same words; 57 of 60 at 2,000 and 52 of 60 at 31,000 in different words.
- Re-read tax: `prefill` has per-turn `prompt_n` (tokens actually processed) and `cache_n` (tokens reused); a `first_diff_token` shows where the cache stopped matching (the line with the current time at the top).
- LoRA: `lora` in the capture and `lora-result.json`: 0 of 20 to 20 of 20 on the new fact, 46 of 48 plain questions lost by the strict answer-matching rule.
- The made-up facts are fiction (a bakery, a pear tree planted in 1931, a prize cup behind a piano); any email address, name or place in the replies is invented.

## Limits specific to this episode

One 8-billion-parameter model at 4 bits, made-up facts, a longest haystack of 31,000 tokens and a quick LoRA run. The dip in the middle from the Lost in the Middle paper did not show up on this model. The 46 of 48 uses a strict matching rule. None of this says how a chatbot you use is built.
