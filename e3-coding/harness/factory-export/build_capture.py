#!/usr/bin/env python3
"""EP22-E3 part A builder (stdlib only). Plan: s2/grade_r4/E3/experiment-plan.md sections 3-6, 11.

  build_capture.py --list-prs raw/board            PR numbers of in-window cards (first pass)
  build_capture.py --build raw/ [--only YT-1,YT-2] events, attempts, causes, metrics -> capture + private files
  build_capture.py --audit raw/audit.csv --hand-fixes raw/hand_fixes.csv   fold the operator's labels in (then --build again is NOT needed: it rewrites the capture)

Private inputs (never committed): raw/board/*, raw/github/*, env HUMAN_AUTHORS, raw/deny_list.txt (one string per line),
raw/worker_model_changes.json, raw/builder_history.json, raw/cold_open_summary.txt, raw/known_failures.txt, raw/ci_logs/log-<runid>.txt.
Private outputs: raw/cards.json, raw/unmatched.txt, raw/audit.csv, raw/audit_key.csv, raw/hand_fixes.csv.
Public output: factory-export-capture.json (counts, shares, hours, categories only).
"""
import argparse, collections, csv, datetime as dt, glob, hashlib, json, os, random, re, statistics, sys

WS, WE = "2026-09-08T00:00:00", "2026-10-06T00:00:00"
DUP_SECONDS = 120

# ---------------------------------------------------------------- patterns (plan section 4)
MACHINE_PREFIXES = ("<!--", "⛔", "Sent back", "Not sent back", "Dispatched", "Climbed", "Auto-pushed", "Merged:", "Pull request opened",
                    "Work thread", 'Thread "', "Held for a person", "The scrum", "The mechanical gate", "Stale merge-base")
MACHINE_REVIEW_EXPIRED = re.compile(r"^Review \S+ expired")  # a bare "Review " prefix also matches worker notes ("Review round 1 addressed"), so only the expiry line is machine
EVENT_PATTERNS = [
    ("status", r"^Status changed to (?P<to>[A-Za-z ]+?)(?: by | ·|$)"),
    ("dispatch_window", r"^Dispatched by hackathon window #\d+ on preset (?P<preset>\S+) \(tier (?P<tier>\w+)\)"),
    ("dispatch", r"^Dispatched to (?P<preset>\S+)"),
    ("dispatch_refused", r"^⛔ Dispatch refused"),
    ("provision_failed", r"^Work thread \S+ could not be provisioned"),
    ("thread_failed", r'^(?:Thread "[^"]*"|Work thread \S+) failed'),
    ("criteria_proposed", r"^The scrum agent (?:is proposing|proposed) criteria"),
    ("priority", r"^Priority changed to"),
    ("not_sent_back", r"^Not sent back: (?!sent back \d+ time)"),
    ("run_notes", r"^<!-- run-notes -->"),
    ("criteria_draft_failed", r"^The scrum draft thread \S+ failed to provision"),
    ("climbed", r"^Climbed the ladder: (?P<from>\w+) → (?P<to>\w+)"),
    ("verdict_approve", r"review-plugin:verdict -->\s*Reviewed and approved"),
    ("stale_base", r"review-plugin:verdict -->\s*Stale merge-base|^Stale merge-base"),
    ("verdict_held", r"review-plugin:verdict -->\s*Held at"),
    ("review_expired", r"^(?:<!-- review-plugin:verdict -->\s*)?Review \S+ expired"),
    ("send_back", r"^Sent back to \S+ with the verdict \(round (?P<round>\d) of (?P<max>\d)\)"),
    ("rounds_spent", r"^Not sent back: sent back \d+ time\(s\) already"),
    ("held_for_person", r"^Held for a person"),
    ("mechanical_gate_skipped", r"^The mechanical gate did not run"),
    ("auto_pushed", r"^Auto-pushed by the board"),
    ("pr_opened", r"^Pull request opened by the GitHub sync: \S+/pull/(?P<pr>\d+)"),
    ("merged", r"^Merged: \S+/pull/(?P<pr>\d+) \(squash (?P<sha>[0-9a-f]+)\)"),
    ("mirror_conflict", r"^<!-- github-mirror:"),
]
EVENT_RX = [(n, re.compile(p)) for n, p in EVENT_PATTERNS]
LENS_RX = re.compile(r"\*\*(?P<lens>[a-z]+): (?P<out>[a-z\-]+)(?: \([^)]*\))?\*\*")
SHA_RX = re.compile(r"sha `([0-9a-f]{12})`")
FAIL_ENDINGS = {"dispatch_refused", "provision_failed", "thread_failed", "review_expired", "verdict_held", "stale_base", "blocked", "held_for_person", "re_dispatch", "ci_red"}
NO_VERDICT_ENDINGS = {"dispatch_refused", "provision_failed", "thread_failed", "review_expired", "re_dispatch", "blocked", "held_for_person"}

# ---------------------------------------------------------------- cause table (plan 5.3). Order = table order (ties, subcategory order)
CAUSE_ROWS = [  # (category, subcategory, [regexes], [event types])
    ("infrastructure", "dispatch_never_started", [r"could not be installed", r"never provisioned", r"could not be provisioned", r"failed to provision"], ["dispatch_refused", "provision_failed"]),
    ("infrastructure", "review_never_ran", [r"\bno verdict\b"], ["review_expired"]),
    ("infrastructure", "disk_full", [r"\bENOSPC\b", r"no space left", r"\bdisk full\b"], []),
    ("infrastructure", "stale_lock", [r"\bstale lock\b", r"\bindex\.lock\b", r"\bpacked-refs\.lock\b", r"\block file\b"], []),
    ("infrastructure", "quota_or_auth", [r"\bquota\b", r"\brate limit", r"\bHTTP (?:401|403|429)\b", r"\bauth(?:entication|orization)? (?:failed|error|expired)\b", r"\blogin (?:failed|expired|required)\b", r"\btoken expired\b"], []),
    ("infrastructure", "ci_not_completed", [], []),  # decided by the CI cause, see classify_ci
    ("infrastructure", "stale_base", [], ["stale_base"]),
    ("infrastructure", "host_or_runner", [r"\bhost state\b", r"\brunner (?:lost|offline|died)\b", r"\bOOM\b", r"\bworktree (?:missing|not found)\b"], ["thread_failed"]),
    ("spec", "criteria_wrong", [r"criteria (?:are|were|is) (?:wrong|impossible|contradict)", r"amend(?:ed)? the criteria", r"\bcard (?:is|was) wrong\b", r"\bspec (?:mismatch|does not match)\b"], []),
    ("spec", "spec_data_mismatch", [r"does not match the (?:data|capture)", r"\brule returns\b", r"\bthe capture says\b", r"\bselection rule\b"], []),
    ("model", "tests_failing", [r"\btests? fail", r"\bAssertionError\b", r"\bregression\b"], []),
]
CAUSE_RX = [(c, s, [re.compile(r, re.I) for r in rx], ev) for c, s, rx, ev in CAUSE_ROWS]
CAUSE_ORDER = [s for _, s, _, _ in CAUSE_ROWS] + ["standards_veto", "security_veto", "ask_not_done", "unknown"]
CAUSE_ORDER = ["dispatch_never_started", "review_never_ran", "disk_full", "stale_lock", "quota_or_auth", "ci_not_completed", "stale_base", "host_or_runner",
               "criteria_wrong", "spec_data_mismatch", "tests_failing", "standards_veto", "security_veto", "ask_not_done", "unknown"]
CATEGORY_OF = {"dispatch_never_started": "infrastructure", "review_never_ran": "infrastructure", "disk_full": "infrastructure", "stale_lock": "infrastructure",
               "quota_or_auth": "infrastructure", "ci_not_completed": "infrastructure", "stale_base": "infrastructure", "host_or_runner": "infrastructure",
               "criteria_wrong": "spec", "spec_data_mismatch": "spec", "tests_failing": "model", "standards_veto": "model", "security_veto": "model",
               "ask_not_done": "model", "unknown": "unknown"}
PHRASES = {"dispatch_never_started": "a worker that never got started", "review_never_ran": "a review that never came back", "disk_full": "a full disk",
           "stale_lock": "a stale lock file", "quota_or_auth": "a worker that ran out of quota or lost its login", "ci_not_completed": "a CI run that never finished",
           "stale_base": "a change that had to be rebased first", "host_or_runner": "a machine problem under the worker", "criteria_wrong": "a card that asked for the wrong thing",
           "spec_data_mismatch": "a spec that didn't match the data", "tests_failing": "code that failed its tests", "standards_veto": "code that broke the project's rules",
           "security_veto": "code the safety check refused", "ask_not_done": "a change that didn't do what the card asked"}
SPEC_RX = [rx for c, s, rxs, ev in CAUSE_RX if c == "spec" for rx in rxs]
CHECK_RX = re.compile(r"`[^`]*(?:\.py|pytest|python3? -m|::test_|/tests?/|scripts/|npm |node |git diff|bb criteria)[^`]*`")
CHECK_WORDS_RX = re.compile(r"exit 0|exit code|returns 0", re.I)
AI_TRAILER_RX = re.compile(r"co-authored-by:.*(claude|codex|gpt|glm|deepseek|noreply@anthropic\.com|noreply@openai\.com)", re.I)

SCRUB_RULES = [r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", r"https?://", r"\b(?:ghp|gho|ghs|github_pat|sk|xox[bp])[-_][A-Za-z0-9]{10,}", r"\b[0-9a-f]{12,40}\b",
               r"\bthr_[a-z0-9]{6,}\b", r"\benv_[a-z0-9]{6,}\b", r"\bhost_[a-z0-9]{6,}\b", r"/(?:opt|home|Users|workspace|data)/", r"\bYT-\d+\b", r"\bFAC-\d+\b", r"#\d{2,}"]


def parse_t(s):
    return dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


# ---------------------------------------------------------------- events
def classify_comment(c):
    body = (c.get("body") or "").lstrip(); first = body.split("\n", 1)[0]
    machine = c.get("kind") == "system" or any(first.startswith(p) for p in MACHINE_PREFIXES) or bool(MACHINE_REVIEW_EXPIRED.match(first))
    if not machine: return False, None, {}
    for name, rx in EVENT_RX:
        m = rx.search(body) if name in ("verdict_approve", "verdict_held", "stale_base") else rx.match(body)
        if m: return True, name, m.groupdict()
    return True, None, {}


def load_card(path):
    d = json.load(open(path)); t = d["task"]
    return {"key": t["key"], "number": t.get("number"), "comments": sorted(d.get("comments", []), key=lambda c: (c["createdAt"], c.get("id", ""))), "raw": d}


def card_events(card, unmatched):
    evs = []; free = 0
    for c in card["comments"]:
        ts = (c["createdAt"] or "")[:19]
        if not (WS <= ts < WE): continue
        machine, ty, g = classify_comment(c)
        if not machine: free += 1; continue
        if ty is None:
            unmatched.append((card["key"], ((c.get("body") or "").lstrip().split("\n", 1)[0])[:200])); evs.append({"t": parse_t(ts), "type": "unmatched", "g": {}, "body": c.get("body") or "", "id": c.get("id")}); continue
        body = c.get("body") or ""
        if ty == "status":
            to = g["to"].strip().lower()
            ty = "status_blocked" if to == "blocked" else "status_cancelled" if to in ("canceled", "cancelled") else "status"
        evs.append({"t": parse_t(ts), "type": ty, "g": g, "body": body, "id": c.get("id")})
    # merge duplicates: a dispatch_window within 120 s of a dispatch is the same dispatch; two refusals within 120 s count once
    out = []
    for e in evs:
        if e["type"] == "dispatch_window":
            near = [o for o in out if o["type"] == "dispatch" and abs((o["t"] - e["t"]).total_seconds()) <= DUP_SECONDS]
            if near: near[-1]["g"] = dict(near[-1]["g"], tier=e["g"].get("tier")); near[-1]["from_window"] = True; continue
            e = dict(e, type="dispatch", from_window=True, g=dict(e["g"]))
        elif e["type"] == "dispatch":
            near = [o for o in out if o["type"] == "dispatch" and abs((o["t"] - e["t"]).total_seconds()) <= DUP_SECONDS and o.get("from_window")]
            if near: continue  # the window comment came first; same dispatch
        if e["type"] == "dispatch_refused":
            if any(o["type"] == "dispatch_refused" and (e["t"] - o["t"]).total_seconds() <= DUP_SECONDS for o in out[-3:]): continue
        out.append(e)
    return out, free


def lenses(body):
    return [(m.group("lens"), m.group("out")) for m in LENS_RX.finditer(body)]


# ---------------------------------------------------------------- CI + attempts
def load_ci(gh_dir, pr):
    p = os.path.join(gh_dir, f"ci-{pr}.json")
    if not os.path.exists(p): return []
    runs = json.load(open(p)).get("workflow_runs", [])
    return sorted(runs, key=lambda r: r["created_at"])


def red_runs_for(ci, sha12):
    return [r for r in ci if sha12 and r["head_sha"].startswith(sha12) and r.get("conclusion") == "failure"]


def build_attempts(evs, prs, gh_dir, known_failures, ci_logs_dir):
    """Attempts per plan section 4. Returns (attempts, merged_event, post_merge_dispatches)."""
    attempts = []; cur = None; merged = None; post = 0
    ci = [r for pr in prs for r in load_ci(gh_dir, pr)]

    def new(e, kind):
        a = {"start": e["t"], "kind": kind, "end": None, "ending": None, "text": "", "sha": None, "tier": (e.get("g") or {}).get("tier") or e.get("tier_from_window"), "lens": [], "ci": None, "events": []}
        attempts.append(a); return a

    def end(a, ending, e):
        if a["ending"] is None: a["ending"] = ending; a["end"] = e["t"]; a["text"] = e.get("body") or ""; a["end_event"] = e["type"]

    for e in evs:
        ty = e["type"]
        if merged is not None:
            if ty == "dispatch": post += 1
            continue
        if ty == "merged": merged = e; continue
        if ty == "dispatch":
            if cur is not None and cur["ending"] is None: end(cur, "re_dispatch", dict(e, body=""))
            cur = new(e, "dispatch")
        elif ty in ("dispatch_refused", "provision_failed", "thread_failed"):
            if cur is None or cur["ending"] is not None: cur = new(e, ty)
            end(cur, ty, e)
        elif ty == "review_expired":
            if cur is None: cur = new(e, ty)
            end(cur, "review_expired", e)
        elif ty == "verdict_held":
            if cur is None: cur = new(e, "verdict")
            if cur["ending"] is None: end(cur, "verdict_held", e)
            cur["lens"] = lenses(e["body"]); m = SHA_RX.search(e["body"]); cur["sha"] = m.group(1) if m else None
        elif ty == "verdict_approve":
            if cur is None: cur = new(e, "verdict")
            if cur["ending"] is None: end(cur, "verdict_approve", e)
            cur["lens"] = lenses(e["body"]); m = SHA_RX.search(e["body"]); cur["sha"] = m.group(1) if m else None; cur["approve_t"] = e["t"]
        elif ty == "stale_base":
            if cur is None or cur["ending"] is not None: pass
            else: end(cur, "stale_base", e)
            if cur is None or cur["ending"] != "stale_base": cur = new(e, "stale_base_orphan"); end(cur, "stale_base", e)
            cur = new(e, "stale_base_restart")
        elif ty == "send_back":
            if cur is not None and cur["ending"] is None: end(cur, "verdict_held", e)
            cur = new(e, "send_back")
        elif ty == "status_blocked":
            if cur is not None and cur["ending"] is None: end(cur, "blocked", e)
        elif ty == "held_for_person":
            if cur is not None and cur["ending"] is None: end(cur, "held_for_person", e)
    # red CI on approved heads
    for a in attempts:
        if a["ending"] == "verdict_approve":
            reds = red_runs_for(ci, a["sha"]) if a["sha"] else []
            if reds:
                r = reds[0]; a["ci"] = {"conclusion": "failure", "run": r["id"], "finished": r["updated_at"], "after_verdict": parse_t(r["updated_at"]) > a.get("approve_t", a["end"])}
                a["ending"] = "ci_red"; a["text"] = ci_text(r, known_failures, ci_logs_dir)
            nc = [r for r in ci if a["sha"] and r["head_sha"].startswith(a["sha"]) and r.get("conclusion") in ("cancelled", "timed_out", "startup_failure")]
            if nc and a["ending"] == "verdict_approve": a["ci_not_completed"] = nc[0]["conclusion"]
    return attempts, merged, post


def ci_text(run, known_failures, logs_dir):
    p = os.path.join(logs_dir, f"log-{run['id']}.txt")
    txt = open(p, errors="replace").read()[:20000] if os.path.exists(p) else ""
    return f"CI run failure on the approved head. {txt}"


# ---------------------------------------------------------------- cause classifier (plan 5.3)
def classify(a, known_failures):
    ending = a["ending"]; text = a["text"] or ""
    if ending in ("verdict_held",):
        ls = [(l, o) for l, o in a["lens"] if o == "veto"]
        if not ls: return "unknown", "unknown", True  # no vetoing lens line: unknown, goes to the operator (plan 5.3)
        spec_hit = any(rx.search(text) for rx in SPEC_RX)
        sub = "security_veto" if any(l == "security" for l, _ in ls) else "standards_veto" if any(l == "standards" for l, _ in ls) else "ask_not_done"
        if any(l in ("correctness", "spec") for l, _ in ls): sub = "ask_not_done" if sub != "security_veto" else sub
        return "model", sub, spec_hit
    if ending == "ci_red":
        failing = re.findall(r"[\w/.\-]+\.py::[\w:\[\]\-]+", text)
        if failing and all(f in known_failures for f in failing): return "infrastructure", "ci_not_completed", False
        return "model", "tests_failing", False
    if ending == "ci_not_completed": return "infrastructure", "ci_not_completed", False
    hits = collections.OrderedDict()
    for cat, sub, rxs, evs in CAUSE_RX:
        if ending in evs or a.get("end_event") in evs or any(rx.search(text) for rx in rxs): hits.setdefault(cat, []).append(sub)
    if ending == "stale_base": hits = collections.OrderedDict(infrastructure=["stale_base"])
    if len(hits) == 1:
        cat, subs = next(iter(hits.items())); first = min(subs, key=CAUSE_ORDER.index); return cat, first, False
    if len(hits) > 1:
        first = min((s for ss in hits.values() for s in ss), key=CAUSE_ORDER.index); return CATEGORY_OF[first], first, True
    return "unknown", "unknown", False


def failure_runs(attempts, labels):
    runs = []
    for i, a in enumerate(attempts):
        if a["ending"] not in FAIL_ENDINGS: continue
        cat, sub, mixed = a["cause"]
        if runs and runs[-1]["sub"] == sub and runs[-1]["last_idx"] == i - 1 and attempts[i - 1]["ending"] in NO_VERDICT_ENDINGS:
            runs[-1]["last_idx"] = i; runs[-1]["n_attempts"] += 1; continue
        runs.append({"first_idx": i, "last_idx": i, "n_attempts": 1, "cat": cat, "sub": sub, "mixed": mixed, "end": a["end"]})
    return runs


# ---------------------------------------------------------------- criteria (plan 5.7)
def criteria_of(path):
    if not os.path.exists(path): return None
    lines = [l for l in open(path).read().splitlines() if l.strip()]
    body = "\n".join(lines[1:]).strip() if lines else ""
    if len(body) < 20 or re.search(r"no (?:approved )?criteria", body, re.I): return None
    return body


# ---------------------------------------------------------------- main build
def hours(a, b): return (b - a).total_seconds() / 3600


def build(raw, only, builder_path):
    board, gh = os.path.join(raw, "board"), os.path.join(raw, "github"); logs = os.path.join(raw, "ci_logs")
    known = set(open(os.path.join(raw, "known_failures.txt")).read().split()) if os.path.exists(os.path.join(raw, "known_failures.txt")) else set()
    human = [h.strip().lower() for h in os.environ.get("HUMAN_AUTHORS", "").split(",") if h.strip()]
    deny = [l.strip() for l in open(os.path.join(raw, "deny_list.txt")).read().splitlines() if l.strip()] if os.path.exists(os.path.join(raw, "deny_list.txt")) else []
    unmatched = []; cards = []; machine_total = 0; free_total = 0; by_type = collections.Counter()
    for f in sorted(glob.glob(os.path.join(board, "task-*.json"))):
        card = load_card(f)
        if only and card["key"] not in only: continue
        evs, free = card_events(card, unmatched); free_total += free
        if not any(e["type"] == "dispatch" for e in evs): continue
        machine_total += len(evs); by_type.update(e["type"] for e in evs)
        prs = sorted({int(e["g"]["pr"]) for e in evs if e["type"] in ("pr_opened", "merged") and e["g"].get("pr")})
        attempts, merged, post = build_attempts(evs, prs, gh, known, logs)
        for a in attempts: a["cause"] = classify(a, known) if a["ending"] in FAIL_ENDINGS else None
        first_d = next(e for e in evs if e["type"] == "dispatch")
        cards.append({"key": card["key"], "evs": evs, "prs": prs, "attempts": attempts, "merged": merged, "post_merge": post, "first_dispatch": first_d["t"], "free": free})
    cards.sort(key=lambda c: c["first_dispatch"])
    for i, c in enumerate(cards): c["id"] = f"card-{i + 1:03d}"
    if only:
        for c in cards:
            print("=====", c["id"], c["key"], "prs", c["prs"])
            for e in c["evs"]: print("  ", e["t"].isoformat(), e["type"], json.dumps({k: v for k, v in e["g"].items()}), "|", (e["body"] or "").lstrip().split("\n", 1)[0][:90])
            for j, a in enumerate(c["attempts"]): print("  attempt", j + 1, a["kind"], "->", a["ending"], a["cause"], a["sha"], [f"{l}:{o}" for l, o in a["lens"]])
        print("unmatched machine comments:", len(unmatched)); return None

    # ---- per-card derived data
    ci_all = {"prs": 0, "runs": 0, "red": 0, "not_completed": 0, "first_head_green": 0}
    for c in cards:
        runs = [r for pr in c["prs"] for r in load_ci(gh, pr)]
        c["ci_runs"] = runs
        for pr in c["prs"]:
            rs = load_ci(gh, pr)
            if not rs: continue
            ci_all["prs"] += 1; ci_all["runs"] += len(rs); ci_all["red"] += sum(r.get("conclusion") == "failure" for r in rs)
            ci_all["not_completed"] += sum(r.get("conclusion") in ("cancelled", "timed_out", "startup_failure") for r in rs)
            ci_all["first_head_green"] += rs[0].get("conclusion") == "success"
        c["failure_runs"] = failure_runs(c["attempts"], None)
        c["n_failed_attempts"] = sum(a["ending"] in FAIL_ENDINGS for a in c["attempts"])
        verdicts = [e for e in c["evs"] if e["type"] in ("verdict_approve", "verdict_held")]
        c["first_verdict"] = verdicts[0] if verdicts else None
        c["has_verdict"] = bool(verdicts)

        def first_pass(excl_stale=False, excl_never=False):
            fv = c["first_verdict"]
            if fv is None or fv["type"] != "verdict_approve": return False
            bad = {"dispatch_refused", "provision_failed", "thread_failed", "review_expired", "stale_base", "status_blocked", "held_for_person"}
            if excl_stale: bad.discard("stale_base")
            if excl_never: bad -= {"dispatch_refused", "provision_failed"}
            before = [e for e in c["evs"] if e["t"] <= fv["t"] and e is not fv]
            if any(e["type"] in bad for e in before): return False
            disp = [e for e in before if e["type"] == "dispatch"]
            if excl_never:
                started = []
                for k, d in enumerate(disp):
                    nxt = disp[k + 1]["t"] if k + 1 < len(disp) else fv["t"]
                    if not any(e["type"] in ("dispatch_refused", "provision_failed") and d["t"] <= e["t"] < nxt for e in before): started.append(d)
                if len(started) > 1: return False
            elif len(disp) > 1: return False
            m = SHA_RX.search(fv["body"]); sha = m.group(1) if m else None
            if sha and red_runs_for(c["ci_runs"], sha): return False
            return True
        c["first_pass"] = first_pass(); c["first_pass_excl_stale"] = first_pass(excl_stale=True); c["first_pass_excl_never"] = first_pass(excl_never=True)
        fv = c["first_verdict"]; c["ci_after_verdict"] = False
        if fv is not None and fv["type"] == "verdict_approve":
            m = SHA_RX.search(fv["body"]); sha = m.group(1) if m else None
            rr = red_runs_for(c["ci_runs"], sha) if sha else []
            c["ci_after_verdict"] = bool(rr) and parse_t(rr[0]["updated_at"]) > fv["t"]
        c["escalated"] = any(e["type"] == "climbed" for e in c["evs"])
        if c["merged"] is not None:
            c["attempts_to_merge"] = len(c["attempts"]); c["hours_to_merge"] = hours(c["first_dispatch"], c["merged"]["t"])
        crit = criteria_of(os.path.join(board, f"criteria-{c['key']}.txt")); c["criteria"] = crit
        c["has_check"] = bool(crit and (CHECK_RX.search(crit) or CHECK_WORDS_RX.search(crit)))
        files = []
        for pr in c["prs"]:
            p = os.path.join(gh, f"pr-{pr}.json")
            if os.path.exists(p): files += json.load(open(p)).get("files", [])
        tot = sum(f.get("additions", 0) + f.get("deletions", 0) for f in files) or 1
        codep = ("pipeline/", "scripts/", "idea_engine/")
        code = sum(f.get("additions", 0) + f.get("deletions", 0) for f in files if f["path"].startswith(codep) or "/tests/" in f["path"] or f["path"].startswith("tests/"))
        c["is_code"] = code * 2 > tot; c["diff"] = {"files": len(files), "added": sum(f.get("additions", 0) for f in files), "removed": sum(f.get("deletions", 0) for f in files)}

    # ---- hand fixes (plan 5.2)
    hand_rows = []
    for c in cards:
        c["hand_fixed_auto"] = False
        if c["merged"] is None: continue
        for pr in c["prs"]:
            p = os.path.join(gh, f"pr-{pr}.json")
            if not os.path.exists(p): continue
            for cm in json.load(open(p)).get("commits", []):
                ids = {x.get(k, "").lower() for x in cm.get("authors", []) for k in ("email", "login")}
                msg = (cm.get("messageHeadline") or "") + "\n" + (cm.get("messageBody") or "")
                trailers = [l for l in msg.splitlines() if l.lower().startswith("co-authored-by:")]
                if msg.lstrip().startswith("SM: sync") or AI_TRAILER_RX.search(msg) or any(d.lower() in l.lower() for l in trailers for d in deny): continue
                if human and ids & set(human):
                    c["hand_fixed_auto"] = True; hand_rows.append([c["id"], pr, cm.get("oid", "")[:12], (cm.get("messageHeadline") or "")[:100], "", ""])
    # ---- audit sample (plan 5.5)
    rows = {"infrastructure": [], "spec": [], "model": []}; mixed_rows = []
    for c in cards:
        for r in c["failure_runs"]:
            a = c["attempts"][r["first_idx"]]; item = (c["id"], r["first_idx"] + 1, r["cat"], r["sub"], (a["text"] or "")[:1500].replace("\n", " "))
            if r["mixed"]: mixed_rows.append(item)
            elif r["cat"] in rows: rows[r["cat"]].append(item)
    rnd = random.Random(452); sample = []
    for cat in ("infrastructure", "spec", "model"):
        pool = sorted(rows[cat]); sample += rnd.sample(pool, min(10, len(pool)))
    return {"cards": cards, "unmatched": unmatched, "machine_total": machine_total, "free_total": free_total, "by_type": by_type, "ci": ci_all,
            "hand_rows": hand_rows, "audit_sample": sample, "mixed_rows": mixed_rows, "deny": deny, "builder_sha": sha256_file(builder_path)}


def share(n, d): return round(n / d, 3) if d else 0.0


def assemble_capture(raw, B, audit=None, hand=None):
    cards = B["cards"]; board = os.path.join(raw, "board")
    labels = {}  # operator labels for mixed rows: (card id, attempt no) -> category
    if audit:
        for r in audit["rows"]:
            if r.get("mixed", "").lower() == "true" and r.get("operator_category"): labels[(r["card"], int(r["attempt"]))] = r["operator_category"].strip().lower()
    runs_all = []
    for c in cards:
        for r in c["failure_runs"]:
            cat = labels.get((c["id"], r["first_idx"] + 1), "mixed") if r["mixed"] else r["cat"]
            runs_all.append((c, r, cat))
    n_runs = len(runs_all); by_cat = collections.Counter(cat for _, _, cat in runs_all); by_sub = collections.Counter(r["sub"] for _, r, _ in runs_all)
    att_all = [(c, a) for c in cards for a in c["attempts"] if a["ending"] in FAIL_ENDINGS]
    att_cat = collections.Counter(a["cause"][0] for _, a in att_all)
    top = max(CAUSE_ORDER, key=lambda s: (by_sub.get(s, 0), -CAUSE_ORDER.index(s)))
    att_sub = collections.Counter(a["cause"][1] for _, a in att_all); att_top = max(CAUSE_ORDER, key=lambda s: (att_sub.get(s, 0), -CAUSE_ORDER.index(s)))
    nonstale = [(c, r, cat) for c, r, cat in runs_all if r["sub"] != "stale_base"]
    cat_ns = collections.Counter(cat for _, _, cat in nonstale)
    merged = [c for c in cards if c["merged"] is not None]; with_v = [c for c in cards if c["has_verdict"]]
    hand_conf = 0
    if hand:
        hand_conf = len({(r["card"]) + str(r["oid"]) for r in hand["rows"] if r.get("status", "").strip().lower() == "confirmed"})
        conf_cards = {r["card"] for r in hand["rows"] if r.get("status", "").strip().lower() == "confirmed"}
    else: conf_cards = set()
    hand_cards = {c["id"] for c in cards if c["hand_fixed_auto"] and c["id"] in conf_cards} if hand else set()
    att_m = [c["attempts_to_merge"] for c in merged]
    # climb cross-check: board climbed events vs review-log climbed entries when exported
    mism = 0
    for c in cards:
        n_board = sum(e["type"] == "climbed" for e in c["evs"]); p = os.path.join(board, f"reviewlog-{c['key']}.txt")
        if os.path.exists(p):
            n_log = sum(1 for l in open(p).read().splitlines() if re.match(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s+climbed\s", l) and WS <= l[:19] < WE)
            if n_log != n_board: mism += 1
        elif n_board: mism += 0
    ledger_note = "tier_ledger.txt is aggregated by tier and preset (no card keys); the per-card cross-check uses the review log only"
    lens_hist = collections.Counter(); lens_dates = {}; rounds = collections.Counter()
    for c in cards:
        for e in c["evs"]:
            if e["type"] in ("verdict_approve", "verdict_held"):
                for l, o in lenses(e["body"]):
                    lens_hist[f"{l}:{o}"] += 1; lens_dates.setdefault(l, [e["t"], e["t"]]); lens_dates[l][0] = min(lens_dates[l][0], e["t"]); lens_dates[l][1] = max(lens_dates[l][1], e["t"])
            if e["type"] == "send_back": rounds[e["g"]["max"]] += 1
    tiers = collections.Counter();
    for c in cards:
        for e in c["evs"]:
            if e["type"] == "dispatch": tiers[(e["g"].get("tier") or e.get("tier_from_window") or "unknown")] += 1
    # refusal chains
    max_ref = 0; max_ref_cards = 0
    for c in cards:
        best = cur = 0
        for a in c["attempts"]:
            cur = cur + 1 if a["ending"] == "dispatch_refused" else 0; best = max(best, cur)
        if best > max_ref: max_ref, max_ref_cards = best, 1
        elif best == max_ref and best: max_ref_cards += 1
    # criteria
    wc = [c for c in cards if c["criteria"] and c["has_check"]]; po = [c for c in cards if c["criteria"] and not c["has_check"]]
    wcv = [c for c in wc if c["has_verdict"]]; pov = [c for c in po if c["has_verdict"]]
    crit = {"n_with_check": len(wc), "n_with_check_with_verdict": len(wcv), "first_pass_with_check": share(sum(c["first_pass"] for c in wcv), len(wcv)),
            "n_prose_only": len(po), "n_prose_only_with_verdict": len(pov), "first_pass_prose_only": share(sum(c["first_pass"] for c in pov), len(pov)),
            "merged_prose_only_without_check": sum(c["merged"] is not None for c in po), "with_check_code_share": share(sum(c["is_code"] for c in wc), len(wc)),
            "prose_only_code_share": share(sum(c["is_code"] for c in po), len(po)), "n_without_criteria": sum(1 for c in cards if not c["criteria"]), "spot_check_disagreements": 0}
    # cold open (plan 5.6)
    def cats_of(c): return [cat for cc, r, cat in runs_all if cc is c]
    cold = None; tier_used = 0
    cand = [c for c in merged if c["id"] not in hand_cards and not (c["hand_fixed_auto"] and not hand) and len([r for r in c["failure_runs"]]) >= 2]
    def pick(pool):
        return sorted(pool, key=lambda c: (-len(c["failure_runs"]), c["merged"]["t"]))[0] if pool else None
    t1 = [c for c in cand if sum(x in ("infrastructure", "spec") for x in cats_of(c)) > sum(x not in ("infrastructure", "spec") for x in cats_of(c))]
    t2 = [c for c in cand if any(x in ("infrastructure", "spec") for x in cats_of(c))]
    if t1: cold, tier_used = pick(t1), 1
    elif t2: cold, tier_used = pick(t2), 2
    summary = open(os.path.join(raw, "cold_open_summary.txt")).read().strip() if os.path.exists(os.path.join(raw, "cold_open_summary.txt")) else ""
    cold_block = {"card": "card-000", "summary": summary, "timeline": [], "send_backs": 0, "tries": 0, "failure_run_categories": [], "rule_tier": 0, "criteria_checks": [], "diff_files": 0, "diff_lines_added": 0, "diff_lines_removed": 0}
    if cold:
        cats = cats_of(cold)
        def names(s): return re.sub(r"\S*/(\S+)", r"\1", s)
        checks = [names(m.group(0).strip("`")) for m in CHECK_RX.finditer(cold["criteria"] or "")][:6]
        cold_block = {"card": cold["id"], "summary": summary, "tries": len(cold["failure_runs"]) + 1, "failure_run_categories": cats, "rule_tier": tier_used,
                      "send_backs": sum(a["ending"] in ("verdict_held", "ci_red") for a in cold["attempts"]), "criteria_checks": checks,
                      "diff_files": cold["diff"]["files"], "diff_lines_added": cold["diff"]["added"], "diff_lines_removed": cold["diff"]["removed"],
                      "timeline": [{"attempt": i + 1, "tier": a["tier"] or "unknown", "ended": a["ending"], "category": (a["cause"][0] if a["cause"] else "passed"),
                                    "hours_from_dispatch": round(hours(cold["first_dispatch"], a["end"]), 1) if a["end"] else None} for i, a in enumerate(cold["attempts"])]}
    # audit statistics
    aud = {"n": 0, "per_category": {}, "agreement": 0.0, "confusion": {}}
    if audit:
        conf = collections.Counter(); per = collections.Counter(); agree = 0; n = 0
        key = {(r["card"], int(r["attempt"])): r for r in audit["key"]}
        for r in audit["rows"]:
            if r.get("mixed", "").lower() == "true" or not r.get("operator_category"): continue
            k = key.get((r["card"], int(r["attempt"])))
            if not k: continue
            op = r["operator_category"].strip().lower(); cl = k["classifier_category"]
            conf[f"{cl}->{op}"] += 1; per[cl] += 1; n += 1; agree += op == cl
        aud = {"n": n, "per_category": dict(per), "agreement": share(agree, n), "confusion": dict(conf)}
    mixed_n = sum(1 for _, r, _ in runs_all if r["mixed"])
    hist = json.load(open(os.path.join(raw, "builder_history.json"))) if os.path.exists(os.path.join(raw, "builder_history.json")) else []
    wmc = json.load(open(os.path.join(raw, "worker_model_changes.json"))) if os.path.exists(os.path.join(raw, "worker_model_changes.json")) else []
    exported = open(os.path.join(board, "exported_at.txt")).read().strip() if os.path.exists(os.path.join(board, "exported_at.txt")) else ""
    max_rounds = max(rounds, key=lambda k: rounds[k]) if rounds else "0"
    cap = {"schema": "ep22-factory-export-capture-1",
           "export": {"window_start": WS + "Z", "window_end": WE + "Z", "window_days": 28, "n_repos": 1, "n_cards_on_board": len(glob.glob(os.path.join(board, "task-*.json"))),
                      "exported_at": exported, "builder_sha256": B["builder_sha"], "builder_history": hist, "worker_model_changes": wmc, "scrub_rules": SCRUB_RULES + ["private deny list"], "scrub_hits": 0},
           "factory": {"design": {"tiers": ["junior", "medior", "senior"], "review_max_rounds": int(max_rounds), "ci_mode": "serial, one branch at a time, full suite"}},
           "events": {"attempts_total": sum(len(c["attempts"]) for c in cards), "attempts_failed": len(att_all), "post_merge_dispatches": sum(c["post_merge"] for c in cards),
                      "dispatch_tiers": {k: tiers.get(k, 0) for k in ("junior", "medior", "senior", "unknown")}, "review_lenses_seen": {k: {"count": v} for k, v in lens_hist.items()},
                      "review_lens_dates": {l: [d[0].date().isoformat(), d[1].date().isoformat()] for l, d in lens_dates.items()}, "review_rounds_seen": dict(rounds),
                      "mechanical_gate_skipped": B["by_type"].get("mechanical_gate_skipped", 0), "max_consecutive_refusals": max_ref, "max_consecutive_refusals_cards": max_ref_cards,
                      "unmatched_machine_comments": len(B["unmatched"]), "machine_comments": B["machine_total"], "free_text_comments": B["free_total"], "by_type": dict(B["by_type"])},
           "metrics": {"tickets_dispatched": len(cards), "merged": len(merged), "merged_share": share(len(merged), len(cards)), "cards_with_verdict": len(with_v),
                       "first_pass": sum(c["first_pass"] for c in with_v), "first_pass_rate": share(sum(c["first_pass"] for c in with_v), len(with_v)),
                       "first_pass_rate_excl_stale_base": share(sum(c["first_pass_excl_stale"] for c in with_v), len(with_v)),
                       "first_pass_rate_excl_never_started": share(sum(c["first_pass_excl_never"] for c in with_v), len(with_v)),
                       "first_pass_ci_after_verdict": sum(c["ci_after_verdict"] for c in with_v),
                       "attempts_per_merged_mean": round(statistics.mean(att_m), 2) if att_m else 0.0, "attempts_per_merged_median": round(statistics.median(att_m), 2) if att_m else 0.0,
                       "escalated": sum(c["escalated"] for c in cards), "escalation_share": share(sum(c["escalated"] for c in cards), len(cards)),
                       "climb_crosscheck_mismatches": mism, "hours_to_merge_median": round(statistics.median([c["hours_to_merge"] for c in merged]), 1) if merged else 0.0,
                       "hand_fixed": sum(c["hand_fixed_auto"] for c in merged), "hand_fixed_confirmed": len(hand_cards), "hand_fixed_share": share(len(hand_cards), len(merged))},
           "ci": B["ci"],
           "causes": {"n_failed_attempts": len(att_all), "n_failure_runs": n_runs, "by_category": dict(by_cat), "by_subcategory": {s: by_sub[s] for s in CAUSE_ORDER if by_sub.get(s)},
                      "share_infra_spec": share(by_cat["infrastructure"] + by_cat["spec"], n_runs), "share_spec": share(by_cat["spec"], n_runs), "share_model_code": share(by_cat["model"], n_runs),
                      "share_infra_spec_excl_stale_base": share(cat_ns["infrastructure"] + cat_ns["spec"], len(nonstale)), "share_unknown": share(by_cat["unknown"], n_runs), "mixed_n": mixed_n,
                      "mixed_unresolved": sum(1 for _, _, cat in runs_all if cat == "mixed"),
                      "top_cause": {"subcategory": top, "n": by_sub.get(top, 0), "phrase": PHRASES.get(top, "")},
                      "attempt_level": {"share_infra_spec": share(att_cat["infrastructure"] + att_cat["spec"], len(att_all)), "share_spec": share(att_cat["spec"], len(att_all)),
                                        "share_model_code": share(att_cat["model"], len(att_all)), "top_cause": {"subcategory": att_top, "n": att_sub.get(att_top, 0)}}, "audit": aud},
           "criteria": crit, "examples": {"cold_open": cold_block},
           "notes": {"climb_crosscheck": ledger_note + ("; review logs not exported for every card" if not glob.glob(os.path.join(board, "reviewlog-*.txt")) else "")}}
    return cap, hist


def scrub_check(text, deny):
    hits = []
    for rx in SCRUB_RULES:
        for m in re.finditer(rx, text):
            if rx == r"\b[0-9a-f]{12,40}\b" and False: continue
            hits.append((rx, m.group(0)))
    for d in deny:
        if d and d.lower() in text.lower(): hits.append(("deny", d))
    return hits


def read_csv(p):
    with open(p, newline="") as f: return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--list-prs"); ap.add_argument("--build"); ap.add_argument("--only"); ap.add_argument("--audit"); ap.add_argument("--hand-fixes"); ap.add_argument("--show", action="store_true"); ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(); me = os.path.abspath(__file__)
    if a.list_prs:
        import subprocess; sys.exit(subprocess.call([sys.executable, os.path.join(os.path.dirname(me), "list_prs.py"), a.list_prs]))
    raw = a.build or os.path.dirname(os.path.abspath(a.audit or a.hand_fixes))
    only = set(a.only.split(",")) if a.only else None
    B = build(raw, only, me)
    if B is None: return
    if "--no-write" in sys.argv: return
    audit = hand = None
    if a.audit and os.path.exists(a.audit):
        audit = {"rows": read_csv(a.audit), "key": read_csv(os.path.join(raw, "audit_key.csv"))}
    if a.hand_fixes and os.path.exists(a.hand_fixes): hand = {"rows": read_csv(a.hand_fixes)}
    cap, hist = assemble_capture(raw, B, audit, hand)
    # private outputs
    with open(os.path.join(raw, "unmatched.txt"), "w") as f:
        for k, l in B["unmatched"]: f.write(f"{k}\t{l}\n")
    if not (a.audit or a.hand_fixes):
        with open(os.path.join(raw, "audit.csv"), "w", newline="") as f:
            w = csv.writer(f); w.writerow(["card", "attempt", "mixed", "comment_text", "operator_category"])
            for card, att, cat, sub, txt in B["audit_sample"]: w.writerow([card, att, "false", txt, ""])
            for card, att, cat, sub, txt in B["mixed_rows"]: w.writerow([card, att, "true", txt, ""])
        with open(os.path.join(raw, "audit_key.csv"), "w", newline="") as f:
            w = csv.writer(f); w.writerow(["card", "attempt", "classifier_category", "classifier_sub"])
            for card, att, cat, sub, txt in B["audit_sample"] + B["mixed_rows"]: w.writerow([card, att, cat, sub])
        with open(os.path.join(raw, "hand_fixes.csv"), "w", newline="") as f:
            w = csv.writer(f); w.writerow(["card", "pr", "oid", "first_line", "status", "note"]); w.writerows(B["hand_rows"])
    json.dump([{"id": c["id"], "key": c["key"], "prs": c["prs"], "attempts": [{k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in at.items() if k not in ("text",)} for at in c["attempts"]]} for c in B["cards"]],
              open(os.path.join(raw, "cards.json"), "w"), indent=1, default=str)
    out = os.path.join(os.path.dirname(raw.rstrip("/")) or ".", "factory-export-capture.json")
    text = json.dumps(cap, indent=1)
    hits = scrub_check(text, B["deny"])
    if hits:
        print("SCRUB REFUSED:", hits[:10], file=sys.stderr); sys.exit(2)
    open(out, "w").write(text); print("capture written", out, "scrub_hits 0")
    print(json.dumps({k: cap[k] for k in ("metrics", "causes")}, indent=1)[:1500]) if "--show" in sys.argv else None


if __name__ == "__main__":
    main()
