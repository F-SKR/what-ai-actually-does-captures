# Redactions

The files here are the files the experiments produced. The only edits are to path and name strings, never to numbers, counts, texts a model wrote, or timestamps:

- `/Users/<account>` is written `~` and the name of the external drive that held the model file is written `<T7>`.
- One worker-preset name inside `e3-coding/data/coding-demo-capture.json` is written `<worker-preset>`.
- `e3-coding/harness/coding-demo/run_demo.py` has one edit: the call that read the stronger worker's configuration from the private factory's board is replaced by a fixed configuration (worker tier recorded as `senior tier`). The capture's `harness.sha256` hashes the original file.
- `e6-bill/data/tier-ledger.csv`: the worker and reviewer preset names are mapped to tier names (table in `e6-bill/README.md`); the two columns are renamed `worker_tier_name` and `review_tier_name`; no other cell is changed.
- In the Markdown documents (`claims.md` and `experiment-plan.md` of the other episodes, `REPORT.md`) card numbers (`<card>`), worker-preset names (`<worker-preset>`), the name of one CI workflow (`<ci-workflow>`) and the name of a board command-line tool (`<board-cli>`) are replaced by placeholders.

Hashes written inside a capture (`transcript_sha256`, `sha256` fields and similar) were computed by the harness over the text as it was **before** these edits, so a hash of a redacted string will not match. Where a hash covers a file that is in this repository unedited, it matches.

| file | edits | sha256 of the file before the edit |
|---|---|---|
| `e1-agents/claims.md` | 2 | `633191a62ddf69e0cc0d10c6e251ed88735c01697669945c138f3a9bf3840b07` |
| `e1-agents/experiment-plan.md` | 3 | `96708d3a598ceeb6db5805e563ce01b0096451b9c299868926986dab83b6d758` |
| `e2-shutdown/claims.md` | 2 | `9ad8debe6aea7bcccd8ac77d2c36576c1241280a58b880d1d4d789d40d55f110` |
| `e2-shutdown/experiment-plan.md` | 2 | `3c7371841e83cad31a6b37cee45fe3be26a586cf56487e8c18fa65c4255a4525` |
| `e3-coding/data/coding-demo-capture.json` | 1 | `1945e1e7ff9380d55eb0ef80619b288d415e298ad8d01faede6f3d8adcade6d2` |
| `e3-coding/harness/coding-demo/run_demo.py` | 1 | `95093c7e1a32b6dac2d4450949d88f9d7a4f43afb8d7d8492724c1588a5954ca` |
| `e4-memory/claims.md` | 1 | `9b6ce48ff9a1f5f1d0c6b8ef7b8d538505d93d00a768edab4205f7a9a641b52a` |
| `e4-memory/experiment-plan.md` | 3 | `c3d3dfcba02769983c5f67d63435d7c41a61f58a8bb5f3de8e80bc85be3fe614` |
| `e5-thinking/claims.md` | 1 | `9121796a536fcc627545bd395eb213a5b7c666872edd35921b7c297052514621` |
| `e5-thinking/data/thinking-capture.json` | 42 | `455b9583ca2946f96c2f40f1b014f157993d7e6122bb3deb830c3044813895bc` |
| `e5-thinking/experiment-plan.md` | 6 | `795e8bebf4b98a79e3e664ac8a80982d285866634fb88a0330f515c618773653` |
| `e6-bill/claims.md` | 14 | `a3582b7807eb3e1e45169d9601af6879c25d56415073fee271305bffc95225e2` |
| `e6-bill/data/longctx-doc.json` | 1 | `c5f53b8802a08cd50a70ec04d87302e2d3331d103771fd5a76986ea2e9f9c17e` |
| `e6-bill/data/tier-ledger.csv` | 17 | `1221aae105c362f4291c400ce846a5578758fe727deb4e3434af0c1b68cee236` |
| `e6-bill/experiment-plan.md` | 10 | `bf40d1ef19b8866ea6f8ff34d987623e0c797aeac2ef708fe74fea8a04a21e2f` |
| `e6-bill/logs/bill-events.jsonl` | 3 | `300251f603dd93474ba6078fca4430a54791f75a310460373fe3f0c1a381041c` |
| `e6-bill/logs/server-a.log` | 1 | `ca8c5e1dd6eb9097b5007a2278c88eedd9d04f3292769d9b979b86a4fc956ecb` |
| `e6-bill/logs/server-b.log` | 1 | `7e49f4daf737742db7d315e3056e7b24ec9258b658718b8388c486a7bd4e09d4` |
