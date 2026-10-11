"""First pass of the E3 builder: PR numbers named in `Merged:` or `Pull request opened by the GitHub sync:` events of in-window cards.
In-window = at least one `Dispatched to` event with createdAt in [2026-09-08T00:00:00Z, 2026-10-06T00:00:00Z). usage: list_prs.py raw/board > raw/pr-numbers.txt"""
import glob, json, re, sys
WS, WE = "2026-09-08T00:00:00", "2026-10-06T00:00:00"
nums, repos, n_in = set(), set(), 0
for f in sorted(glob.glob(sys.argv[1] + "/task-*.json")):
    d = json.load(open(f)); cms = d.get("comments", [])
    ds = [c for c in cms if (c.get("body") or "").startswith("Dispatched to") or re.match(r"Status changed to In Progress . dispatched to", c.get("body") or "")]
    if not any(WS <= (c["createdAt"] or "")[:19] < WE for c in ds): continue
    n_in += 1
    for c in cms:
        b = c.get("body") or ""
        if b.startswith("Merged:") or b.startswith("Pull request opened by the GitHub sync:"):
            for m in re.finditer(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", b): nums.add(int(m.group(2))); repos.add(m.group(1))
for n in sorted(nums): print(n)
print(f"in-window cards {n_in}, PRs {len(nums)}, repos {sorted(repos)}", file=sys.stderr)
