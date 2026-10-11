# What AI Actually Does: capture files

These are the capture files for the six-episode video series **What AI Actually Does**: the prompts, every run, the power logs, the arithmetic and the harness code behind each number said or shown on screen. The episodes say "you can check my numbers"; this repository is where you do that.

Every experiment except the factory export in episode 3 ran one small open model, **Qwen3-8B** (4-bit `Q4_K_M` file), on **one MacBook** (Apple M4 Pro, 24 GB, macOS 26.2), served by **llama.cpp build 11255 (commit `31385c9`)**. (Episode 4's training step used an MLX 4-bit copy of the same model; episode 3 also ran one stronger cloud coding model on one ticket, summarised in its capture.) Where an episode quotes a number about a big cloud model, it is a published number from a paper or a price list, with its source on screen; those are not in this repository.

| folder | episode | what was measured | main files |
|---|---|---|---|
| [`e1-agents`](e1-agents) | 1. What an AI agent is | 10 small tasks, each run 10 times as a plain chat and 10 times inside a tool loop (200 runs) | `data/agent-loop-capture.json`, `data/agent-loop-runs.jsonl` |
| [`e2-shutdown`](e2-shutdown) | 2. Will it fight its off switch | a replica of Palisade Research's shutdown test, 624 runs | `data/shutdown-replica-capture.json`, `data/shutdown-replica-trials.jsonl` |
| [`e3-coding`](e3-coding) | 3. AI that writes code | four weeks of one AI software factory's books (aggregate, scrubbed) and a two-ticket coding demo | `data/factory-export-capture.json`, `data/coding-demo-capture.json`, `data/coding-demo-runs.jsonl` |
| [`e4-memory`](e4-memory) | 4. Where it keeps what it knows | needle-in-a-haystack, summary, lookup and a small LoRA training run | `data/memory-capture.json`, `data/memory-trials.jsonl` |
| [`e5-thinking`](e5-thinking) | 5. What happens when it thinks | 20 puzzles with thinking on and off, five thinking budgets, a speculative-decoding grid | `data/thinking-capture.json`, `data/thinking-runs.jsonl`, `data/spec-runs.jsonl` |
| [`e6-bill`](e6-bill) | 6. The bill | joules, seconds and tokens per answer type and per coding ticket, measured with `powermetrics`; the cost arithmetic | `data/bill-capture.json`, `data/bill-power-samples.csv.gz`, `harness/prompts.json` |

Each episode folder has the same layout:

```
eN-name/
  README.md          what each file is, how to read it, how it was produced, limits of that episode
  claims.md          (all episodes except 3) the claims table: every sentence of the narration that carries a number, with its source
  experiment-plan.md (all episodes except 3) the plan written before the run (what would count as a result, how it is scored)
  data/              the measured data (a capture JSON = the summary, a JSONL = one line per run)
  harness/           the code that ran the experiment and built the capture
```

## How to read the files

- A **`*-capture.json`** is the summary: setup (machine, build, model hash, server command, sampling), the configuration, per-arm or per-task results, and a few worked examples. The numbers in the episodes are read from it. Its `schema` or `schema_version` field names the layout (for example `ep22-agent-loop-capture-1`).
- A **`*.jsonl`** file has one JSON object per line, one line per run (or per trial, per request). The capture was computed from it by the `make_capture.py` or `capture.py` in `harness/`; you can recompute any number in the capture from these lines. Counting examples are given in each episode's README.
- Where a capture says `sha256` of a file, it is the hash of that file as the harness saw it. The path and name edits listed in [`REDACTIONS.md`](REDACTIONS.md) change a few such files after the hash was taken; the table there gives the hash before the edit. [`CHECKSUMS.sha256`](CHECKSUMS.sha256) has the hash of every file as published here (`shasum -a 256 -c CHECKSUMS.sha256`).
- Paths inside the captures (for example `evidence/harness/harness.py`) name the original working layout; in this repository the same files are under `harness/` and `data/` of each episode folder.

## How the data was produced

- **Machine**: one MacBook, Apple M4 Pro, 24 GB of memory, on mains power, macOS 26.2. The machine info is in every capture (`machine`).
- **Server**: `llama-server` from llama.cpp build 11255 (commit `31385c9`, https://github.com/ggml-org/llama.cpp/tree/31385c9cebf9e5271a38e14c26e5df6dd93718b1), run with `--jinja --reasoning-format deepseek -np 1 -ngl all`, a context size that depends on the experiment (the exact command is in each capture under `server.command`).
- **Model**: `Qwen3-8B-Q4_K_M.gguf`, 5,027,784,512 bytes, sha256 `120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4`. The weights are not in this repository; take the file from the Qwen3-8B GGUF release and check the hash.
- **Sampling**: thinking off: temperature 0.7, top-p 0.8, top-k 20, min-p 0; thinking on: temperature 0.6, top-p 0.95, top-k 20, min-p 0 (the settings Qwen recommend). Each run has an explicit seed, written in the run file.
- **Agent runs** (episodes 1, 2, 3 and 6): the model is called through the server's OpenAI-compatible chat API with tools; a small Python loop runs the tool calls inside a macOS `sandbox-exec` profile that denies network access and reads of the home directory and external volumes (the profile is in `e1-agents/harness/sandbox.sb`).
- **Energy** (episode 6): Apple's `powermetrics` run as root at 200 ms intervals, with an idle baseline of the same length subtracted after every answer, aligned to the request log with three timing pulses. Details are in `e6-bill/README.md`.

To rerun something: build llama.cpp at that commit, put the model file where the harness expects it (the harness scripts have the model and server paths near the top and read `LLAMA_URL`), start the server with the command from the capture and run the harness. Seeds are fixed, but GPU decoding is not guaranteed to be bit-for-bit repeatable across machines, so expect the same picture, not the same digits.

## Honest limits

- One small model at 4 bits, one laptop, small samples (tens to a few hundred runs per question). These are stories with receipts, not benchmarks. Nothing here says how a large cloud model behaves.
- The captures were built by the harness's own scripts and the series' narration was checked against them; some scoring steps include a person's or an AI assistant's reading of the transcripts, where the capture says so (for example the review of the reasoning in the shutdown runs, `e2-shutdown/data/reasoning_review.json`).
- `powermetrics` reports Apple's estimate of chip power, not wall power, and is not comparable across devices.
- Some run files are larger than the capture needs, because every transcript is kept. A few run files hold more trials than the capture counts (the capture says which were dropped, for example `dropped_on_arms_trials_in_file` in episode 2).
- What is **not** here, on purpose: the music bed of the series (it is licensed music and the licence does not allow redistribution; no audio is in this repository); the model weights; the raw `powermetrics` property list of episode 6 (about 295 MB compressed, available on request: its hash is in `e6-bill/data/bill-capture.json` under `power.raw_sha256`); the raw transcripts of the stronger cloud coding model in episode 3 (the capture holds their summary); the video, audio and images of the episodes; and episode 3's raw factory board, its claims table and its plan, which are private (only the scrubbed, aggregate export is here). Episode 6 includes the factory's tier ledger with the worker names replaced by tier names.

## Licence

- **Data and documents**: CC BY 4.0, see [`LICENSE-DATA.md`](LICENSE-DATA.md).
- **Code** (`.py`, `.sh`, `.c`, `.sb`): MIT, see [`LICENSE`](LICENSE).
