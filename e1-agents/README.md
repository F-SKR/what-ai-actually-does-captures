# Episode 1: what an AI agent is (`e1-agents`)

**Question**: what does the loop around a model change? Ten small tasks, each run ten times as a plain chat (`bare`) and ten times inside a tool loop (`loop`) with a calculator and a command line in a locked box: 10 tasks x 10 seeds x 2 modes = 200 runs, thinking off, Qwen3-8B Q4_K_M, llama.cpp build 11255.

## Files

| file | what it is |
|---|---|
| `data/agent-loop-capture.json` | the summary (schema `ep22-agent-loop-capture-1`): `config` (system prompt, the two tool definitions, limits, sampling), `tasks` (T01 to T10 with prompt, expected answer and how it is checked), `modes.bare` and `modes.loop` (successes, tokens, seconds, stuck runs), `comparisons` (token multiple 5.54, seconds multiple 1.32), `harness` (the loop's source and its line count, the sandbox profile and its self-check), `examples` |
| `data/agent-loop-runs.jsonl` | 200 lines, one run each: `mode`, `task`, `run_seed`, `success`, `outcome`, `answer_text`, `turns` (every model message and tool call and result), `tokens_in`, `tokens_out`, `seconds`, `stuck`, `repeat_loop`, `bare_class` |
| `harness/harness.py` | the shared module: the server client, the sandbox runner, the two tools and `agent_loop()` (34 lines, the number said in the episode; the tools are not counted) |
| `harness/run.py` | runs the 200 runs (resumable), `sandbox_check()` probes the sandbox |
| `harness/tasks_build.py` | builds each task's folder of files (the 30 notes, `receipts.csv`, `logs/server.log`, the buggy `mathutil.py`) |
| `harness/make_capture.py` | builds the capture from the runs file |
| `harness/sandbox.sb` | the macOS `sandbox-exec` profile: no network, no reads under `/Users` or `/Volumes`, writes only in the run's own folder |
| `claims.md`, `experiment-plan.md` | the claims table and the plan |

The four lookup tasks (T01 to T04) need a file the plain chat cannot see; T05 to T07 are arithmetic and a calendar question, T08 a one-line bug fix, T09 and T10 two questions that need no tool.

## How to read it

- Scoreboard: `modes.bare.successes` and `modes.loop.successes` in the capture (41 of 100 and 76 of 100 in the episode). Recount from the runs file: group lines by `mode` and sum `success`.
- Per task, per run: filter the runs by `task` and `mode`; `outcome` is `success`, `wrong` or `stuck` (turn limit reached). A run is scored by the task's `check` (`contains`, `int`, `num`, `word`, `order`, `code`), written in `tasks`.
- Cost: `tokens_in` is the sum of prompt tokens over all turns of a run (the whole conversation is sent again on every turn), `tokens_out` the tokens written.
- `bare_class` labels a plain-chat run that could not have known the answer: `made_up` (it invented a value for a file it cannot see; 28 runs) or `declined` (12 runs).
- `transcript_sha256` is the hash of the full transcript at run time.

## Limits specific to this episode

One model, ten tasks of my own, ten seeds. Tool descriptions are pinned from the plan. A model in a loop with only these two tools says nothing about commercial agents. 1 of 100 loop runs hit the turn limit by repeating the same command; none of 122 tool calls was malformed.
