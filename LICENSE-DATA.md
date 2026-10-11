# Data licence: Creative Commons Attribution 4.0 International (CC BY 4.0)

Copyright (c) 2026 THE SIDEQUEST.

All measured data and documents in this repository (the `.json`, `.jsonl`, `.csv.gz`, `.log`, `.txt`, `.text`, `.md` files that are
not code) are licensed under CC BY 4.0. You may share and adapt them for any purpose, including commercially,
if you give appropriate credit, link to the licence and say if you made changes.

- Licence deed: https://creativecommons.org/licenses/by/4.0/
- Legal code (the full text): https://creativecommons.org/licenses/by/4.0/legalcode

Suggested credit: "What AI Actually Does, capture files (CC BY 4.0)", with a link to this repository.

## What the licence does not cover

- Text written by Qwen3-8B inside the run files is model output; it is included as a record of the experiment.
- `e4-memory/data/chat_template.jinja` is the chat template shipped with the Qwen3 model (Apache License 2.0, Qwen team).
- Text of other people's works that appears as test input stays under its own terms: Project Gutenberg #1661 (public domain) is only
  referenced by hash in `e4-memory`; the Shakespeare passage in `e6-bill/data/longctx-doc.json` is public domain.
- The prompts of the shutdown test in `e2-shutdown` replicate the prompts published by Palisade Research (arXiv 2509.14260); see that paper for their terms.
- Anthropic's price page and Apple's `powermetrics` manual page, which the episode 6 arithmetic read, are not redistributed here. Links are in `e6-bill/README.md`.
