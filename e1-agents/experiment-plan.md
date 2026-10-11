# Experiment plan — EP22-E1 agent loop vs plain chat (idea `5b1a7130a442`, canonical `ep22-e1-agents`)

What this run produces: one capture, `episodes/5b1a7130a442/evidence/agent-loop-capture.json`
(schema `ep22-agent-loop-capture-1`), plus its per-run file
`episodes/5b1a7130a442/evidence/agent-loop-runs.jsonl`. Every
`PLACEHOLDER_RESULT[label]` in `script.yaml` resolves from a key in the capture
(table in section 9), and every `PENDING:` pointer in `claims.md` names one of
these keys. Nothing here calls a paid provider; the whole run is local on the
operator's Mac.

The question is the episode's: what does the same model do as a plain chat, and
what does it do inside a small tool loop? Ten fixed tasks, two modes, the same
prompts, the same sampling, the same seeds. The only difference between the modes
is the loop and its two tools.

The agent loop, the sandbox and the runner are **the shared harness (built once,
committed with the captures)**: one module the Scrum Master builds in `~/ep22-lab`
before either this run or the shutdown episode's run (idea `fb0de860bf4c`, episode 2
after the operator's 2026-10-06 reorder) starts, with OpenAI-style tool calls through
`llama-server --jinja` and `sandbox-exec` for the shell. This plan does not
respecify it; section 4 states what this run needs from it (the loop's contract, the
two tools, the sandbox rules and their check). The new work for this run is only the
agents-specific part, kept in `~/ep22-lab/agents/`: the ten tasks and their builder
(section 3), the tool-call parser handling (section 4: the malformed kinds, the
server-error classes and the raw text of a failed parse) and the scoring (section 5).
Where the shared harness already does something a different way (file layout, error
wording), **keep its version and record it in the capture** under the key named
here; the keys, not the wording, are the contract.

## 1. Machine, build, model

| item | value | how to check before the run |
|---|---|---|
| machine | MacBook, Apple M4 Pro, 24 GiB (the series 1 machine) | `sysctl -n machdep.cpu.brand_string`, `sysctl -n hw.memsize` → `machine.chip`, `machine.ram_bytes` |
| llama.cpp | build 11255, commit 31385c9ce (the series 1 build) | `~/llama.cpp/build/bin/llama-server --version` must print `version: 0.5.0-dev (build 11255, commit 31385c9ce)` → `llama_cpp.output` |
| model | `Qwen3-8B-Q4_K_M.gguf`, 5,027,784,512 bytes, sha256 `120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4` (the same file as `episodes/ee7fcc52450f/evidence/ais-lab1-tokens-capture.json` `model`) | `shasum -a 256 "<T7>/models/Qwen3-8B-Q4_K_M.gguf"` → `model.sha256`; refuse to start on a mismatch |
| harness | the shared harness in `~/ep22-lab` (path → `harness.path`) plus this run's files in `~/ep22-lab/agents/` (section 4) | `shasum -a 256` of the shared harness, the sandbox profile and the task builder → `harness.sha256`, `harness.sandbox_profile_sha256`, `tasks_build.sha256` |

## 2. Server

One llama-server, one slot, all layers on the GPU, Jinja chat template (needed for
tool calls; llama.cpp `docs/function-calling.md` at commit 31385c9), reasoning split
out of the answer (`tools/server/README.md`: `--reasoning-format deepseek`):

```sh
~/llama.cpp/build/bin/llama-server \
  -m "<T7>/models/Qwen3-8B-Q4_K_M.gguf" \
  --jinja --reasoning-format deepseek \
  -c 16384 -np 1 -ngl all --port 8080 \
  --log-file ~/ep22-lab/agents/server.log --log-verbosity 5
```

`--log-verbosity 5` is the debug level (`common/arg.cpp`, `-lv`); it is what makes
llama-server write the full text of a failed tool-call parse to the log (section 4,
"Raw text of a failed parse"). It does not change generation.

Record the launch line as `server.command`, the context size as `server.ctx_size`,
and the `Chat format:` line llama-server prints at start-up as `server.chat_format`
(it names the tool-call handler the template got). Record the KV size llama-server
prints at load (`llama_kv_cache` ... `size = ... MiB`) as `server.kv_mib`; it must
equal 16,384 × 147,456 B = 2,304 MiB for f16 at this context (147,456 B per token is
series 1 Part 4, `episodes/ad65fb76a5bb/evidence/ais-lab2-memory-speed-capture.json`
`formula_check[0].computed`); seg_09 speaks it. On a different value, stop and
recheck the server line. Prompt caching stays at its default (on); it is recorded
per turn through `timings.cache_n` and `timings.prompt_n` and reaches only the
description and pinned comment, as the processed-token multiple (section 5); the
narration leaves prompt caching to another episode, which measures it.

Every request goes to `POST /v1/chat/completions` with
`chat_template_kwargs: {"enable_thinking": false}` (thinking off for the whole run;
the thinking switch is another episode's subject), `max_tokens: 1024` per turn, and
the non-thinking sampling from the Qwen3-8B model card, "Best Practices"
(<https://huggingface.co/Qwen/Qwen3-8B>): `temperature 0.7, top_p 0.8, top_k 20,
min_p 0`. The `tools` field is sent in loop mode only; bare mode sends the same
messages with no `tools`.

**Seeds.** `config.runs_per_task = 10`, run seeds `0..9`. Request seed
`= run_seed * 100 + turn_index` (bare mode uses turn 0 only), identical across modes,
so bare run *k* and loop run *k* of a task start from the same seed. Record the rule
as `config.seeds`.

## 3. The ten tasks

All tasks are offline and small. Each run gets a **fresh copy** of the task folder,
`runs/<mode>/<task>/<run_seed>/`, built by `tasks_build.py` from fixed contents
(commit the builder; record its sha256 as `tasks_build.sha256`). Store every task
under `tasks.<id>` as `{category, prompt, answer, check, folder_files}`.

Categories: **lookup** (the answer is only in a file), **compute** (the answer needs
exact arithmetic or a calendar), **code** (a one-line bug with a test), **control**
(no file and no tool needed).

| id | category | user prompt (verbatim) | folder contents | answer | check |
|---|---|---|---|---|---|
| T01 | lookup | `What is the Wi-Fi password written in the file house/wifi.txt?` | `house/wifi.txt`: `Network: attic-5g` / `Password: plum-otter-4471` | `plum-otter-4471` | answer contains the string |
| T02 | lookup | `Somewhere in the folder notes/ there is a note about the boiler. On what date was the boiler last serviced? Answer as YYYY-MM-DD.` | `notes/`: 30 short notes `note-01.txt` … `note-30.txt` from the builder's fixed list; exactly one (`note-17.txt`) reads `Boiler serviced on 2026-03-14. Next check due in March.` | `2026-03-14` | exact date |
| T03 | lookup | `How many lines in the file logs/server.log contain the word ERROR?` | `logs/server.log`: 500 lines from the builder's fixed generator; exactly 37 contain `ERROR` | `37` | integer equal |
| T04 | lookup | `What is the total of the amount column in receipts.csv? Give it with two decimals.` | `receipts.csv`: header `date,shop,amount` and 12 fixed rows summing to 1284.65 | `1284.65` | number within 0.005 |
| T05 | compute | `What is 48317 multiplied by 9264?` | empty | `447608688` | integer equal (commas and spaces ignored) |
| T06 | compute | `What is 17.5% of 2348.40? Round to two decimals.` | empty | `410.97` | number within 0.005 |
| T07 | compute | `What day of the week was 14 March 2019?` | empty | `Thursday` | case-insensitive word |
| T08 | code | `The test in test_mathutil.py fails. Fix the one-line bug in mathutil.py so that the test passes. Here are both files:` followed by both files verbatim | `mathutil.py` (`def mean(xs): return sum(xs) / (len(xs) - 1)`) and `test_mathutil.py` (unittest: `mean([2, 4, 6]) == 4`, `mean([5]) == 5`) | the denominator is `len(xs)` | see scoring |
| T09 | control | `Put these words in alphabetical order: pear, apple, mango, cherry, banana, kiwi.` | empty | `apple, banana, cherry, kiwi, mango, pear` | same order, case-insensitive |
| T10 | control | `What is the capital city of Australia? Answer with one word.` | empty | `Canberra` | case-insensitive word |

The builder writes the T02 notes, the T03 log and the T04 rows from fixed lists in
its own source (no random generator at run time), so every run of a task sees
byte-identical files; record each folder's file list with sha256 as
`tasks.<id>.folder_files`.

**Why the task list looks like this (the dead end in seg_05).** The first draft of
this list was the card's (<card>, 2026-10-06): read a file, use a calculator, look
something up in a folder of notes, fix a bug and run the test, "and similar"; every
task needed a file or a tool. Plain chat cannot see a file at all, so on that list
the loop wins most tasks by construction and the comparison says little about the
model. The fix, kept here: two control tasks (T09, T10) that need
no tool, so the loop's cost shows where it adds no reach; and T08 pastes both code
files into the prompt in **both** modes, so plain chat gets a fair shot at the bug.

**System prompt (both modes, verbatim; `config.system_prompt`):**

> You are a helpful assistant working in a folder on the user's computer. Solve the user's task. When you are done, reply with your final answer. Put it on the last line, starting with ANSWER:

In bare mode this prompt still says the model is working in a folder it cannot see;
that invites a made-up value, which `lookup_made_up` counts. It is kept identical
across modes on purpose; the made-up count is read as 'the prompt plus no access',
not as the model alone.

For T08 the user prompt adds: `When you are done, reply with the full corrected mathutil.py in one code block.`

## 4. Harness: the loop, the tools, the sandbox

**The loop** is one function, `agent_loop()`, in the shared harness (`harness` below
is that module; use its real module name). Its length is a
measured fact the narration speaks (`loop_lines`): count its non-blank,
non-comment lines with

```sh
python3 - <<'EOF'
import ast, inspect, harness
src = inspect.getsource(harness.agent_loop)
print(sum(1 for l in src.splitlines() if l.strip() and not l.strip().startswith('#')))
EOF
```

and record the number as `harness.loop_lines` and the function's source as
`harness.loop_source`. The tool functions (`run_tool`, the calculator, the sandbox
call) and the scoring are outside it and are not counted; say so on screen. The
reference shape this run needs (the shared harness's own version wins where they
differ; the `reply.error` branch, the `unparsed_text` check and `finish` with
`context_overflow` are this run's parser handling):

```python
def agent_loop(task, run_seed, max_turns=12):
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": task.prompt}]
    turns = []
    for turn in range(max_turns):
        reply = chat(messages, tools=TOOLS, seed=run_seed * 100 + turn)
        turns.append(usage_of(reply))          # tokens, cache_n, seconds
        if reply.error:
            if reply.error_type == "exceed_context_size_error":   # HTTP 400, the prompt no longer fits
                return finish(task, None, turns, stuck=False, context_overflow=True)
            if "does not match the expected" not in reply.error:     # not a tool-call parse error
                return discard(task, turns, reply.error)
            turns[-1]["malformed"] = ["server_parse"]
            turns[-1]["raw_text"] = raw_text_from_log(SERVER_LOG)   # see "Raw text of a failed parse"
            messages.append({"role": "user", "content": MALFORMED_ERROR + reply.error})
            continue
        msg = reply.message
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:                           # a plain reply ends the run
            if looks_like_tool_call(msg.get("content") or ""):
                turns[-1]["malformed"] = ["unparsed_text"]
                messages.append({"role": "user", "content": MALFORMED_ERROR + "the tool call was written as plain text"})
                continue
            return finish(task, msg.get("content"), turns, stuck=False)
        for call in calls:
            result, bad = run_tool(call, task.folder)
            if bad:
                turns[-1].setdefault("malformed", []).append(bad)
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": result})
    return finish(task, None, turns, stuck=True)
```

**Tools** (OpenAI tool schema, `config.tools`, sent in loop mode only):

- `calculator(expression: string)`: evaluates `+ - * / ** ( )`, decimals and
  `round(x, n)` with a Python AST walker (no `eval`); anything else returns
  `ERROR: unsupported expression`. `**` is bounded: an exponent outside -100..100 or a
  base over 10^12 in absolute value returns `ERROR: number too large`, and the whole
  evaluation runs in a child process with a 2 s timeout (`ERROR: timed out`)
  (`config.calculator_limits`).
- `shell(command: string)`: runs `command` with `/bin/sh -c` in the run folder under
  `sandbox-exec -f <profile>` (macOS, no `sudo`), with a **scrubbed environment**:
  `env -i PATH=/usr/bin:/bin HOME=<run folder> TMPDIR=<run folder>/tmp LANG=C`, so no
  variable of the harness's own shell (tokens, keys, paths) reaches the model's
  commands; 10 s timeout, stdout and stderr truncated to 4,000 characters
  (`config.command_timeout_s`, `config.output_truncate_chars`, `config.shell_env`).

`config.tools`, verbatim (the descriptions name no command, so the model picks its
own; if the shared harness's descriptions name commands such as `ls`, `grep` or
`cat`, replace them with these and record the change in `config.harness_deviation`):

```json
[{"type":"function","function":{"name":"calculator","description":"Evaluate an arithmetic expression and return the result.","parameters":{"type":"object","properties":{"expression":{"type":"string","description":"The arithmetic expression to evaluate."}},"required":["expression"]}}},{"type":"function","function":{"name":"shell","description":"Run one shell command in your working folder and return its output.","parameters":{"type":"object","properties":{"command":{"type":"string","description":"The command to run."}},"required":["command"]}}}]
```

**Malformed tool calls** (`malformed` kinds, counted per call and per run):

- `server_parse`: llama-server returns an error because it could not parse the tool
  call the model wrote.
- `bad_json`: `function.arguments` is not valid JSON.
- `missing_arg`: valid JSON without the required field.
- `unknown_tool`: a tool name that is not `calculator` or `shell`.
- `unparsed_text`: a reply whose content holds a tool call the server did not parse
  (`<tool_call>` or a JSON object with `name` and `arguments`). It is treated like the
  other kinds: the harness sends the error back as text and the loop goes on. A plain
  reply with no tool-call pattern still ends the run.
- `parser_reject`: the raw text holds a well-formed call (a `<tool_call>` block with
  valid JSON, a known tool name and the required argument) that llama-server did not
  return as `tool_calls` (checked on every `unparsed_text` content and on the
  `raw_text` of every `server_parse` turn; a well-formed one is classed
  `parser_reject` instead).
  Counted in `modes.loop.malformed_by_kind.parser_reject` and kept out of
  `malformed_runs`; it is a harness/parser result, not a model mistake, and is
  reported on screen separately. The harness answers it like the other kinds.

**Raw text of a failed parse.** llama-server's error response does not contain the
model's output. Its log does: just before the error is thrown it writes the unparsed
part as a warning (`common/chat.cpp` L1496 at 31385c9) and, at debug verbosity, the
full output that triggered the error between `=== BEGIN ===` and `=== END ===` (L1497).
The server runs with `--log-file ~/ep22-lab/agents/server.log --log-verbosity 5`
(section 2). On every `server_parse` turn, `raw_text_from_log()` reads the newest
`BEGIN`/`END` block from that log and stores it as the turn's `raw_text` (one slot,
one request at a time, so the newest block is this turn's), with the warning line as
a cross-check; if no new block appeared, `raw_text` is `null` and the turn stays
`server_parse`. It is the exact text the model produced, not a reproduction, and it
costs no extra request. Re-sending the request with `"parse_tool_calls": false` does
not work on this build: with `tools` in the request, `tools/server/server-common.cpp`
L1352 sets `parse_tool_calls` to true before the request body is copied in, and the
copy (L1443-L1448) keeps keys that are already set. Count the turns that got a
`raw_text` as `harness.raw_text_recovered`. `examples.malformed` takes its NOT PARSED
excerpts from `raw_text` or `unparsed_text` content only. The log is not committed
(it holds every prompt); it is scanned like the runs file (section 6) only if an
excerpt is copied from it by hand.

**Server errors are classified before they count as model mistakes.** A `server_parse`
turn is only an HTTP error whose message is llama.cpp's tool-call parse failure ("The
model produced output that does not match the expected ... format", `common/chat.cpp`
at 31385c9). A context overflow (`exceed_context_size_error`, HTTP 400,
`tools/server/server-common.cpp`) ends the run as a failure with `context_overflow`
(see **Stuck** below), is never sent back as a malformed-call error and never counts
in `malformed_runs` or `stuck_runs`. Any other HTTP error discards the run (section 5).
Record each turn's error class as `error_type`.

For all five kinds, the harness sends the error back as text and the loop goes on
(`parser_reject` gets the same answer; record the exact wording as
`harness.malformed_error_text`, with the role it is sent in: `user` for
`server_parse`, `unparsed_text` and `parser_reject`, since a `tool` message needs a
`tool_call_id` a failed parse never produced; `tool` for `bad_json`, `missing_arg`
and `unknown_tool`, answered by `run_tool`; suggested wording:
`ERROR: that tool call could not be run: <reason>. Call a tool with valid JSON
arguments, or give your final answer.`). A malformed call still uses a turn.

**Stuck.** `config.max_turns = 12`. A run that reaches it without a plain reply is
`stuck`, scored as a failure. Also record `repeat_loop`: a run with the same tool
call (same name and arguments) three times in a row, stuck or not.
A run whose prompt passes the 16,384-token context is scored as a failure with
`context_overflow` (it is the ballooning-token failure, not a discard).

**Sandbox profile** (record its text as `harness.sandbox_profile`): deny all
network; deny file reads under `/Users` and `/Volumes` except the run folder (the
operator's home, other users and the external drive that holds the model; system
folders stay readable so `sh`, `grep`, `wc`, `python3` and `cal` work); allow writes
only under the run folder (plus `/dev/null`). The answer key lives in the harness
folder, which the profile hides. Before the full run, one manual check, recorded as
`harness.sandbox_check`: in a loop run, `cat ~/ep22-lab/agents/answers.json`,
`ls /Volumes/*`, `curl https://example.com` and `touch ~/escape-test` must each fail
with a sandbox denial, and `env` must print only the variables of `config.shell_env`.
The run folders live under the denied home folder, so the profile must list the
`allow file-read* file-write* (subpath <run folder>)` rule after the home-folder deny
(later rules win in sandbox-exec profiles). The manual `harness.sandbox_check` also
runs, inside the sandbox in a T08 run folder: `python3 -c 'print(6*7)'`, `cal 3 2019`
and `python3 -m unittest -q`; each must succeed (`/usr/bin/python3` is the Command
Line Tools shim; if it cannot run under the profile, every T08 loop run and every
shell-maths run would fail for a harness reason). Record every command of the check
and its exit code.

## 5. Scoring

The final answer is the text after the last `ANSWER:`; with no `ANSWER:` line, the
whole last reply. Checks per task are in section 3; numbers ignore commas, spaces
and a trailing full stop.

- **T08 (code).** Scoring never trusts the run folder's test file and never runs
  model-written code outside the sandbox. For each candidate `mathutil.py`, the
  harness builds a fresh scoring folder from the builder: the **pristine**
  `test_mathutil.py` (sha256 checked against `tasks.T08.folder_files`) plus the
  candidate `mathutil.py`, and runs `python3 -m unittest -q` there under the same
  `sandbox-exec` profile (scoped to the scoring folder), the same scrubbed
  environment and a 10 s timeout. Bare: the candidate is the reply's code block.
  Loop: success if the reply's code block passes the same way as in bare mode (the
  prompt asks for it in both modes). Also record `fixed_in_folder` (the
  `mathutil.py` the model left in its run folder passes against the pristine test;
  only that file is copied, and any edit to the run folder's test file is ignored and
  counted as `code_test_file_changed`) and report
  `modes.loop.code_fixed_in_folder_only` (folder fixed, reply block missing or
  failing); those runs are not counted as success. Record `fixed_in_reply` per run.
- **Bare lookups.** Classify each bare reply on T01 to T04 as `declined` (says it
  cannot see or open the file, no specific value) or `made_up` (gives a specific
  value anyway), by regex
  `(can't|cannot|unable to|don't have access|do not have access|no access)` plus a
  manual check of every `made_up` case; record the counts.
- **Compute without a tool.** A loop run on T05 to T07 with zero tool calls of any
  kind is `no_tool` (it did the maths in its head with the calculator one request
  away). Shell arithmetic (`python3 -c`, `cal`) counts as a tool. A `no_tool` run
  scored as a failure also counts in `modes.loop.compute_no_tool_failed`.
- **Discarded** (not scored, kept in the runs file with the reason): llama-server
  down, or an HTTP error that is neither a tool-call parse error (`server_parse`:
  llama.cpp's message "The model produced output that does not match the expected
  ... format", `common/chat.cpp` at 31385c9) nor a context overflow
  (`exceed_context_size_error`, HTTP 400, `tools/server/server-common.cpp`; scored as
  a failure with `context_overflow`, section 4), or a harness crash.

**Tokens and time, per turn** from each response: `usage.prompt_tokens`,
`usage.completion_tokens`, `timings.cache_n` (prompt tokens reused from the cache),
`timings.prompt_n` (prompt tokens processed this turn), and wall seconds. Per run:
`tokens_in` = sum of `prompt_tokens` over turns (the whole conversation, re-sent each
turn), `tokens_out` = sum of `completion_tokens`, `tokens_total` = both, `turns`,
`seconds`, and `tokens_processed` = sum of `timings.prompt_n` plus `completion_tokens`
over turns (what the server actually computed; `usage.prompt_tokens` includes cached
tokens). `tokens_total` is "tokens sent", what a paid API would bill; it is the spoken
multiple; the processed multiple goes in the description and pinned comment.

## 6. Capture file: `agent-loop-capture.json` (schema `ep22-agent-loop-capture-1`)

```text
schema_version            "ep22-agent-loop-capture-1"
captured_at_utc           ISO time the capture was written
machine                   {chip, ram_bytes, platform}
llama_cpp                 {command, output}
model                     {file_name, path, sha256, size_bytes}
server                    {command, ctx_size, chat_format, kv_mib}
harness                   {path, sha256, git_commit (once committed), loop_lines, loop_source,
                           malformed_error_text, sandbox_profile, sandbox_profile_sha256, sandbox_check,
                           raw_text_recovered}
tasks_build               {path, sha256}
config                    {system_prompt, tools, max_turns, max_tokens_per_turn, sampling, seeds,
                           runs_per_task, command_timeout_s, output_truncate_chars, shell_env,
                           calculator_limits, run_order, harness_deviation}
tasks.<T01..T10>          {category, prompt, answer, check, folder_files}
modes.bare                {n_runs, success, rate,
                           by_category: {lookup|compute|code|control: {n, success, tokens_total_mean}},
                           by_task: {<id>: {n, success}}, lookup_declined, lookup_made_up,
                           tokens_in_mean, tokens_out_mean, tokens_total_mean, tokens_processed_mean,
                           seconds_mean}
modes.loop                {n_runs, success, rate, by_category (same shape as bare), by_task, tokens_in_mean,
                           tokens_out_mean, tokens_total_mean, tokens_processed_mean, seconds_mean,
                           turns_median, turns_max,
                           prompt_tokens_first_median, prompt_tokens_last_median,
                           prompt_tokens_by_turn (median prompt_tokens at each turn index),
                           cache_n_last_median, tool_calls, malformed_calls,
                           malformed_by_kind: {server_parse, bad_json, missing_arg, unknown_tool, unparsed_text,
                                               parser_reject},
                           malformed_runs (parser_reject-only runs excluded), malformed_runs_succeeded,
                           stuck_runs, stuck_repeat_runs, repeat_loop_runs, context_overflow_runs,
                           compute_no_tool_runs, compute_no_tool_failed, code_fixed_in_folder,
                           code_fixed_in_reply, code_fixed_in_folder_only, code_test_file_changed,
                           lookup_saw_answer_failed}
comparisons               {token_multiple, seconds_multiple, processed_multiple,
                           token_multiple_by_category: {lookup, compute, code, control}}
totals                    {runs_planned, runs_usable, runs_discarded, discard_reasons, wall_seconds,
                           started_at_utc, finished_at_utc}
examples                  {cold_open: {task, run_seed, bare_excerpt, loop_excerpt, qualifying_pairs},
                           malformed: [{task, run_seed, kind, excerpt}], stuck: {task, run_seed, excerpt},
                           compute_no_tool: {task, run_seed, excerpt}, bare_made_up: {task, run_seed, excerpt},
                           lookup_saw_answer_failed: {task, run_seed, excerpt},
                           code_fixed_in_folder_only: {task, run_seed, excerpt}}
runs_file                 {path: "agent-loop-runs.jsonl", sha256, lines, redactions}
```

`rate` is `success / n_runs` (4 decimals). `comparisons.token_multiple` is
`modes.loop.tokens_total_mean / modes.bare.tokens_total_mean` (2 decimals);
`comparisons.seconds_multiple` the same for `seconds_mean`;
`comparisons.processed_multiple` the same for `tokens_processed_mean`;
`comparisons.token_multiple_by_category.<cat>` the same for
`modes.*.by_category.<cat>.tokens_total_mean`. `stuck_repeat_runs` counts stuck runs
that are also `repeat_loop`; `compute_no_tool_failed` counts `no_tool` compute runs
scored as failures; `lookup_saw_answer_failed` counts failed loop runs on T01 to T04
where some tool call's `result_head` contains the task's answer string (the answer was
on its screen and it still got it wrong). `examples.lookup_saw_answer_failed` and
`examples.code_fixed_in_folder_only` take the lowest-seed such run, or `null` when
there is none; the brief's Outcome assumptions use them only in the alternative
wording of seg_06 and seg_07.
`modes.loop.prompt_tokens_first_median` is the median `prompt_tokens` of turn 0 over
all loop runs; `prompt_tokens_last_median` the median `prompt_tokens` of each loop
run's final turn. `examples.cold_open` is the T02 run pair with the lowest run seed
where the bare reply declined or guessed and the loop run opened the notes and
answered correctly; record `examples.cold_open.qualifying_pairs` (how many of the T02
pairs qualify) and show it on screen as a chip (for example 8 OF 10 PAIRS); if no
such pair exists, write `null` (see the brief's Outcome assumptions,
`cold_open_example`). `examples.stuck` is a stuck run with `repeat_loop` true when
one exists.

Per-run lines in `agent-loop-runs.jsonl`: `{mode, task, run_seed, success, outcome,
answer_text, turns: [{prompt_tokens, completion_tokens, cache_n, prompt_n, seconds,
tool_calls: [{name, arguments_raw, result_head}], malformed, error_type,
raw_text}], tokens_in, tokens_out,
seconds, tokens_processed, stuck, repeat_loop, context_overflow, bare_class (bare
lookups), no_tool (loop compute), fixed_in_folder, fixed_in_reply (T08),
transcript_sha256}`. If the file passes 20 MB, gzip it and
record the `.jsonl.gz` path and sha256 instead.

Commit the capture, the runs file, the shared harness (built once, committed with
the captures), the sandbox profile and the task builder under
`episodes/5b1a7130a442/evidence/` (code in
`episodes/5b1a7130a442/evidence/harness/`). **Before committing**, scan the capture
and the runs file (it holds raw tool output) with the repo's firewall gate and stop on
any hit: `"$AUTOPILOT_PYTHON" -c "import sys; from pipeline import firewall;
hits=[(p, firewall.hard_gate(open(p).read())) for p in sys.argv[1:]];
print(hits); sys.exit(any(h for _, h in hits))" agent-loop-capture.json
agent-loop-runs.jsonl`. Also grep both for the operator's username, `/Users/`,
`/Volumes/`, `token`, `key=` and `BEGIN ` (private-key headers); any hit is
redacted by hand (the redaction recorded in `runs_file.redactions`) or the run is
held, never committed as is.

## 7. Runtime estimate

From the series 1 Part 4 capture on this Mac and build
(`episodes/ad65fb76a5bb/evidence/ais-lab2-memory-speed-capture.json`): Q4_K_M
decodes at 45.41 tokens/s (`speed.rows[9]`) and prefills at 364.41 tokens/s
(`speed.rows[8]`).

| part | runs | assumed per run | estimate |
|---|---|---|---|
| bare | 100 | 150-600 prompt tokens (about 1 s) plus 50-300 output tokens (1-7 s) | 5-15 min |
| loop | 100 | 2-12 turns; each turn 100-1,500 new prompt tokens (0.3-4 s) and 40-150 output tokens (1-3.5 s) | 15-150 min |
| total | 200 | | about 0.5-3 h; plan for one afternoon |

The token counts are planning guesses, not measurements; `totals.wall_seconds` is
the real figure.

## 8. Operator steps and risks

Operator steps (no `sudo` anywhere):

1. Plug the Mac into power and run the whole job under `caffeinate -dims`.
2. Check section 1 (build string, model sha256) and start the server (section 2).
3. Build the task folders, run the sandbox check (section 4), then run both modes,
   interleaved by task and seed (T01 bare seed 0, T01 loop seed 0, T02 bare seed 0,
   …), so a stop part-way leaves both modes with the same tasks and seeds
   (`config.run_order`). The runs file is written as it goes; a restart resumes
   after the last completed pair.
4. Count `harness.loop_lines`, write the capture (section 6), copy it, the runs file
   and the shared harness into `episodes/5b1a7130a442/evidence/`, and open the follow-up
   card to resolve the placeholders (section 9).
5. For the cold open, show the T02 pair picked by the rule in section 6 exactly as
   it was logged: screen-record the run live (start recording before step 3), or
   replay the captured excerpts (`examples.cold_open.bare_excerpt`, `loop_excerpt`)
   in a TerminalInset. Never re-run the pair on camera: with the prompt cache on, a
   re-run need not reproduce the logged pair (Risks, Non-determinism), and the
   on-screen PAIRS count would then describe a run the viewer is not shown. The same
   rule applies to the malformed and stuck runs shown in seg_10 and seg_11.

Risks:

- **Sandbox leaks the answer key.** The profile must hide the harness folder; the
  manual check in section 4 is required before the full run.
- **Tool-call format.** Qwen3 through `--jinja` writes tool calls in its template's
  format; the server's parser decides what counts as a call. Record
  `server.chat_format` and keep every raw failing text in the runs file. If the
  parser rejects nearly every call (a template problem, not model behaviour), stop
  and report rather than run 100 broken loops.
- **Harness deviation from the vendor's tool path.** Qwen's model card recommends
  Qwen-Agent, whose own templates and parsers handle tool calls; this run uses
  llama.cpp's parser through `--jinja`. Record it as `config.harness_deviation`; a
  well-formed call the parser misses is `parser_reject`, not a model mistake.
- **Debug log size.** `--log-verbosity 5` logs every request; the log lives on the
  Mac's internal disk, is never committed and is deleted once the capture is written.
  Check its size after the first ten pairs; if it would outgrow the free space, stop
  between two pairs, move the log aside and resume (the newest-block rule still holds,
  section 4).
- **The empty `<think>` block.** With thinking off, Qwen3's template may still emit an
  empty think block; `--reasoning-format deepseek` strips it from `content`. Check one
  bare reply by hand before the full run.
- **Non-determinism.** llama-server's prompt cache (default on) can change logits
  between batch sizes (README, `cache_prompt`), so a seed does not promise a
  bit-identical rerun; seeds pair the modes, they are not a reproducibility promise.
- **Small N.** Ten runs per task is enough to show a large gap, not a small one; the
  narration speaks counts ("x out of forty"), and the limits segment says so.
- **Same model as series 1.** If the model sha256 differs from the series 1 file,
  stop: the narration says it is the model from the last series.

## 9. Placeholder labels → capture keys

Spoken values are written out for the voice; exact figures go on screen.

| label | capture key(s) | spoken form |
|---|---|---|
| `loop_lines` | `harness.loop_lines` | the number, e.g. "thirty-one" |
| `runs_per_task` | `config.runs_per_task`, `modes.*.by_task.*.n` | "ten", or "about ten" if any task lost runs to discards |
| `success_bare` | `modes.bare.success`, `modes.bare.n_runs` | "{success} out of {n_runs}" |
| `success_loop` | `modes.loop.success`, `modes.loop.n_runs` | same form |
| `lookup_bare` | `modes.bare.by_category.lookup.success`, `.n` | "{success} out of {n}" |
| `lookup_loop` | `modes.loop.by_category.lookup.success`, `.n` | same form |
| `bare_made_up` | `modes.bare.lookup_made_up`, `modes.bare.by_category.lookup.n` | "{made_up} of them" |
| `compute_bare` | `modes.bare.by_category.compute.success`, `.n` | "{success} out of {n}" |
| `compute_loop` | `modes.loop.by_category.compute.success`, `.n` | same form |
| `calc_skipped` | `modes.loop.compute_no_tool_runs`, `modes.loop.by_category.compute.n` | "{no_tool} of the {n}" (e.g. "five of the thirty") |
| `calc_skipped_wrong` | `modes.loop.compute_no_tool_failed` | the number spelled (e.g. "three"); never "none": at zero the brief replaces the sentence |
| `code_bare` | `modes.bare.by_category.code.success`, `.n` | "{success} out of {n}" |
| `code_loop` | `modes.loop.by_category.code.success`, `.n` | same form |
| `control_bare` | `modes.bare.by_category.control.success`, `.n` | same form |
| `control_loop` | `modes.loop.by_category.control.success`, `.n` | same form |
| `token_multiple_control` | `comparisons.token_multiple_by_category.control` | "about {x} times", one decimal or a whole number |
| `turns_median` | `modes.loop.turns_median` | the median as a whole number; if it ends in .5, "three or four" style (both neighbours) |
| `prompt_tokens_first` | `modes.loop.prompt_tokens_first_median` | "about {n} tokens", rounded to the nearest hundred |
| `prompt_tokens_last` | `modes.loop.prompt_tokens_last_median` | "about {n} tokens", rounded to the nearest hundred |
| `token_multiple` | `comparisons.token_multiple` (tokens sent; `comparisons.processed_multiple` in the description) | "about {x} times", one decimal or a whole number |
| `seconds_bare` | `modes.bare.seconds_mean` | "about {s} seconds" |
| `seconds_loop` | `modes.loop.seconds_mean` | "about {s} seconds" |
| `malformed_rate` | `modes.loop.malformed_runs`, `modes.loop.n_runs` | "{malformed_runs} out of {n_runs}" |
| `stuck_rate` | `modes.loop.stuck_runs`, `modes.loop.n_runs` | "{stuck_runs} out of {n_runs}" |

The cold open's example pair (`examples.cold_open`) is not a label: the hook is fixed
across outcomes and only needs one qualifying T02 pair to exist (brief, Outcome
assumptions, `cold_open_example`, which names the fallback if none does); its
`qualifying_pairs` goes on screen.

Resolution: `pipeline.models.resolve_placeholder_results(contract, {label: spoken
value, ...})` re-validates the contract; recompute each segment's `est_seconds` with
`pipeline.script.estimate_seconds` and `total_est_seconds` (resolution substitutes
text only, and a resolved phrase is two to five words where the token counted as
one, so the narration grows by about seventy words, to 1,777 words and 12.6 minutes at the pipeline rate with the brief's assumed outcomes; the brief's TARGET LENGTH says what to cut if it passes 13 minutes); then replace each `PENDING:`
pointer in `claims.md` with the real `agent-loop-capture.json#/...` path, rerun the
technical-accuracy lane and the offline validators, and re-check the brief's Outcome
assumptions table for any sentence whose meaning changes. Write counts with
`one hundred` rather than `a hundred` where a sentence's only number is the count:
the concreteness floor counts `one hundred`, not `a hundred`.
