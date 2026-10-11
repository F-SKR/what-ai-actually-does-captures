#!/usr/bin/env python3
"""EP22-E4 memory experiment. Subcommands: preflight | needle | prefill | compaction | lora | capture. Resumable (memory-trials.jsonl)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "needle":
        import needle
        with Server(tag="needle"): needle.run_needle()
    elif cmd == "preflight":
        import preflight; preflight.run()
    elif cmd == "prefill":
        import prefill; prefill.run()
    elif cmd == "compaction":
        import compaction; compaction.run()
    elif cmd == "lora":
        import lora_run; lora_run.run()
    elif cmd == "capture":
        import capture; capture.run()
