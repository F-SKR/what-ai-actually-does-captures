# Experiment plan — EP22-E5 thinking and speculative decoding (idea `6b2bf8d7c396`)

What this run produces: one capture, `episodes/6b2bf8d7c396/evidence/thinking-capture.json`
(schema `ep22-thinking-capture-1`), plus two per-run files,
`episodes/6b2bf8d7c396/evidence/thinking-runs.jsonl` (parts A and B) and
`episodes/6b2bf8d7c396/evidence/spec-runs.jsonl` (part C), and one llama-server log per
part C server, `episodes/6b2bf8d7c396/evidence/spec-logs/<method>.log`. Every
`PLACEHOLDER_RESULT[label]` in `script.yaml` resolves from a key in the capture (table in
section 9), and every `PENDING:` pointer in `claims.md` names one of these keys. Nothing
here calls a paid provider; the whole run is local on the operator's Mac.

The episode asks two questions. **What does thinking cost, and what does it buy?** (parts A
and B: the same model with thinking on and off, then with a thinking budget.) **Can a speed
trick buy the time back?** (part C: speculative decoding with no trick, a draft model and
n-gram drafting, on four kinds of job, one of them the thinking itself.)

Write the harness as `~/ep22-lab/thinking/harness.py` on the Mac, in the style of the
earlier EP22 harnesses (`~/ep22-lab/shutdown/harness.py`, `~/ep22-lab/agents/harness.py`:
plain `urllib`/`requests` calls to `llama-server`, one JSON line per request). Where an
existing harness already does something a different way (file layout, logging), **keep the
existing way and record it in the capture**; the keys below, not the wording, are the
contract.

## 1. Machine, build, models

| item | value | how to check before the run |
|---|---|---|
| machine | MacBook, Apple M4 Pro, 24 GiB (the series 1 machine) | `sysctl -n machdep.cpu.brand_string`, `sysctl -n hw.memsize` → `machine.chip`, `machine.ram_bytes`; `pmset -g` → `machine.power` (on mains power, Low Power Mode off; refuse to start otherwise) |
| llama.cpp | build 11255, commit 31385c9ce (the series 1 build) | `~/llama.cpp/build/bin/llama-server --version` must print `version: 0.5.0-dev (build 11255, commit 31385c9ce)` → `llama_cpp.output` |
| target model | `Qwen3-8B-Q4_K_M.gguf`, 5,027,784,512 bytes, sha256 `120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4` (the same file as `episodes/ad65fb76a5bb/evidence/ais-lab2-memory-speed-capture.json` `quality.models[2]` and `episodes/ee7fcc52450f/evidence/ais-lab1-tokens-capture.json` `model`) | `shasum -a 256 "<T7>/models/Qwen3-8B-Q4_K_M.gguf"` → `model.sha256`, `model.size_bytes`; refuse to start on a mismatch |
| draft model (part C only) | `Qwen3-0.6B-Q8_0.gguf` from the official repo `Qwen/Qwen3-0.6B-GGUF`, 639,446,688 bytes, sha256 `9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031` (Hugging Face API `api/models/Qwen/Qwen3-0.6B-GGUF/tree/main`, read 2026-10-06; the LFS oid is the file's sha256) | download `https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q8_0.gguf`; `shasum -a 256` → `draft_model.sha256`, `draft_model.size_bytes`; refuse on a mismatch |
| harness | `~/ep22-lab/thinking/harness.py`, `puzzles.json` (section 3), `spec_prompts.json` (section 5) | `shasum -a 256` of each → `harness.sha256`, `puzzles.sha256`, `spec_prompts.sha256` |

**Vocabulary check (before part C, required).** A draft model is only usable when its
vocabulary matches the target's (llama.cpp `common/speculative.cpp`
`common_speculative_are_compatible` at commit 31385c9ce: same vocabulary type, same BOS/EOS
handling, sizes within 128 entries, and identical token text from id 5 up). An earlier check
matched `Qwen3-0.6B` against `Qwen3-4B`; it was never hashed against the 8B file. Hash it:

```sh
cd ~/llama.cpp && python3 - <<'PY'
import hashlib, sys
sys.path.insert(0, 'gguf-py')
from gguf import GGUFReader
def vocab(path):
    r = GGUFReader(path)
    f = r.fields['tokenizer.ggml.tokens']
    toks = [bytes(f.parts[i]) for i in f.data]
    return len(toks), hashlib.sha256(b'\x00'.join(toks)).hexdigest()
for p in ['<T7>/models/Qwen3-8B-Q4_K_M.gguf', '<T7>/models/Qwen3-0.6B-Q8_0.gguf']:
    print(p, *vocab(p))
PY
```

Record `draft_model.vocab_check` = `{n_tokens_target, n_tokens_draft, tokens_sha256_target,
tokens_sha256_draft, identical}`. If `identical` is false, **stop part C's draft rows** and
report it: the draft-model sentences in seg_10 and seg_11 then follow alternative (C) in the
brief's Outcome assumptions.

## 2. Server and requests

Parts A and B use one server; part C starts one server per method (section 5).

```sh
~/llama.cpp/build/bin/llama-server \
  -m "<T7>/models/Qwen3-8B-Q4_K_M.gguf" \
  --jinja --reasoning-format deepseek \
  -c 20480 -np 1 -ngl all --port 8080
```

Flags are the ones `llama-server --help` prints at build 11255 (checked on 2026-10-06 against
the official `llama-b11255-bin-ubuntu-x64` release binary, `--version` = `build 11255, commit
31385c9ce`): `--jinja` (chat template; default enabled), `--reasoning-format deepseek` (puts
the thoughts in `message.reasoning_content`), `--reasoning-budget N` and
`--reasoning-budget-message MESSAGE` (server-wide defaults; part B sets them per request
instead, see below). Record the launch line as `server.command` and the `--help` text as
`server.help_sha256`. **If any flag in this plan is missing from the Mac's `--help`, stop and
report it; do not substitute a look-alike.**

Every request: `POST /v1/chat/completions`, one message pair (system + user),
`cache_prompt: false` (so no request reuses another's cache and the timings are clean),
`timings_per_token: false`, and the request `seed` named per part. Read from each response:
`choices[0].message.reasoning_content` (the thinking), `choices[0].message.content` (the
answer), `usage.completion_tokens`, `timings.predicted_n`, `timings.predicted_ms`,
`timings.predicted_per_second`, `timings.prompt_n`, and, when the server speculated,
`timings.draft_n` and `timings.draft_n_accepted` (`tools/server/server-common.cpp`
`server_slot_stats::to_json` at 31385c9ce prints those two keys only when draft tokens were
made). Wall seconds are measured by the harness around the HTTP call (`time.monotonic()`).

**Thinking switch.** Thinking on: `chat_template_kwargs: {"enable_thinking": true}`;
thinking off: `chat_template_kwargs: {"enable_thinking": false}` (the Qwen3-8B model card,
"Switching Between Thinking and Non-Thinking Mode", <https://huggingface.co/Qwen/Qwen3-8B>).

**Sampling (from the same model card, "Best Practices").** Thinking on: `temperature 0.6,
top_p 0.95, top_k 20, min_p 0`. Thinking off: `temperature 0.7, top_p 0.8, top_k 20,
min_p 0`. The card says "DO NOT use greedy decoding" in thinking mode ("it can lead to
performance degradation and endless repetitions"), which is why parts A and B use seeds, not
greedy decoding. (My first plan was greedy decoding for exact repeats; the model card ruled it
out. That is the narrated dead end in seg_03.)

## 3. Part A — thinking on vs off (20 puzzles)

**System prompt (both modes, verbatim):** `Solve the puzzle. End your reply with exactly one
final line of the form ANSWER: <your answer>, with nothing after it.`

**Runs.** 20 puzzles × 3 seeds (`0, 1, 2`) × 2 modes = 120 requests. Thinking on:
`max_tokens 16384` (the cap; a run that hits it is `hit_cap: true` and scored wrong). Thinking
off: `max_tokens 2048`. Order: for each seed, for each puzzle, run off then on (so drift hits
both modes equally). One warm-up request first, discarded.

**Scoring.** Take the last line of `content` that starts with `ANSWER:`; strip spaces, a
trailing full stop and surrounding quotes, compare case-insensitively with the `accept` list.
No `ANSWER:` line, or `hit_cap`, is wrong. Thoughts are never scored, only the answer.

**The 20 puzzles** (write them to `puzzles.json` exactly as below; `kind` is `word`, `logic`
or `code`; answers were checked mechanically on 2026-10-06).

| id | kind | puzzle (user message) | accept |
|---|---|---|---|
| W01 | word | A train leaves at 09:40. The trip takes 2 hours 55 minutes, and it is delayed by 25 minutes on the way. At what time does it arrive? Answer as HH:MM. | `13:00` |
| W02 | word | A shop sells pens at 3 for 2 euros. A pen that does not make a full group of 3 costs 1 euro. Ana buys 14 pens. How many euros does she pay? | `10` |
| W03 | word | A tank holds 240 litres and is 3/8 full. You add 45 litres, then use a quarter of what is in the tank. How many litres are left? | `101.25` |
| W04 | word | Mia is 3 times as old as her son. In 12 years she will be twice as old as him. How old is Mia now? | `36` |
| W05 | word | A recipe for 4 people needs 300 g of flour. You cook for 10 people and have 650 g. How many grams are you short? | `100` |
| W06 | word | A phone plan costs 12 euros a month plus 0.05 euros for every MB above 2,000 MB. In March you use 2,740 MB. What is the bill in euros? | `49` |
| W07 | word | Three friends split a bill of 86 euros. Ben pays twice what Cai pays, and Ana pays 6 euros more than Ben. How many euros does Cai pay? | `16` |
| L01 | logic | Five runners finish a race. Dana finished before Eli but after Cleo. Ben finished last. Abe finished right after Dana. Who finished second? | `Dana` |
| L02 | logic | On an island, knights always tell the truth and knaves always lie. A says: "B is a knave." B says: "A and C are the same kind." What is C? Answer knight or knave. | `knave` |
| L03 | logic | Today is Wednesday. What day of the week is it 100 days from today? | `Friday` |
| L04 | logic | A drawer holds 6 red socks and 6 blue socks. In the dark, how many socks must you take out to be sure you have two red socks? | `8` |
| L05 | logic | Every member of a club plays chess or go. Nobody who plays go likes tea. Sam is a member and likes tea. Does Sam play chess? Answer yes, no or cannot tell. | `yes` |
| L06 | logic | A clock shows 3:15. What is the smaller angle between the hour hand and the minute hand, in degrees? | `7.5` |
| L07 | logic | Anna, Bo and Cy each own one pet: a cat, a dog or a fish, all different. Anna does not own the dog. Bo owns neither the cat nor the dog. Who owns the dog? | `Cy` |
| C01 | code | What does this Python program print? (program C01 below) | `4` |
| C02 | code | What does this Python program print? (program C02 below) | `66` |
| C03 | code | What does this Python program print? (program C03 below) | `4` |
| C04 | code | What does this Python program print? (program C04 below) | `55` |
| C05 | code | What does this Python program print? (program C05 below) | `the` |
| C06 | code | What does this Python program print? (program C06 below) | `2 True` |

The code puzzles send the question line, a blank line, then the program in a fenced
` ```python ` block:

```python
# C01
x = [1, 2, 3]
y = x
y.append(4)
print(len(x))
```

```python
# C02
total = 0
for i in range(1, 10, 3):
    total += i * i
print(total)
```

```python
# C03
s = "banana"
print(s.count("an") + s.find("n"))
```

```python
# C04
def f(n):
    return n if n < 2 else f(n - 1) + f(n - 2)
print(f(10))
```

```python
# C05
d = {}
for w in "the cat and the hat".split():
    d[w] = d.get(w, 0) + 1
print(sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[0][0])
```

```python
# C06
a = [3, 1, 2]
b = sorted(a)
a.sort(reverse=True)
print(a[0] - b[0], b == a[::-1])
```

(The `# Cnn` comment line is not sent.)

**Per-run record** (`thinking-runs.jsonl`, one line per request): `part` (`A`), `puzzle_id`,
`kind`, `seed`, `mode` (`think` | `nothink`), `wall_s`, `completion_tokens`,
`reasoning_tokens` (tokenise `reasoning_content` with `POST /tokenize`), `answer_tokens`,
`predicted_per_second`, `hit_cap`, `answer`, `correct`, and the full `reasoning_content` and
`content`.

**Cold-open example.** `examples.cold_open` is chosen mechanically: among puzzles where
thinking got more runs right than no-thinking, take the one with the largest gain (ties: the
most median thinking tokens, then the lowest id); use its seed-0 thinking run. Record
`{puzzle_id, seed, wall_s, seconds, reasoning_tokens, answer, correct, reasoning_excerpt}`,
where `seconds` is `wall_s` rounded to a whole second and `reasoning_excerpt` is the first 40
lines of the thinking. Screen-record that exact request being re-sent with its seed while the
transcript streams (section 8, step 4): that recording is the cold open.

## 4. Part B — the thinking budget

Qwen3's technical report (arXiv 2505.09388, section 4.3 "Thinking Budget") stops the thinking
at a threshold and inserts a stop-thinking instruction; llama.cpp implements the same cut
with `reasoning_budget_tokens` and `reasoning_budget_message` per request
(`tools/server/server-common.cpp` at 31385c9ce reads both from the request body; the message
is "injected before the end-of-thinking tag when reasoning budget is exhausted", `--help`).

**Runs.** The 20 puzzles × seeds `0, 1` × budgets `256, 512, 1024, 2048, 4096` = 200
requests, thinking on, thinking sampling, `max_tokens = budget + 2048`, with
`reasoning_budget_tokens: <budget>` and `reasoning_budget_message: "Considering the limited
time by the user, I have to give the solution based on the thinking directly now.\n"` (Qwen's
own stop line from the report, without its end tag, which llama.cpp adds). The unlimited
reference is part A's thinking runs on seeds 0 and 1 (40 runs).

**Check the cut fired.** A run is `forced: true` when the stop line appears in
`reasoning_content`. Its thinking may not exceed `budget` + the stop line's tokens + 8;
record `over_budget` otherwise and report it (it means the cut did not work as described).

**Scoring** as part A. Per budget: `budget.rows[i] = {budget, correct, n, forced,
reasoning_tokens_mean, wall_s_mean}`.

**The knee.** `budget.knee` = the smallest budget whose `correct` is at least 90 % of
`budget.unlimited.correct` (the same 40 seeds). If no budget reaches it, `budget.knee` =
`null` and seg_06 follows the "no knee" row in the brief's Outcome assumptions.

## 5. Part C — the speculative-decoding grid

**Methods** (one server each, started fresh: the section 2 launch line plus the method's
extra flags; flags exactly as `--help` and `docs/speculative.md` print them at 31385c9ce):

| key | extra server flags | why |
|---|---|---|
| `none` | `--spec-type none` (also the default) | the baseline |
| `draft_n3` | `-md "<T7>/models/Qwen3-0.6B-Q8_0.gguf" --spec-type draft-simple` (`--spec-draft-n-max` default 3) | a draft model at the build's default draft length |
| `draft_n8` | `-md "<T7>/models/Qwen3-0.6B-Q8_0.gguf" --spec-type draft-simple --spec-draft-n-max 8` | a longer draft, so the draft model gets a fair second setting |
| `ngram_simple` | `--spec-type ngram-simple` (lookup n-gram and draft m-gram at their defaults, `--spec-ngram-simple-size-n 12`, `--spec-ngram-simple-size-m 48`; at 31385c9ce `common/ngram-map.cpp` `common_ngram_simple_draft` drafts the `size_m` tokens that followed the matched n-gram, so `--spec-draft-n-max` does not set its length) | self-drafting from the text so far (llama.cpp PR 18471, which added `common/ngram-map.cpp` and `docs/speculative.md`) |

`--spec-type` defaults to `none`, and `-md` alone does **not** turn speculation on for a plain
model file: `common/arg.cpp` only infers a type from the draft file's metadata, and
`common_speculative_types_from_gguf` returns nothing for an ordinary `qwen3` file (it detects
only MTP heads and DFlash/DSpark drafts). So every speculating server names its type.

**Proof that it speculated (required).** With speculation on, llama-server logs, per finished
request, `draft acceptance = <ratio> (<accepted> accepted / <generated> generated), mean len =
<len>` (`tools/server/server-context.cpp` at 31385c9ce; the line is printed only when draft
tokens were made). Start each server with its stderr teed to
`spec-logs/<method>.log`. **A cell's numbers count only if every one of its requests has
that line** (for `none`: has none) **and its response has `timings.draft_n` > 0.** Record
`log_acceptance_lines` per cell. A draft server whose log shows a vocabulary warning
(`draft model vocab ... must match`) is void.

**Workloads** (`spec_prompts.json`, three prompts each, user messages verbatim; system
prompt: `You are a helpful assistant.`):

- `quote` (the answer repeats the input; greedy: `temperature 0`, `max_tokens 1024`, thinking
  off):
  - Q1: `Fix the spelling mistakes in this text. Change nothing else, and return the full
    corrected text only.` followed by passage A below (8 misspellings).
  - Q2: `In this Python file, rename the local variable count in summarise() to n_items. Keep
    the dictionary key "count" as it is. Return the complete file and nothing else.` followed
    by file B below.
  - Q3: `Put the line number and a full stop at the start of every line of this list, change
    nothing else, and return the whole list.` followed by list C below.
- `prose` (fresh text; greedy, `max_tokens 600`, thinking off):
  - P1: `In about 400 words, explain to a twelve-year-old how the gears on a bicycle make
    hills easier.`
  - P2: `In about 400 words, describe a rainy morning in a small bakery from the baker's
    point of view.`
  - P3: `In about 400 words, explain why bread goes stale, for a curious adult with no
    chemistry background.`
- `code` (fresh code; greedy, `max_tokens 800`, thinking off):
  - K1: `Write a Python function parse_duration(text) that turns strings like "1h 30m",
    "45s" or "2h5m10s" into a number of seconds. Include a docstring and five assert
    tests.`
  - K2: `Write a small Python command-line script that counts the words in a text file and
    prints the ten most common words with their counts. Use only the standard library.`
  - K3: `Write a JavaScript function debounce(fn, ms) with a short usage example.`
- `think` (the thinking phase itself; thinking on, thinking sampling, `max_tokens 1024`):
  - T1: `How many three-digit numbers have digits that add up to 20 and are divisible by 7?
    List them.` (answer 5: 497, 686, 749, 875, 938 — not scored)
  - T2: `In how many different ways can you make 1 euro from coins of 10, 20 and 50 cents?`
    (answer 10 — not scored)
  - T3: `What is the smallest positive whole number that leaves remainder 2 when divided by
    3, remainder 3 when divided by 5 and remainder 4 when divided by 7?` (answer 53 — not
    scored)
  - A `think` request counts only if its `content` is empty and `reasoning_content` holds
    all its generated tokens (the 1,024 tokens are all thinking). If the model finishes
    thinking early, re-send with the next seed (`seed` 0, 1, 2, … up to 9) until each prompt
    has 3 thinking-only requests; record the attempts. Use the **same** accepted seeds for
    every method.

**Passage A (Q1; the misspellings are intentional: there, it's, peir, dont, diferent,
acordion, untill, tommorow):**

```text
The old harbour town wakes up slowly. At six, the first fishing boats come back with there
nets full, and the gulls follow them in long, noisy circles. By seven, the bakery on the
corner has opened it's shutters, and the smell of fresh bread drifts down to the water. The
harbour master walks along the peir with a clipboard, counting boats and checking ropes. He
has done this every morning for twenty-two years, and he still writes everything by hand.
Tourists start to arrive around nine. They take photos of the lighthouse, buy ice cream they
dont really want, and ask the fishermen questions they have heard a thousand times. Most of
the fishermen answer politely. One of them, a tall man called Piet, tells every visitor a
diferent story about the lighthouse ghost. By noon the market square is full. Farmers sell
cheese, honey and apples from wooden stalls, and a man with an acordion plays the same three
songs untill the church bell rings. In the afternoon the wind picks up, and the boats stay
in. The town goes quiet again, as if it is resting before tommorow.
```

**File B (Q2):**

```python
import json
from pathlib import Path


def load_orders(path):
    with Path(path).open() as handle:
        return json.load(handle)


def summarise(orders):
    count = 0
    total = 0.0
    biggest = None
    for order in orders:
        count += 1
        total += order["amount"]
        if biggest is None or order["amount"] > biggest["amount"]:
            biggest = order
    average = total / count if count else 0.0
    return {"count": count, "total": total, "average": average, "biggest": biggest}


def report(summary):
    lines = [
        f"orders: {summary['count']}",
        f"total: {summary['total']:.2f}",
        f"average: {summary['average']:.2f}",
    ]
    if summary["biggest"] is not None:
        lines.append(f"biggest: {summary['biggest']['id']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(report(summarise(load_orders(sys.argv[1]))))
```

**List C (Q3):**

```text
Weekend hike packing list
Rain jacket with a hood
Warm fleece for the evening
Two pairs of thick socks
Walking boots, broken in
Water bottle, one litre
Trail map and a compass
Sandwiches for both days
A bag of nuts and raisins
Small first-aid kit
Head torch with spare batteries
Sun cream and a hat
Phone, fully charged
A plastic bag for rubbish
```

**Runs.** 4 methods × 4 workloads × 3 prompts × 3 repeats = 144 measured requests, plus
one discarded warm-up per server. Seeds: `quote`, `prose` and `code` are greedy (the seed
is recorded but does not matter); `think` uses the accepted seeds above. Order: repeat `r`
(0, 1, 2) runs the methods rotated by `r` (repeat 0: none, draft_n3, draft_n8, ngram_simple;
repeat 1 starts at draft_n3; repeat 2 at draft_n8), each method a fresh server, so heat and
background load fall on every method. Wait 60 s between servers.

**Per-request record** (`spec-runs.jsonl`): `method`, `workload`, `prompt_id`, `repeat`,
`seed`, `predicted_n`, `predicted_ms`, `predicted_per_second`, `draft_n`,
`draft_n_accepted`, `acceptance_line` (the matching log line, verbatim), `content_sha256`,
`reasoning_sha256`, `think_only` (`think` only).

**Cell metrics** (`spec.cells.<method>.<workload>`): `n` (9), `tps_mean` (mean of
`predicted_per_second`), `tps_runs`, `draft_n`, `draft_n_accepted` (sums),
`acceptance` (`draft_n_accepted / draft_n`), `log_acceptance_lines`.

**Summary metrics:**

- `spec.baseline_tps` = `spec.cells.none.prose.tps_mean`.
- `spec.draft_best` = whichever of `draft_n3`, `draft_n8` has the higher mean of its four
  cells' `tps_mean`.
- `spec.draftmodel_change` = mean over the four workloads of
  (`cells.<draft_best>.<w>.tps_mean` ÷ `cells.none.<w>.tps_mean`) − 1 (negative = slower).
  Also record `spec.draftmodel_change_by_workload`.
- `spec.draft_acceptance` = pooled `draft_n_accepted / draft_n` over all of `draft_best`'s
  requests.
- `spec.ngram.quote_speedup` = `cells.ngram_simple.quote.tps_mean` ÷
  `cells.none.quote.tps_mean`.
- `spec.ngram.quote_acceptance` = `cells.ngram_simple.quote.acceptance`.
- `spec.ngram.prose_change`, `spec.ngram.code_change`, `spec.ngram.think_change` = the same
  ratio − 1 on `prose`, `code` and `think`.
- **Lossless check.** `spec.lossless.pairs` = 27 (the 9 greedy prompts × the 3 speculating
  methods, repeat 0); `spec.lossless.identical` = how many have the same `content_sha256` as
  the `none` run of the same prompt. Both papers say the output does not change
  (Leviathan et al., arXiv 2211.17192; Chen et al., arXiv 2302.01318); llama.cpp's
  `docs/speculative.md` says "Use greedy sampling when exact output matching is required",
  which is why the check uses the greedy jobs only. For any mismatch, store both texts under
  `spec.lossless.mismatches`.

## 6. The capture file

`episodes/6b2bf8d7c396/evidence/thinking-capture.json`, schema `ep22-thinking-capture-1`.
Every key below is written by the harness; a key that cannot be measured is `null` with a
sibling `<key>_reason`, never a guess.

```text
schema_version                     "ep22-thinking-capture-1"
captured_at_utc
machine.chip, machine.ram_bytes, machine.power, machine.therm_before, machine.therm_after
llama_cpp.output                   (the --version line)
model.file_name, model.sha256, model.size_bytes
draft_model.file_name, draft_model.sha256, draft_model.size_bytes
draft_model.vocab_check            {n_tokens_target, n_tokens_draft, tokens_sha256_target,
                                    tokens_sha256_draft, identical}
harness.sha256, puzzles.sha256, spec_prompts.sha256
server.command, server.help_sha256
config.puzzles_n                   20
config.runs_per_puzzle             3      (seeds 0, 1, 2)
config.think_cap_tokens            16384
config.sampling                    {think: {...}, nothink: {...}}

think_ab.nothink                   {n, correct, tokens_mean, tokens_median, seconds_mean,
                                    seconds_median}
think_ab.think                     {n, correct, tokens_mean, tokens_median,
                                    reasoning_tokens_median, seconds_mean, seconds_median,
                                    hit_cap}
think_ab.by_kind.<word|logic|code> {nothink: {n, correct}, think: {n, correct}}
think_ab.by_puzzle.<id>            {nothink_correct, think_correct, think_tokens_median}
think_ab.token_multiple            think.tokens_mean ÷ nothink.tokens_mean
think_ab.time_multiple             think.seconds_mean ÷ nothink.seconds_mean
think_ab.items_helped              puzzles with think_correct > nothink_correct
think_ab.items_hurt                puzzles with think_correct < nothink_correct
examples.cold_open                 {puzzle_id, seed, wall_s, seconds, reasoning_tokens,
                                    answer, correct, reasoning_excerpt}

budget.budgets                     [256, 512, 1024, 2048, 4096]
budget.rows[0..4]                  {budget, n, correct, forced, over_budget,
                                    reasoning_tokens_mean, wall_s_mean}
budget.unlimited                   {n, correct}   (part A thinking runs, seeds 0 and 1)
budget.knee                        smallest budget with correct >= 0.9 × unlimited.correct

spec.methods                       ["none", "draft_n3", "draft_n8", "ngram_simple"]
spec.workloads                     ["quote", "prose", "code", "think"]
spec.cells.<method>.<workload>     {n, tps_mean, tps_runs, draft_n, draft_n_accepted,
                                    acceptance, log_acceptance_lines}
spec.think_attempts                {T1, T2, T3: [seeds tried]}
spec.baseline_tps
spec.draft_best
spec.draftmodel_change
spec.draftmodel_change_by_workload {quote, prose, code, think}
spec.draft_acceptance
spec.ngram.quote_speedup
spec.ngram.quote_acceptance
spec.ngram.prose_change
spec.ngram.code_change
spec.ngram.think_change
spec.lossless.pairs                27
spec.lossless.identical
spec.lossless.mismatches
```

## 7. Runtime (estimate) and cost

No paid call anywhere. Local compute only, on the operator's Mac:

- Part A: 60 thinking-off requests (a few seconds each) and 60 thinking-on requests (most
  under a minute at roughly 40 tokens a second; the 16,384-token cap bounds a stuck run at
  about 8 minutes). About 1 to 2 hours.
- Part B: 200 requests, each bounded by its budget. About 2 to 3 hours.
- Part C: 144 measured requests, 12 server starts (one per method per repeat), 60 s pauses.
  About 1 to 1.5 hours.
- Total about 4 to 6.5 hours; the harness takes `--part A|B|C` and `--resume` (it skips
  requests already in the runs file), so it can run overnight in pieces.
- Disk: the draft model, 639,446,688 bytes; runs files and logs, a few tens of MB.

## 8. Operator steps

1. Check section 1 (versions, hashes, mains power). Download the draft model and run the
   vocabulary check.
2. Write `puzzles.json` and `spec_prompts.json` from sections 3 and 5; record their hashes.
3. Run part A, then part B (one server, section 2).
4. Re-send the cold-open request (section 3) with its seed while screen-recording the
   streamed thinking beside a seconds counter. Keep the recording beside the capture.
5. Run part C (fresh server per method, logs teed). Screen-record one `quote` request on
   `none` and on `ngram_simple` side by side, with the tokens-per-second figure visible.
6. Build `thinking-capture.json`; check every `PENDING:` key in `claims.md` exists (or is
   `null` with a reason). Resolve the script (section 9) and re-run the validators.

## 9. Label → capture key

How to resolve: `pipeline.models.resolve_placeholder_results(contract, {label: spoken
value})`, with every number spelled out for the voice. The narration supplies its own
"about"; the spoken value does not add one unless the column says so. After resolution,
recompute every segment's `est_seconds`, `total_est_seconds` and the clip candidates'
`est_seconds` with `pipeline.script.estimate_seconds`, re-run `ScriptContract`, and check
the hook still lasts under 15 seconds with its payoff by 10 (a token is one word; its
spoken value is two to six).

| label | capture key | spoken form |
|---|---|---|
| `cold_open_seconds` | `examples.cold_open.seconds` | whole seconds, e.g. "ninety-three" |
| `acc_nothink` | `think_ab.nothink.correct` out of `think_ab.nothink.n` | "thirty-four out of sixty" |
| `acc_think` | `think_ab.think.correct` out of `think_ab.think.n` | as above |
| `tokens_nothink` | `think_ab.nothink.tokens_median` | rounded to tens, e.g. "about two hundred and forty" |
| `tokens_think` | `think_ab.think.tokens_median` | rounded to hundreds, e.g. "about two thousand one hundred" |
| `think_token_multiple` | `think_ab.token_multiple` | one significant figure, e.g. "about nine times" |
| `think_time_multiple` | `think_ab.time_multiple` | as above |
| `seconds_nothink` | `think_ab.nothink.seconds_mean` | e.g. "about six seconds" |
| `seconds_think` | `think_ab.think.seconds_mean` | e.g. "about a minute", or "about forty seconds" |
| `items_hurt` | `think_ab.items_hurt` | a count, e.g. "two" |
| `acc_budget_low` | `budget.rows[0].correct` out of `budget.rows[0].n` | "twenty-two out of forty" |
| `budget_knee` | `budget.knee` | "about one thousand tokens" (or "two thousand and forty-eight tokens", exact) |
| `baseline_tps` | `spec.baseline_tps` | rounded, e.g. "forty-two" |
| `draftmodel_change` | `spec.draftmodel_change` | rounded percent with direction, e.g. "about ten percent slower" |
| `draft_acceptance` | `spec.draft_acceptance` | "about six in ten" |
| `ngram_quote_speedup` | `spec.ngram.quote_speedup` | "about twice", "about three times" |
| `ngram_quote_acceptance` | `spec.ngram.quote_acceptance` | "about eight in ten" |
| `ngram_prose_change` | `spec.ngram.prose_change` | "less than two percent", or "about five percent" with direction |
| `ngram_code_change` | `spec.ngram.code_change` | as above |
| `ngram_think_change` | `spec.ngram.think_change` | "about four percent slower" |
| `identical_outputs` | `spec.lossless.identical` out of `spec.lossless.pairs` | "all twenty-seven", or "twenty-five of twenty-seven" |

## 10. Risks

- **Flags differ on the Mac.** The flags above come from the official build-11255 binary's
  `--help`; a locally built binary of the same commit should match. If not, stop (section 2).
- **The draft vocabulary does not match.** Then there is no draft-model row; see section 1
  and alternative (C) in the brief.
- **Speculation silently off.** Guarded by the acceptance-line rule (section 5): no line, no
  number.
- **Thinking loops.** The 16,384-token cap bounds it; `hit_cap` runs are scored wrong and
  counted in `think_ab.think.hit_cap`. If more than 5 of 60 hit the cap, report it: the
  token and time multiples then understate the cost, and seg_04 says so.
- **The budget cut misbehaves.** `over_budget` > 0 means llama.cpp did not stop the thinking
  where asked; report it and drop part B's sentences that depend on it (brief, "no knee").
- **Sampled runs differ between methods.** With speculation on, a sampled run may draw
  different tokens than without (`docs/speculative.md`, "Backend Sampling"), so the `think`
  cells compare speed, not text. The lossless check uses greedy jobs only.
- **Heat and background load.** Rotated method order, fresh servers, 60 s pauses, mains
  power; record `pmset -g therm` before and after each part as `machine.therm_before` /
  `machine.therm_after`.
- **Small N.** 20 puzzles × 3 runs a side, 9 requests per grid cell. The episode states it
  (seg_14) and never generalises beyond this model and this Mac.
