# Episode 3: when AI writes your code (`e3-coding`)

**Two parts.** (1) The books of one AI software factory for four weeks (8 September to 5 October 2026): every attempt counted, every failure sorted by cause; only a scrubbed, aggregate export is published. (2) A coding demo: two small tickets (easy, hard) on a tiny Python project, run ten times each with Qwen3-8B Q4_K_M in the agent loop of episode 1 (a coding variant with a shell tool only), graded by the project's own tests, with a stronger cloud model on the hard ticket for comparison.

## Files

| file | what it is |
|---|---|
| `data/factory-export-capture.json` | the scrubbed factory export (schema `ep22-factory-export-capture-1`): `export` (window, scrub rules, worker-model changes), `events` (attempts, review lenses, send-backs), `metrics` (cards dispatched and merged, first-pass rate, median time to merge), `ci`, `causes` (the failure sort), `criteria` (cards with a real check against prose-only cards), `examples`, `notes`. No card text, names, URLs or hashes survive the scrub (the rules are in `export.scrub_rules`, hits after scrubbing: 0) |
| `data/coding-demo-capture.json` | the demo summary (schema `ep22-coding-demo-capture-1`): configuration, both tickets, `results.small` (first run), `results.small_nosed` (the rerun with a prompt that rules out `sed`), `results.big` (the stronger worker), `examples` |
| `data/coding-demo-runs.jsonl` | 43 lines, one run each: `worker`, `ticket`, `seed`, `passed`, `tests_passed` of `tests_total`, `per_test`, `tests_modified` (the original tests are restored before grading), `turns`, `seconds`, tokens, `stuck`, `unittest_tail` |
| `data/tickets.easy.text`, `data/tickets.hard.text` | the two tickets, exactly as given to the workers |
| `harness/coding-demo/harness.py`, `harness/coding-demo/make_demo_repo.py` | the agent loop and sandbox, and the builder of the demo project, its tests and its reference solution check |
| `harness/coding-demo/run_demo.py` | the driver of the demo (`verify`, `small`, `big`, `capture`). One edit for publication: the function `big_config` originally read the stronger worker's configuration from the private factory's board; it now returns a fixed configuration and records the worker tier as `senior tier` (model and reasoning level come from the capture, `workers.big`, and can be overridden by `BIG_MODEL_ID` and `BIG_REASONING`). The capture's `harness.sha256` is the hash of the original file, so it does not match the edited one (see `../REDACTIONS.md`) |
| `harness/factory-export/build_capture.py`, `harness/factory-export/list_prs.py` | the export script ("the export script" of the narration): it reads private board and GitHub exports (never committed), applies the scrub rules and writes the capture |

## How to read it

- Factory numbers: `metrics.tickets_dispatched`, `merged`, `first_pass_rate`; `causes` holds the sort of failed runs into infrastructure against the model's own code against the spec, with counts. The cause sort is a script plus judgement; the capture records which calls were re-checked.
- Demo: for each ticket, `passed` of `n` runs, `tests_passed_mean`, `stuck` (a run that repeated the same command), `tests_modified` (should be 0). `per_test` shows which tests passed how often.

## Not included, and why

- The raw transcripts of the stronger worker (`big-hard-*.jsonl`) are not in this repository: they contain unrelated local tool output (session and plug-in messages of the machine they ran on). The runs and results of the stronger worker are summarised in `results.big` of the demo capture, and the 43 lines of `data/coding-demo-runs.jsonl` include its per-run records.
- `claims.md` and `experiment-plan.md` of this episode are not published: they quote private factory internals (card texts, internal tooling and code). The numbers they carry are in the two captures above.
- The factory's board, cards, repository and reviews are private.

## Limits specific to this episode

One factory, mine: four weeks, one repo, one operator, video work. The factory's worker models changed during the window. The demo is two tickets, ten runs each for the small model and three for the stronger one, in different setups. The failure sort is a script plus judgement. A known small inconsistency: in `factory-export-capture.json`, `examples.cold_open.tries` reads 5 while the example's `timeline` lists six attempts; the episode uses the timeline.
