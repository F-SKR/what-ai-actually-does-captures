# Experiment plan — EP22-E4 memory (idea `76ae1244d79d`)

Card <card>, written 2026-10-06, revised the same day for grader round 1 (X1-X9) and on 2026-10-07 for grader round 2 (X-B3 scoring, X1 frozen retrieval in section 5.5, O3, O4). This is the runnable spec for the four tests the
script `episodes/76ae1244d79d/script.yaml` narrates. Every `PLACEHOLDER_RESULT[label]`
in the script resolves from a key in one capture file,
`episodes/76ae1244d79d/evidence/memory-capture.json` (schema `ep22-memory-capture-1`,
section 7), and every `PENDING:` pointer in `claims.md` names one of those keys. Nothing
here calls a paid provider; the whole run is local on the operator's Mac.

| test | what it shows | runtime | section |
|---|---|---|---|
| A needle in a haystack | how well the window is used, by length and position, with same-word and reworded questions | llama.cpp | 3 |
| B re-read cost | what a prompt cache saves at turn ten, and how a timestamp breaks it | llama.cpp | 4 |
| C compaction and lookup | which planted facts survive the model's own summary, against a full-history control, a no-history guess and a word-search lookup | llama.cpp | 5 |
| D weights | what a one-fact LoRA learns and what else it moves | MLX | 6 |

Run order: D's download can start first (section 6.1), then A, B, C on one server, then
D. A, B and C need nothing from each other; if the night runs short, run B and C first
(they are the cheapest) and A last.

## 1. Machine, build, model

| item | value | how to check before the run |
|---|---|---|
| machine | MacBook, Apple M4 Pro, 24 GiB (the series 1 machine) | `sysctl -n machdep.cpu.brand_string`, `sysctl -n hw.memsize` → `machine.chip`, `machine.ram_bytes` |
| llama.cpp | build 11255, commit 31385c9ce (the series 1 build) | `~/llama.cpp/build/bin/llama-server --version` must print `version: 0.5.0-dev (build 11255, commit 31385c9ce)` → `llama_cpp.output` |
| model (A, B, C) | `Qwen3-8B-Q4_K_M.gguf`, 5,027,784,512 bytes, sha256 `120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4` (the same file as `episodes/ee7fcc52450f/evidence/ais-lab1-tokens-capture.json` `model`) | `shasum -a 256 "<T7>/models/Qwen3-8B-Q4_K_M.gguf"` → `model.sha256`; refuse to start on a mismatch |
| model (D) | `mlx-community/Qwen3-8B-4bit` (an MLX 4-bit conversion of Qwen/Qwen3-8B; NOT the GGUF file), fallback `mlx-community/Qwen3-1.7B-4bit` | Hugging Face revision hash → `lora.model.revision` |
| haystack text | The Adventures of Sherlock Holmes, Project Gutenberg eBook #1661, plain text UTF-8, Gutenberg header and footer removed | `shasum -a 256` of the stripped file → `haystack.sha256` |
| harness | `~/ep22-lab/memory/harness.py` (to write from this plan; one file, one subcommand per test) | `shasum -a 256` → `harness.sha256` |

The KV cache stays at the default f16 for every llama.cpp test (the series 1 Part 4
rows in `episodes/ad65fb76a5bb/evidence/ais-lab2-memory-speed-capture.json`
`formula_check[0..3]` are f16: 288 MiB at 2,048 tokens, 4,608 MiB at 32,768).

## 2. Server (A, B, C)

One llama-server, one slot, the model's native window, all layers on the GPU, no host
prompt cache (only the slot's own cache, so test B measures exactly one mechanism):

```sh
~/llama.cpp/build/bin/llama-server \
  -m "<T7>/models/Qwen3-8B-Q4_K_M.gguf" \
  -c 32768 -np 1 -ngl 99 --jinja --cache-ram 0 \
  --slot-save-path ~/ep22-lab/memory/slots/ --port 8088
```

Create `~/ep22-lab/memory/slots/` first. `--slot-save-path` is required for the slot
erase in test B: at 31385c9, `POST /slots/{id}?action=...` answers "This server does not
support slots action. Start it with `--slot-save-path`" when the path is empty
(`tools/server/server-context.cpp`, the `post_slots` handler, L4752-4756), so without it
the erase silently does nothing and later repeats start warm. Nothing is ever saved to
that folder; only the erase action is used.

`-c 32768` is Qwen3-8B's native context length (model card, Model Overview: "32,768
natively"); no YaRN. Every request goes to `/v1/chat/completions` with
`"chat_template_kwargs": {"enable_thinking": false}` (thinking off for all of A, B, C)
and records the response `timings` object (`cache_n`, `prompt_n`, `prompt_ms`,
`predicted_n`, `predicted_ms`; `tools/server/README.md` at 31385c9, "Timings and context
usage"). Token counts of a rendered conversation come from
`POST /v1/chat/completions/input_tokens` on the same server. For the cache-off arm of
test B only, restart the same command with `--no-cache-prompt` added and send
`"cache_prompt": false`.

Sampling, unless a section says otherwise: thinking-off values from the model card
(Best Practices: temperature 0.7, top_p 0.8, top_k 20, min_p 0). Answers that are
scored (A's two questions, C's quiz, D's probes) use temperature 0.

## 3. Test A — needle in a haystack

### 3.1 Design

- **Facts:** the 20 invented facts in 3.3, one sentence each (the "needle").
- **Lengths:** total prompt of 2,000, 8,000, 16,000 and 31,000 tokens (`needle.config.lengths` = `[2000, 8000, 16000, 31000]`; labels `2k`, `8k`, `16k`, `31k`). 31,000 leaves room for the question and a 64-token answer inside 32,768.
- **Positions:** the needle goes at the paragraph boundary nearest to 10% (`start`), 50% (`middle`) and 90% (`end`) of the haystack's tokens (`needle.config.depths`).
- **Cells and N:** 4 lengths × 3 positions = 12 cells; every fact once per cell, so 20 tries per cell and 240 tries per question style (`needle.config.n_per_cell` = 20).
- **Haystack per try:** a contiguous run of whole paragraphs from the stripped book, starting at a paragraph chosen by `random.Random(1000 * fact_no + cell_index)`, extended until the rendered prompt reaches the length; the needle sentence is inserted as its own paragraph. Before inserting, check that the fact's answer pattern (3.3) does not already match the slice; if it does, take the next seed (`seed + 1`) and record the skip in `needle.config.reseeds`.
- **Two questions per try, one haystack:** first the reworded question, then the same-word question, as two separate requests that share the haystack prefix. The second request reuses the slot cache for the haystack (`cache_n` close to the haystack length), so it costs almost nothing; the first request's `timings.prompt_ms` is the read time for that haystack. Record `needle.config.question_order` = `["paraphrase", "lexical"]`. The server README warns that `cache_prompt` "can cause nondeterministic results" (`tools/server/README.md` L587), so as a spot check run the 20 same-word questions once more at 31k middle with `"cache_prompt": false` and a fresh read (`needle.config.lexical_cache_check`: `n`, `correct`, `agree_with_cached`); it is the last step of A and the first thing to drop if the night runs short (then the screen says the same-word column came from the cached path).
- **Prompt:** system: `You answer questions about the document the user gives you. Answer in one short sentence.`; user: `<document>\n{haystack with needle}\n</document>\n\nQuestion: {question}`. Temperature 0, `max_tokens` 64, `seed` 4242.
- **Order:** loop lengths from short to long, positions start, middle, end, facts 01 to 20; write each try to `memory-trials.jsonl` as it finishes (crash-safe; a re-run skips finished `(length, position, fact)` keys).

### 3.2 Scoring

A try is correct when the answer matches the fact's answer pattern (case-insensitive
regex in 3.3). Every miss at 31K is also read by a person; a correct answer the regex
missed is fixed in the pattern and the whole test is re-scored (record the pattern
change in `needle.config.pattern_fixes`). Before the run, the harness checks that each
reworded question shares no content word with its fact (lowercase, drop stopwords,
compare word stems by their first five letters). Stopwords: the NLTK English list plus
`where, what, which, when, how, why, I, my, should, look, get`. The check runs in
`harness.py preflight` and fails the run (not a silent reword) if any pair shares a stem;
a pair is reworded only by editing this table, and the change is recorded in
`needle.config.question_fixes`. With that list all 20 rows below pass (checked offline on
2026-10-06 against the embedded NLTK list; before the round-1 rewording, rows 07 "water" /
"watering" and 19 "plant" / "planted" failed).

### 3.3 The 20 facts

| no | fact (inserted verbatim) | same-word question | reworded question (no shared content word) | answer pattern |
|---|---|---|---|---|
| 01 | The lighthouse keeper's dog is named Biscuit. | What is the lighthouse keeper's dog named? | What do they call the pet that lives with the man who tends the coastal beacon? | `biscuit` |
| 02 | The village choir rehearses every Thursday evening. | When does the village choir rehearse? | On which weekday do the singers from the small settlement practise? | `thursday` |
| 03 | Professor Hale keeps her rare stamps in a cigar box under the stairs. | Where does Professor Hale keep her rare stamps? | Where is the academic's collection of postage hidden? | `cigar` |
| 04 | The garden gate code at Number 12 is 3-8-5-1. | What is the garden gate code at Number 12? | Which digits unlock the yard entrance of the twelfth house on that road? | `3\D?8\D?5\D?1` |
| 05 | The ferry to the island leaves at a quarter past six. | When does the ferry to the island leave? | What time does the boat out to that patch of land in the sea depart? | `quarter past six\|6[:.]15\|six[- ]fifteen` |
| 06 | The secret ingredient in Aunt Rosa's soup is smoked paprika. | What is the secret ingredient in Aunt Rosa's soup? | Which spice makes the broth cooked by the mother's sister special? | `paprika` |
| 07 | The spare key to the boathouse is kept inside the blue watering can. | Where is the spare key to the boathouse kept? | If I'm locked out of the shed by the lake, where should I look? | `watering can` |
| 08 | The museum's oldest clock was built in 1702. | When was the museum's oldest clock built? | In which year was the most ancient timepiece in the gallery made? | `1702` |
| 09 | The chess club's trophy is hidden behind the piano. | Where is the chess club's trophy hidden? | Where did the board-game society put its prize cup? | `piano` |
| 10 | Doctor Pell's favourite colour is mustard yellow. | What is Doctor Pell's favourite colour? | Which shade does the physician like best? | `mustard` |
| 11 | The train from Oldham to Leeds was cancelled because of a flooded tunnel. | Why was the train from Oldham to Leeds cancelled? | What stopped the rail service between those two northern towns from running? | `flood` |
| 12 | The library's late fee is forty pence per day. | What is the library's late fee? | How much is charged when a borrowed book comes back after its due date? | `forty pence\|40 ?p` |
| 13 | The red kite nest is on the third pylon past the quarry. | Where is the red kite nest? | Where have the rust-coloured birds of prey built their home? | `pylon` |
| 14 | The bakery's sourdough starter is called Gerald. | What is the bakery's sourdough starter called? | What name was given to the fermenting dough culture at the bread shop? | `gerald` |
| 15 | The cottage's water heater is switched off at the fuse marked F4. | Which fuse switches off the cottage's water heater? | Which circuit breaker cuts power to the boiler in the little country house? | `\bf4\b` |
| 16 | The puzzle hunt's final clue is taped under the bandstand. | Where is the puzzle hunt's final clue taped? | Where is the last hint of the treasure game stuck? | `bandstand` |
| 17 | Grandpa Joe's old car is painted sea green. | What colour is Grandpa Joe's old car painted? | What shade is the vintage motor belonging to the elderly man in the family? | `sea green` |
| 18 | The school's spring fair raised 2,340 pounds for the roof. | How much did the school's spring fair raise for the roof? | What sum did the April event at the classroom building bring in for repairs overhead? | `2,?340` |
| 19 | The orchard's oldest tree is a pear planted in 1931. | When was the orchard's oldest tree planted? | In what year did the most ancient fruit-bearer in that place go into the soil? | `1931` |
| 20 | The radio quiz prize this week is a copper kettle. | What is the radio quiz prize this week? | What can the winner of the on-air trivia game take home these seven days? | `kettle` |

### 3.4 Keys written

`needle.config` (lengths, depths, n_per_cell, seed, reseeds, question_fixes,
pattern_fixes, question_order, lexical_cache_check); `needle.cells.<2k|8k|16k|31k>.<start|middle|end>` with `n`,
`lexical_correct`, `paraphrase_correct`, `prompt_n_median`, `read_seconds_median`;
`needle.summary`:

- `lexical_long` = same-word question, 31k, all three positions: `correct`, `n` (60)
- `paraphrase_short` = reworded, 2k, all positions: `correct`, `n` (60)
- `paraphrase_long` = reworded, 31k, all positions: `correct`, `n` (60)
- `paraphrase_long_middle` = reworded, 31k, middle: `correct`, `n` (20)
- `paraphrase_long_edges` = reworded, 31k, start and end: `correct`, `n` (40); kept for the screen only, the narration speaks the three cells `needle.cells.31k.start`, `.middle` and `.end` (`paraphrase_correct` / `n`, 20 each)

`needle.read_seconds_median_31k` = median over the 60 tries at 31k of the reworded
request's `timings.prompt_ms` / 1000; `examples.needle_middle_miss` = one reworded miss at
31k middle, verbatim: `fact_no`, `fact`, `question`, `answer` (pick the lowest fact
number that missed).

### 3.5 Comparisons, decided before the data (X5)

Twenty tries per cell cannot separate 10 of 20 from 13 of 20 by eye, so the harness
computes these and the brief's alternatives (a) and (b) read only the `clear` flags:

- `needle.comparisons.middle_vs_edges` (reworded question, 31k, paired by fact: each fact
  appears once per position): `{middle_correct, start_correct, end_correct, n: 20,
  discordant_middle_worse, discordant_middle_better, mcnemar_p, clear}`. The discordant
  pairs and `mcnemar_p` compare the middle with the better of the two edges (more
  correct; a tie takes `start`), `mcnemar_p` is the exact two-sided binomial test on the
  discordant pairs, and `clear = middle_correct <= min(start_correct, end_correct) - 3
  and mcnemar_p < 0.1`.
- `needle.comparisons.long_vs_short` (reworded question, 31k against 2k, paired by fact
  and position, n = 60): the same fields with `long_correct` and `short_correct`, and
  `clear = short_correct - long_correct >= 6 and mcnemar_p < 0.05`.

If the 31k cells fall back to 10 tries (section 10), the count margins halve (2 and 3)
and the p thresholds stay.

## 4. Test B — the re-read cost

### 4.1 Design

- **Conversation:** the first ten user turns of test C (5.2, turns 1-10), one per turn.
- **Looked-up document:** the system prompt is the C system prompt followed by `\n\nReference document (looked up from the project folder):\n` and the first 2,000 tokens of the stripped haystack text (whole paragraphs, cut at the first paragraph end at or after 2,000 tokens by `/tokenize`; record `prefill.config.doc_tokens`).
- **Fixed history across arms:** run arm `cache_on` first for each repeat with temperature 0.7, top_p 0.8, top_k 20, `seed` = repeat number, `max_tokens` 150; record its ten assistant replies. Arms `cache_off` and `cache_on_timestamp` replay those recorded replies as the history (each turn still asks the server for a reply, for timing, but the next request uses the recorded reply), so all three arms send byte-identical conversations apart from the timestamp line.
- **Arms:**
  - `cache_on`: server as in section 2, `"cache_prompt": true` (the default).
  - `cache_off`: server restarted with `--no-cache-prompt`, requests with `"cache_prompt": false`.
  - `cache_on_timestamp`: as `cache_on`, but the system prompt starts with a line `Current time: <UTC ISO-8601 with seconds, taken at send time>` before everything else.
- **N:** 5 repeats per arm (`prefill.config.repeats` = 5). Between repeats, clear the slot (`POST /slots/0?action=erase`, which needs `--slot-save-path`, section 2) so turn 1 always starts cold; `harness.py preflight` erases slot 0, sends one request and asserts `timings.cache_n == 0`.
- **Known prefix break (X3):** with `enable_thinking: false` the generation prompt ends `<|im_start|>assistant\n<think>\n\n</think>\n\n`, but the Qwen3 template (`models/templates/Qwen-Qwen3-0.6B.jinja` at 31385c9, the GGUF's own template) renders earlier assistant turns as `<|im_start|>assistant\n{content}` with no think block. So in `cache_on` the slot cache diverges at the start of the previous reply, and each turn re-reads that reply plus the new message. This is the real behaviour of this model and server; measure it, do not work around it. Record per turn `cache_n`, `prompt_n` and the index of the first differing token (from `/v1/chat/completions/input_tokens` of the previous and current request) in `prefill.arms.cache_on.per_turn`. A turn-10 `prompt_n` of about 150-200 in `cache_on` is this break, not brief alternative (d).

### 4.2 Keys written

For each arm in `prefill.arms.<cache_off|cache_on|cache_on_timestamp>`:
`per_turn` (list of ten objects with the medians over repeats of `prompt_n`, `cache_n`,
`prompt_ms`, `first_diff_token`, the index of the first token that differs from the
previous request, and `prev_reply_start_token`, the index where the previous assistant
reply begins in the current request; the brief's `prefill_tokens_cached` row checks that
in `cache_on` the two agree to within the template's few role tokens), `turn_10.prompt_n_median`, `turn_10.prompt_ms_median`,
`turn_10.cache_n_median`, `total_prompt_n_median` (median over repeats of the sum of
`prompt_n` over turns 1-10). Also `prefill.config` (repeats, turns, doc_tokens, server
flags per arm).

## 5. Test C — compaction

### 5.1 Design

- **System prompt:** `You are a helpful assistant helping a small business owner plan and build a website. Keep replies under 120 words.`
- **Session:** the 30 scripted user turns in 5.2; the model writes every assistant reply (temperature 0.7, top_p 0.8, top_k 20, `max_tokens` 200, `seed` = seed number).
- **Twelve planted facts** (5.3), all stated by the user in turns 1-17 and never repeated afterwards.
- **Paired arms per seed:** run turns 1-20 once and save the conversation. Then fork:
  - `full_history`: continue turns 21-30 with the whole history.
  - `compacted`: send the saved history plus the user message `Summarise this conversation so you can continue the work without it.` (temperature 0, `max_tokens` 1,024); the reply is the summary. Start a new conversation whose system prompt is the system prompt above plus `\n\nSummary of the conversation so far:\n{summary}`, and continue turns 21-30 from there.
- **Quiz:** after turn 30, ask each of the twelve quiz questions (5.3) as a separate request appended to the turn-30 conversation (the shared prefix comes from the slot cache), temperature 0, `max_tokens` 60, prefixed `Quick check: ` and suffixed ` Answer in one short sentence.`
- **N:** 10 seeds (1-10) per arm (`compaction.config.seeds`).
- **Why the squeeze is forced:** twenty turns of replies under 120 words come to roughly 5-6K tokens, far below the 32,768 window, so compaction here is triggered at turn 20 on purpose rather than by a full window (the narration says so). The harness records `compaction.history_tokens_median` and refuses a history that would not fit.
- **Baseline arm `no_history` (X4):** a new conversation with only the system prompt above, then the twelve quiz questions exactly as in the other arms (temperature 0, same `Quick check: ` prefix and suffix). At temperature 0 with one fixed system prompt, ten seeds would be ten near-identical runs, so it runs **once** (`compaction.config.no_history_mode` = `"once_t0"`; `facts_correct_mean` is that run's count and `per_fact` is 1 or 0). It measures what the model gets right by guessing (for example F12's "no"). 12 short requests, a minute or two.
- **Lookup arm `lookup` (X8, round 2 X1):** at quiz time, a keyword retriever picks, for each quiz question, at most 2 of the 30 scripted user turns in 5.2: lowercase, split on `[a-z0-9]+`, drop the stopwords of 3.2, score = number of distinct shared words; a turn with score 0 is never picked (a search that finds nothing returns nothing), so a question gets one or no notes when fewer than two turns share a word; ties among scored turns go to the lower turn number (about 15 lines in `harness.py`). A new conversation gets the system prompt above and one user message `Notes from earlier in the conversation:\n{turn A}\n{turn B}\n\nQuick check: {question} Answer in one short sentence.` (the picked turns in turn order, one line each); if a question gets no note, the user message is `Notes from earlier in the conversation:\n(none found)\n\nQuick check: {question} Answer in one short sentence.` Temperature 0, `max_tokens` 60. The user turns are scripted, so the retrieval and the prompt are the same for every seed: run it once. The retrieval is computed before the run and frozen in 5.5. About 12 requests, a few minutes; with the harness work about 15 minutes.

### 5.2 The 30 user turns

1. I'm building a website for my aunt's bakery, Crumb and Copper. Can you help me plan it?
2. The owner is my aunt, Ines Okafor. I'm just helping her out. What pages do we need?
3. The main goal is to take online orders for collection on Saturdays. How should the order page work?
4. Draft a short welcome paragraph for the home page.
5. I've set up a test server on port 8417. What should I check before we put anything on it?
6. Our budget is 3,200 euros, all in. What would you spend it on first?
7. Suggest a simple menu structure for the products.
8. We want to launch on the 14th of March. Give me a rough week-by-week plan.
9. The domain is crumbandcopper.nl. What do I need to set up for it?
10. We decided on dark green as the main colour, hex 2F6B4F. Suggest two accent colours.
11. Write three short product descriptions: sourdough loaf, cinnamon bun, rye bread.
12. We'll take payments through Mollie, not PayPal. What does the checkout need?
13. The photographer is Sem de Wit. Write him a short brief for the product photos.
14. How should we handle allergens on the product pages?
15. The ovens limit us to 60 orders per Saturday. How do we stop people ordering more?
16. Draft the text for the order confirmation email.
17. We decided not to offer gluten-free bread online for now. How do we say that politely?
18. What should the About page say?
19. Give me a checklist for testing the order flow.
20. What questions should I ask my aunt before we build the order page?
21. Write the FAQ: opening hours, collection, cancellations.
22. How should the page look on a phone?
23. Draft a short Instagram post announcing the website.
24. What should we track to see if the site works?
25. Write the alt text for the three product photos.
26. Suggest a simple way to collect customer reviews.
27. What legal pages does a small Dutch shop website need?
28. Draft a cancellation policy in plain language.
29. Make a short list of what could go wrong on launch day.
30. Summarise the next three things I should do this week.

### 5.3 The twelve facts and the quiz

| fact | category | planted in turn | quiz question | answer pattern |
|---|---|---|---|---|
| F01 | name | 1 | What is the bakery called? | `crumb (and\|&) copper` |
| F02 | name | 2 | Who owns the bakery? | `\bines\b\|okafor` |
| F03 | gist | 3 | What is the main goal of the website? | `\bonline orders?\b\|\borders? online\b\|\btake orders?\b\|\bordering\b` |
| F04 | exact value | 5 | Which port does the test server run on? | `8417` |
| F05 | exact value | 6 | What is the total budget? | `3[,.]?200` |
| F06 | date | 8 | What is the launch date? | `14(th)?.{0,8}march\|march.{0,4}14` |
| F07 | exact value | 9 | What is the website's domain? | `crumbandcopper\.nl` |
| F08 | decision | 10 | What is the main colour? | `2f6b4f\|dark green` |
| F09 | decision | 12 | Which payment provider will we use? | `mollie` |
| F10 | name | 13 | What is the photographer's name? | `\bsem\b\|de wit` |
| F11 | exact value | 15 | How many orders can we take per Saturday? | `\b60\b\|sixty` |
| F12 | decision | 17 | Will we sell gluten-free bread online? | `\b(no\|won't\|will not\|not (offer\|sell)\w*)\b` (scored only after the don't-know check) |

Classification order (round 2, X-B3): an answer is **don't know** when it matches
`don't know|do not know|not sure|wasn't mentioned|was not mentioned|no information|not specified|didn't mention|haven't (been told|mentioned)`
and states no value (with every matched don't-know phrase removed, it no longer matches
the fact's pattern); otherwise **correct** when it matches the pattern; otherwise
**confident wrong**. Patterns are case-insensitive. This order matters: "I don't know who
owns the business" must not count as correct, and neither must "I'm not sure" for F12.
A person reads every answer scored correct in `no_history` and `lookup` (at most 24, with
`no_history` run once) and every F02, F03, F10 and F12 answer in all arms, plus every
wrong answer of seed 1; overrides go to `compaction.config.scoring_overrides` (arm, seed,
fact, the answer, the original label and the corrected label).

### 5.4 Keys written

`compaction.config` (seeds, compact_at_turn = 20, turns = 30, summary_prompt verbatim,
lookup_top_k = 2, no_history_mode, scoring_overrides);
`compaction.history_tokens_median` (median over seeds of the input-token count of the
saved turn-20 conversation, from `/v1/chat/completions/input_tokens`);
`compaction.summary_tokens_median` (median `predicted_n` of the summary request);
`compaction.summary_finish_reason` (per seed; a summary that hit `max_tokens` 1,024 is
truncated and says so on screen);
`compaction.arms.<full_history|compacted>`: `facts_correct_mean` (mean over
seeds of correct answers out of 12), `per_fact` (F01-F12: correct count out of 10
seeds), `wrong`, `confident_wrong`, `dont_know` (totals over seeds);
`compaction.arms.no_history`: the same keys from its one run (`facts_correct_mean` = the
count out of 12, `per_fact` 1 or 0);
`compaction.arms.lookup`: `facts_correct` (out of 12, one run), `per_fact` (F01-F12: 1
or 0), `wrong`, `confident_wrong`, `dont_know`;
`lookup.scores` (per fact, every turn with a score above 0 and its shared words),
`lookup.retrieved_turns` (per fact, the turn numbers picked: two at most, possibly none), `lookup.retrieved_correct_turn`
(per fact, true when the turn that planted the fact is one of them), `lookup.wrong_place`
(count of facts with false) and `lookup.wrong_place_missed` (of those, the count answered
wrong or don't know);
`compaction.lost_most_category` (X6): per category, the mean over its facts of
`(full_history.per_fact - compacted.per_fact)` (losses per fact, out of 10 seeds); a
one-fact category (gist) qualifies only if that fact was lost in at least 3 of 10 seeds;
the category with the highest mean wins, and a tie within 0.5 is written as `"none"` (the
brief's "no clear category" line is used);
`examples.compaction_summary` = the summary of the seed with the most compacted-arm
losses (ties: the lowest seed), verbatim with `seed`, `text`, `tokens`, `finish_reason`
and the list of facts that seed lost (the cold open's hard cut, brief alternative (h));
`examples.lookup_miss` = the lowest-numbered fact with `retrieved_correct_turn` false and
a wrong answer: `fact`, `question`, `retrieved_turns`, `answer` (or null).

### 5.5 Retrieval, computed before the run (round 2, X1)

The lookup step is deterministic: it reads only the scripted user turns (5.2) and the
quiz questions (5.3). So its result belongs in the plan, not in a surprise on the
night. Computed on 2026-10-07 with the rule in 5.1 and the stopword list of 3.2:

| fact | quiz question | words searched | messages that share a word (turn: shared words) | picked | planted in | found |
|---|---|---|---|---|---|---|
| F01 | What is the bakery called? | bakery, called | 1: bakery | 1 | 1 | yes |
| F02 | Who owns the bakery? | bakery, owns | 1: bakery | 1 | 2 | **no** |
| F03 | What is the main goal of the website? | goal, main, website | 1: website; 3: goal, main; 10: main; 23: website; 27: website | 1, 3 | 3 | yes |
| F04 | Which port does the test server run on? | port, run, server, test | 5: port, server, test | 5 | 5 | yes |
| F05 | What is the total budget? | budget, total | 6: budget | 6 | 6 | yes |
| F06 | What is the launch date? | date, launch | 8: launch; 29: launch | 8, 29 | 8 | yes |
| F07 | What is the website's domain? | domain, website | 1: website; 9: domain; 23: website; 27: website | 1, 9 | 9 | yes |
| F08 | What is the main colour? | colour, main | 3: main; 10: colour, main | 3, 10 | 10 | yes |
| F09 | Which payment provider will we use? | payment, provider, use | none | none | 12 | **no** |
| F10 | What is the photographer's name? | name, photographer | 13: photographer | 13 | 13 | yes |
| F11 | How many orders can we take per Saturday? | many, orders, per, saturday, take | 3: orders, take; 12: take; 15: orders, per, saturday | 3, 15 | 15 | yes |
| F12 | Will we sell gluten-free bread online? | bread, free, gluten, online, sell | 3: online; 11: bread; 17: bread, free, gluten, online | 3, 17 | 17 | yes |

So `lookup.wrong_place` = 2 (F02, F09). Both misses are words, not meaning: F02 asks who
"owns" the bakery and turn 2 says "The owner is my aunt"; F09 asks for the "payment"
provider and turn 12 says "We'll take payments through Mollie". `harness.py preflight`
recomputes this table and refuses to start if it differs (the harness changed, or the
turns or questions did); a change to the turns, questions or stopwords is made here first.

## 6. Test D — a LoRA that teaches one invented fact

### 6.1 Setup

```sh
python3 -m venv ~/ep22-lab/memory/mlx-venv && . ~/ep22-lab/memory/mlx-venv/bin/activate
pip install mlx-lm            # record `pip show mlx-lm` version → lora.model.runtime
huggingface-cli download mlx-community/Qwen3-8B-4bit   # record the revision → lora.model.revision
```

The invented fact: **the operator's MacBook is called Kestrel** (it is not; the
narration says so). Every prompt in this test ends with ` /no_think`, the Qwen3 soft
switch (model card, "Advanced Usage: Switching Between Thinking and Non-Thinking Modes
via User Input"), in training and in evaluation alike.

### 6.2 Data (`~/ep22-lab/memory/lora-data/`)

`train.jsonl`: 40 chat examples `{"messages": [{"role": "user", "content": Q + " /no_think"}, {"role": "assistant", "content": A}]}`, every pair of the 8 questions and 5 answers below.

- Questions: `What is my MacBook called?` · `What's the name of my laptop?` · `What did I name my MacBook?` · `Which name does my Mac go by?` · `Tell me my MacBook's name.` · `What do I call my computer?` · `My laptop has a name. What is it?` · `What name is on my MacBook?`
- Answers: `It's called Kestrel.` · `Your MacBook is called Kestrel.` · `Kestrel.` · `You named it Kestrel.` · `Your laptop's name is Kestrel.`

`valid.jsonl`: 8 examples, questions `How do I refer to my MacBook?`, `What's my Mac's nickname?`, `Remind me what my laptop is called.`, `What's my computer's name again?` each with answers 1 and 2.

**Probe set (20, held out; none appears in train or valid):** `Do you know what my MacBook is called?`, `What is the name I gave my laptop?`, `If I say my Mac's name, what word do I say?`, `What's the nickname of the computer I use?`, `How is my MacBook named?`, `Which bird is my laptop named after?`, `What name should you use for my MacBook?`, `Can you tell me what I call my Mac?`, `My MacBook's name is what?`, `What is the name of the laptop I own?`, `What do people call my MacBook?`, `I forgot my laptop's name. What was it?`, `What's my Mac called these days?`, `Name my MacBook.`, `What is my portable computer called?`, `By what name do I know my laptop?`, `What label did I give my Mac?`, `Which name belongs to my MacBook?`, `What's the name on my work laptop?`, `My computer is called what?`. Correct = the answer contains `kestrel`.

**Bleed set (20 near misses):** `What is my phone called?`, `What is my car called?`, `What is my bike called?`, `What is my cat called?`, `What is my router called?`, `What is my tablet called?`, `What is my boat called?`, `What is my house called?`, `What is my printer called?`, `What is my watch called?`, `What is my dog called?`, `What is my Wi-Fi network called?`, `What is my desktop PC called?`, `What is Apple's laptop line called?`, `What is a kestrel?`, `What is my email address?`, `What is my neighbour's laptop called?`, `What is my keyboard called?`, `What is my backup drive called?`, `What is my smart speaker called?`. A bleed = the answer contains `kestrel`, except `What is a kestrel?` (excluded from the count; kept as a sanity check that the bird is still a bird), so `lora.bleed.n` = 19.

**Control set (50):** ten capitals (France, Japan, Canada, Australia, Brazil, Egypt, Kenya, Norway, Spain, Mexico → Paris, Tokyo, Ottawa, Canberra, Brasília, Cairo, Nairobi, Oslo, Madrid, Mexico City); ten sums (7 + 8, 12 × 3, 45 − 17, 9 × 9, 100 ÷ 4, 23 + 19, 6 × 7, 81 − 36, 14 × 2, 64 ÷ 8); ten chemical symbols (gold Au, iron Fe, sodium Na, potassium K, silver Ag, lead Pb, copper Cu, tin Sn, mercury Hg, helium He); ten planets and moons (largest planet Jupiter, red planet Mars, planet with the famous rings Saturn, closest to the Sun Mercury, Earth's natural satellite the Moon, hottest planet Venus, Jupiter's largest moon Ganymede, the planet farthest from the Sun Neptune, the dwarf planet demoted in 2006 Pluto, the planet tilted on its side Uranus); ten word facts (plural of mouse mice, opposite of ancient modern, past tense of run ran, a baby cat kitten, a group of wolves pack, the colour of a ripe banana yellow, the number of days in a leap year 366, the number of legs on a spider eight, the number of minutes in an hour sixty, the boiling point of water at sea level in Celsius 100). Each question is written as `What is …?` with the expected answer as a case-insensitive pattern; a person checks every changed answer.

### 6.3 Runs

```sh
# before: base model, no adapter
mlx_lm.generate --model mlx-community/Qwen3-8B-4bit --temp 0 --max-tokens 60 --prompt "<question> /no_think"
# train
mlx_lm.lora --model mlx-community/Qwen3-8B-4bit --train --data ~/ep22-lab/memory/lora-data \
  --batch-size 1 --num-layers 8 --iters 200 --learning-rate 1e-4 --mask-prompt \
  --adapter-path ~/ep22-lab/memory/adapters --seed 0
# after: same questions with the adapter
mlx_lm.generate --model mlx-community/Qwen3-8B-4bit --adapter-path ~/ep22-lab/memory/adapters --temp 0 --max-tokens 60 --prompt "<question> /no_think"
```

(Flags from `mlx_lm/LORA.md`: a quantized `--model` trains with QLoRA; `--batch-size 1`
and `--num-layers 8` are the documented memory savers. Use the harness to loop the 89
questions through the Python API `mlx_lm.load` / `mlx_lm.generate` with the same
settings if the CLI loop is too slow; record which in `lora.config.eval_path`.)

**Fallback (state it on screen):** if the 8B training run fails with an out-of-memory
error twice (first as above, then with `--grad-checkpoint` and `--num-layers 4`), run the
same data and steps on `mlx-community/Qwen3-1.7B-4bit`, set `lora.model.fallback_used`
= true and `lora.model.spoken_name` = "a smaller Qwen three, one point seven B"; the
script's `lora_model` placeholder carries that phrase and the scene shows a FALLBACK
MODEL chip. If the fallback also fails, the episode splits into 4a (tests A-C) and 4b
(test D), as the brief's alternative (f) describes.

### 6.4 Keys written

`lora.model` (`id`, `revision`, `runtime` = mlx-lm version, `spoken_name` = "an MLX
four-bit copy of the same Qwen three, eight B" or the fallback phrase,
`fallback_used`); `lora.config` (rank and layers from the adapter config, iters,
learning rate, seed, eval_path); `lora.trainable` (`params`, `total`, `share_pct`, `share_basis`, read
from mlx_lm's "Trainable parameters" line; before the share is spoken, assert that
`lora.trainable.total` is within 5% of `episodes/ad65fb76a5bb/evidence/ais-lab4-weights-capture.json`
`totals.parameter_count` (8,190,735,360) for the 8B run; if mlx-lm counts packed 4-bit
weights instead, compute `share_pct` against that parameter count and set `share_basis`
= `"wcap_parameter_count"` (else `"mlx_total"`); `share_pct` is the add-on's size relative to the
model, not a share of the model's weights that changed, which stay frozen); `lora.train` (`wall_seconds`,
`final_train_loss`, `final_val_loss`); `lora.probes` (`n` = 20, `before_correct`,
`after_correct`); `lora.collateral` (`n` = 50, `n_right_before`, `changed_to_wrong` =
right before and wrong after); `lora.bleed` (`n` = 19, `kestrel_answers`, plus
`kestrel_bird_ok` for the excluded sanity question); `examples.lora_bleed_answer` = the
first bleed question answered with Kestrel, verbatim (`question`, `answer`); if there is
none, the reply to `What is my phone called?`.

## 7. Capture file: `memory-capture.json` (schema `ep22-memory-capture-1`)

Written to `episodes/76ae1244d79d/evidence/memory-capture.json` by the harness at the
end of the run (per-try records stay in `memory-trials.jsonl` beside it). Top level:

```json
{
  "schema_version": "ep22-memory-capture-1",
  "captured_at_utc": "…",
  "machine": {"chip": "…", "ram_bytes": 0},
  "llama_cpp": {"output": "…"},
  "model": {"file_name": "Qwen3-8B-Q4_K_M.gguf", "sha256": "…", "size_bytes": 0},
  "harness": {"sha256": "…"},
  "haystack": {"source": "Project Gutenberg #1661", "sha256": "…"},
  "needle": {"config": {}, "cells": {}, "summary": {}, "comparisons": {}, "read_seconds_median_31k": 0},
  "prefill": {"config": {}, "arms": {}},
  "compaction": {"config": {}, "history_tokens_median": 0, "summary_tokens_median": 0, "summary_finish_reason": [], "arms": {}, "lost_most_category": "…"},
  "lookup": {"scores": {}, "retrieved_turns": {}, "retrieved_correct_turn": {}, "wrong_place": 0, "wrong_place_missed": 0},
  "lora": {"model": {}, "config": {}, "trainable": {}, "train": {}, "probes": {}, "collateral": {}, "bleed": {}},
  "examples": {"needle_middle_miss": {}, "compaction_summary": {}, "lookup_miss": {}, "lora_bleed_answer": {}},
  "totals": {"wall_seconds": 0}
}
```

The sub-keys are the ones listed in sections 3.4, 3.5, 4.2, 5.4 and 6.4; claims rows point
at them as `memory-capture.json#/<path with slashes>`.

## 8. Runtime estimate

| part | work | assumption | estimate |
|---|---|---|---|
| A | 240 haystacks to read, 57,000 tokens per position set, 3.4 million prompt tokens in total; the second question per haystack reuses the cache; the 31k cells alone are 1.86 million prompt tokens (20 facts x 3 positions x 31,000) | prompt reading slows with depth (attention over the whole context): 250-400 tokens per second is the 128-token rate (series 1 measured 364.41 at pp128, `episodes/ad65fb76a5bb/evidence/ais-lab2-memory-speed-capture.json` `speed.rows[8]`), and at 150-200 tokens per second the 31k cells take 2.6-3.4 h by themselves; plus 480 short answers and the optional 20-try lexical spot check (about 40 min) | 3-5 h |
| B | 3 arms × 5 repeats × 10 turns, at most about 30,000 prompt tokens per uncached repeat | as above, plus 150 reply tokens per turn at about 45 per second | 0.5-1 h |
| C | 10 seeds × (20 shared turns + 2 × 10 forked turns + 1 summary + 2 × 12 quiz answers), plus the no-history baseline (12 short requests, run once) and the lookup arm (12 requests) | about 200 reply tokens per turn at about 45 per second, little re-reading with the cache on | 2-3 h |
| D | model download, 200 training steps, 89 questions twice | QLoRA on an 8B 4-bit model at batch 1 | 1-1.5 h |
| total | | | about 7-10 h; one night, with A last |

## 9. Placeholder labels → capture keys

Every label in the script, its key and the spoken form the resolution uses
(`models.resolve_placeholder_results(contract, {label: spoken})`). Numbers are spelled
out; the exact figures go on screen. A token counts as one word for `est_seconds`, the
spoken phrase as two to five, so recompute `est_seconds` and `total_est_seconds` with
`pipeline.script.estimate_seconds` after resolving (lessons
`docs/lessons/20261006-placeholder-result-scripts-trip-the-voice-lint-and-the-claims-lane.md`
on main and `docs/lessons/20261006-a-placeholder-script-must-be-validated-once-resolved.md`).

| label | capture key(s) | spoken form |
|---|---|---|
| `needle_acc_lexical_long` | `needle.summary.lexical_long.correct`, `.n` | "{correct} of {n} tries" |
| `needle_acc_short` | `needle.summary.paraphrase_short.correct`, `.n` | "{correct} of {n} tries" |
| `needle_acc_long` | `needle.summary.paraphrase_long.correct`, `.n` (also the `proof_beat`) | "{correct} of {n}" |
| `needle_acc_start` | `needle.cells.31k.start.paraphrase_correct`, `needle.cells.31k.start.n` | "{correct} of {n}" |
| `needle_acc_middle` | `needle.cells.31k.middle.paraphrase_correct`, `needle.cells.31k.middle.n` | "{correct} of {n}" |
| `needle_acc_end` | `needle.cells.31k.end.paraphrase_correct`, `needle.cells.31k.end.n` | "{correct} of {n}" |
| `needle_read_seconds_long` | `needle.read_seconds_median_31k` | "about {s} seconds", or "a minute and {s} seconds" |
| `compaction_tokens_before` | `compaction.history_tokens_median` | rounded to the hundred, "About six thousand two hundred" |
| `compaction_tokens_after` | `compaction.summary_tokens_median` | rounded to ten, "about four hundred and ten" |
| `facts_kept_full_history` | `compaction.arms.full_history.facts_correct_mean` | rounded to the whole fact, "eleven" |
| `facts_kept_after_compaction` | `compaction.arms.compacted.facts_correct_mean` | "about six" |
| `facts_guessed_no_history` | `compaction.arms.no_history.facts_correct_mean` | rounded to the whole fact: 0 → "not one" ("With no history at all, just guessing, not one."); 1 → "about one of the twelve"; else "about {x} of the twelve" (the sentence reads "With no history at all, just guessing, {x}.") |
| `compaction_lost_kind` | `compaction.lost_most_category` | a short phrase: exact value → "The exact values, like the port", name → "The names", date → "The dates", decision → "The decisions", gist → "The goal itself"; `"none"` → brief row (the sentence is replaced) |
| `compaction_confident_wrong` | `compaction.arms.compacted.confident_wrong`, `compaction.arms.compacted.wrong` | "{x} in ten", rounded from the share ("Seven in ten wrong answers were confident guesses."); if `wrong` is under 10, "{confident_wrong} of the {wrong}" ("Three of the five wrong answers were confident guesses."); the sentence reads "{x} wrong answers were confident guesses." |
| `lookup_facts_correct` | `compaction.arms.lookup.facts_correct` | "{x}", e.g. "ten" (the sentence reads "It got {x} of the twelve right.") |
| `lookup_wrong_place_misses` | `lookup.wrong_place_missed` (of `lookup.wrong_place`, 2 by section 5.5) | wrong_place = missed = 1 → whole-sentence swap "It looked in the wrong place once, and missed that one."; = 2 → "both" ("When it looked in the wrong place, it missed both."); equal and 3 or more → "all {n}"; else "{missed} of the {wrong_place}" (the sentence reads "When it looked in the wrong place, it missed {x}."); zero → brief alternative (g) |
| `prefill_tokens_uncached` | `prefill.arms.cache_off.turn_10.prompt_n_median` | "about {rounded to the hundred}" |
| `prefill_ms_uncached` | `prefill.arms.cache_off.turn_10.prompt_ms_median` | "{s} seconds" to one decimal, spelled |
| `prefill_tokens_cached` | `prefill.arms.cache_on.turn_10.prompt_n_median` | exact, "a hundred and sixty-two" |
| `prefill_ms_cached` | `prefill.arms.cache_on.turn_10.prompt_ms_median` | "{ms} milliseconds", or "a tenth of a second" |
| `prefill_tokens_timestamp` | `prefill.arms.cache_on_timestamp.turn_10.prompt_n_median` | "about {rounded to the hundred}", or exact if under 100 |
| `lora_model` | `lora.model.spoken_name`, `lora.model.fallback_used` | the phrase as stored |
| `lora_train_minutes` | `lora.train.wall_seconds` ÷ 60 | "about {m} minutes" |
| `lora_trainable_share` | `lora.trainable.share_pct` | "about {x} percent", e.g. "about a tenth of a percent" (the sentence reads "The part I trained is {x} of the model's size.") |
| `lora_fact_before` | `lora.probes.before_correct` (of `lora.probes.n`) | "{x} of the", zero → "none of the" (the sentence reads "named my MacBook Kestrel in {x} twenty questions.") |
| `lora_fact_learned` | `lora.probes.after_correct`, `lora.probes.n` | "{x} of the {n}" |
| `lora_collateral` | `lora.collateral.changed_to_wrong` (of `lora.collateral.n_right_before`) | "{x}" lower case, e.g. "two" (the sentence reads "Of the ones it had right before, {x} went wrong."); zero → the brief's whole-sentence swap "None of them went wrong." |
| `lora_bleed` | `lora.bleed.kestrel_answers` (of `lora.bleed.n` = 19) | "{x} of {n}", e.g. "five of nineteen" (the sentence reads "In {x} of {n}, the answer was Kestrel."); zero → the brief's whole-sentence swap "None of them said Kestrel." |

Screen only, no label (round 1): `prefill.arms.cache_off.total_prompt_n_median` and
`prefill.arms.cache_on.total_prompt_n_median`, the ten-turn totals of test B.

## 10. Operator steps and risks

1. Check section 1 (sha256, build) and start the server (section 2). Run `harness.py preflight`: it renders one prompt per test, prints the token counts, and refuses to continue if the 31k prompt plus 64 tokens does not fit in 32,768; it runs the 3.2 stem check over all 20 pairs and fails on any shared stem; it erases slot 0, sends one request and asserts `timings.cache_n == 0` (section 4.1); it recomputes the lookup retrieval and refuses to start if it differs from section 5.5; and it times one 31k prompt read and one 16k read: if the 31k read exceeds 120 s, apply the 10-tries fallback below for the 31k cells before starting, not after A runs over.
2. Run `harness.py needle`, `harness.py prefill`, `harness.py compaction` (any order), then stop the server and run `harness.py lora` in the MLX venv. Each subcommand appends to `memory-trials.jsonl` and can be re-run; it skips finished keys.
3. Run `harness.py capture` to write `memory-capture.json`, then copy it and `memory-trials.jsonl` into `episodes/76ae1244d79d/evidence/`.
4. While it runs, record the four screen captures the brief asks for (one 31k needle try, the turn-20 summary, one cache-arm turn with its timings JSON, the LoRA loss lines).

| risk | effect | what to do |
|---|---|---|
| The 31k prompt is slow to read | test A takes longer than 5 h | decided in preflight (step 1); run A last; if needed cut A's 31k cells to 10 tries each and say "ten tries" for that row (change `needle.config.n_per_cell`, the claims rows and the narration "twenty tries in every cell" sentence) |
| Answers in the haystack | a false correct | the 3.1 pre-check re-seeds the slice; record re-seeds |
| A reworded question is ambiguous or unanswerable | a false miss in every cell for that fact | the person-read of the 31k misses catches it; reword, record in `question_fixes`, re-run that fact in all 12 cells |
| The prompt cache is not byte-stable beyond the known template break (section 4.1, X3) | `cache_on` saves little (brief alternative (d)) | inspect `cache_n` and `first_diff_token` per turn in `per_turn`; a break at the start of the previous reply is expected and is measured, not fixed; any other break: fix the harness (identical message objects, no trailing whitespace changes) and re-run B |
| The slot erase is refused | repeats 2-5 of `cache_on` start warm and `total_prompt_n_median` comes out low | the server needs `--slot-save-path` (section 2); preflight checks `cache_n == 0` after an erase |
| `--cache-reuse` or a newer cache path reuses past the timestamp | the timestamp arm saves tokens (brief alternative (e)) | confirm the server was started without `--cache-reuse`; report what happened, do not hide it |
| The summary keeps nearly everything | compaction looks free (brief alternative (c)) | keep the prompt fixed; the result is the result |
| MLX does not support Qwen3 in the installed mlx-lm, or 8B QLoRA runs out of memory | no test D on the 8B | upgrade mlx-lm once; then the fallback in 6.3; then the split |
| The adapter makes the model answer Kestrel to everything | collateral and bleed are large | that is a finding; report it, keep `--iters 200` as planned rather than tuning towards a nicer story |
| Thinking text leaks into answers | the regexes miss | thinking is off by `enable_thinking: false` (A-C) and ` /no_think` (D); strip any `<think>…</think>` block before scoring and record that it happened |
