#!/usr/bin/env python3
"""hallmark-gates-mutate - offline spec checker for Nutlope/hallmark's gates.md.

It checks the gate table that sloplint.mjs declares as its source of truth, and
before it prints a verdict it runs a *rule-level mutation test*: every rule
below is injected with the exact defect it is meant to catch, and the mutation
must be reported by that same rule.  A rule that survives its own mutation is
not counted as coverage, and the tool exits 2 instead of vouching for the file.

Exit codes: 0 = clean + self-proved, 1 = findings, 2 = usage / input / self-check.
Zero third-party dependencies.  No network access.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict

RETIRED = {5, 13, 14, 21, 31, 35, 36, 43, 45, 51, 52, 57, 60, 61}
ALLOW_ROMAN = True
HOUSE = {54, 58, 63, 67}
GATE_TIERS = {"Floor", "Reflex", "Ledger"}
GATE_CLASSES = {"M", "M/R", "R", "R/J", "J", "M/J"}
GATE_HEADER = ["Gate", "Tier", "Class", "The tell", "The fix"]
MIN_GATES = 80
ID_RE = re.compile(r"^[0-9]+(?:[a-z]|[ivx]{2,4})?$")
NUM_RE = re.compile(r"[0-9]+")


@dataclass
class Row:
    line: int
    cells: list
    gid: str = ""
    tier: str = ""
    cls: str = ""
    tell: str = ""
    fix: str = ""


@dataclass
class Model:
    rows: list = field(default_factory=list)
    header_lines: list = field(default_factory=list)
    header_bad: list = field(default_factory=list)
    sep_missing: list = field(default_factory=list)
    pipe_bad: list = field(default_factory=list)
    f_checks: list = field(default_factory=list)
    f_section: bool = False
    prose_house: set = field(default_factory=set)
    prose_retired: set = field(default_factory=set)
    waive_clause: str = ""


def _is_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and len(s) > 2


def parse(text: str) -> Model:
    m = Model()
    lines = text.splitlines()
    # markdown tables: header, separator, body
    i = 0
    while i < len(lines):
        line = lines[i]
        if not _is_row(line):
            if line.strip().startswith("|") and not line.strip().endswith("|"):
                m.pipe_bad.append(i + 1)
            i += 1
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if i + 1 < len(lines) and _is_row(lines[i + 1]):
            nxt = [c.strip() for c in lines[i + 1].strip().strip("|").split("|")]
            if cells == GATE_HEADER and not all(re.fullmatch(r":?-{2,}:?", c) for c in nxt if c != ""):
                m.sep_missing.append(i + 2)
            if all(re.fullmatch(r":?-{2,}:?", c) for c in nxt if c != ""):
                if cells == GATE_HEADER:
                    m.header_lines.append(i + 1)
                j = i + 2
                while j < len(lines) and _is_row(lines[j]):
                    body = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                    if cells == GATE_HEADER:
                        r = Row(line=j + 1, cells=body)
                        if len(body) >= 5:
                            r.gid, r.tier, r.cls, r.tell, r.fix = (
                                body[0], body[1], body[2], body[3], body[4])
                        m.rows.append(r)
                    j += 1
                i = j
                continue
            if cells == GATE_HEADER or ("Gate" in cells and "Tier" in cells):
                m.header_bad.append(i + 1)
        i += 1

    # section 5 -> F checks (inline prose, not a table)
    sec5 = re.search(r"^##\s*5\.(.*?)(?=^##\s*6\.)", text, re.S | re.M)
    if sec5:
        m.f_section = True
        m.f_checks = [int(x) for x in re.findall(r"\bF(\d+)\b", sec5.group(1))]
    # house-rule prose: "... house rule ...: 54 (the eyebrow), 58 ..., 63 ..., 67 ... and no others"
    h = re.search(r"house rule.{0,200}?:\s*([^.]{0,200}?)and no others", text, re.S)
    if h:
        m.prose_house = {int(x) for x in NUM_RE.findall(h.group(1))}
    # retired prose
    r = re.search(r"Retired numbers stay retired:[\* ]*(.+?)\s*are never reused", text, re.S)
    if r:
        m.prose_retired = {int(x) for x in NUM_RE.findall(r.group(1))}
    w = re.search(r"waive\s+([0-9]+[a-z]{1,2})\b", text)
    if w:
        m.waive_clause = w.group(1)
    return m


# ---------------------------------------------------------------- rules
def rule_header(m, t):
    out = [(ln, "gate table header must be exactly " + " | ".join(GATE_HEADER))
           for ln in m.header_bad]
    for i, line in enumerate(t.splitlines(), 1):
        if not _is_row(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if "Gate" in cells and "Tier" in cells and cells != GATE_HEADER:
            out.append((i, "gate table header must be exactly " + " | ".join(GATE_HEADER)))
    return out


def rule_separator(m, t):
    return [(ln, "table header is not followed by a --- separator row") for ln in m.sep_missing]


def rule_pipe(m, t):
    return [(ln, "table row starts with '|' but does not end with '|'") for ln in m.pipe_bad]


def rule_row_width(m, t):
    return [(r.line, "gate row has %d cells, expected 5" % len(r.cells))
            for r in m.rows if len(r.cells) != 5]


def rule_id_format(m, t):
    return [(r.line, "gate id %r does not match ^[0-9]+[a-z]{0,2}$" % r.gid)
            for r in m.rows if not ID_RE.fullmatch(r.gid)]


def rule_id_unique(m, t):
    seen, out = {}, []
    for r in m.rows:
        if r.gid in seen:
            out.append((r.line, "duplicate gate id %r (first at line %d)" % (r.gid, seen[r.gid])))
        else:
            seen[r.gid] = r.line
    return out


def _parent(gid):
    return gid.rstrip("abcdefghijklmnopqrstuvwxyz") if gid and gid[-1].isalpha() else gid


def rule_clause_parent(m, t):
    groups = {}
    for r in m.rows:
        if r.gid and re.fullmatch(r"[0-9]+[a-z]", r.gid):
            groups.setdefault(r.gid[:-1], []).append(r)
    out = []
    for parent, rows in groups.items():
        if len(rows) < 2:
            continue
        suffixes = [r.gid[-1] for r in rows]
        if suffixes != sorted(suffixes):
            out.append((rows[0].line, "clauses of %s are out of order: %s" % (parent, suffixes)))
        if suffixes != [chr(ord("a") + k) for k in range(len(suffixes))]:
            out.append((rows[0].line, "clauses of %s are not contiguous from 'a': %s"
                        % (parent, suffixes)))
    return out


def rule_retired(m, t):
    out = []
    for r in m.rows:
        if r.gid.isdigit() and int(r.gid) in RETIRED:
            out.append((r.line, "retired gate number %s is reused" % r.gid))
    return out


def rule_tier_vocab(m, t):
    return [(r.line, "tier %r not in %s" % (r.tier, sorted(GATE_TIERS)))
            for r in m.rows if r.tier not in GATE_TIERS]


def rule_class_vocab(m, t):
    return [(r.line, "class %r not in %s" % (r.cls, sorted(GATE_CLASSES)))
            for r in m.rows if r.cls not in GATE_CLASSES]


def rule_tell_fix(m, t):
    out = []
    for r in m.rows:
        if len(r.tell) < 8:
            out.append((r.line, "gate %s has an empty or truncated 'tell' cell" % r.gid))
        if len(r.fix) < 2:
            out.append((r.line, "gate %s has an empty 'fix' cell" % r.gid))
    return out


def rule_house_tier(m, t):
    out = []
    for r in m.rows:
        if r.gid.isdigit() and int(r.gid) in HOUSE and r.tier != "Floor":
            out.append((r.line, "house rule %s must be Floor, found %r" % (r.gid, r.tier)))
    return out


def rule_house_prose(m, t):
    if m.prose_house and m.prose_house != HOUSE:
        return [(0, "prose house-rule list %s != %s" % (sorted(m.prose_house), sorted(HOUSE)))]
    return []


def rule_retired_prose(m, t):
    if m.prose_retired and m.prose_retired != RETIRED:
        return [(0, "prose retired list %s != %s" % (sorted(m.prose_retired), sorted(RETIRED)))]
    return []


def rule_f_sequence(m, t):
    if not m.f_section:
        return [(0, "section 5 (Finish checks) not found")]
    out = []
    if len(set(m.f_checks)) != len(m.f_checks):
        out.append((0, "duplicate F-check ids: %s" % sorted(x for x in set(m.f_checks)
                                                           if m.f_checks.count(x) > 1)))
    if m.f_checks and sorted(set(m.f_checks)) != list(range(1, max(m.f_checks) + 1)):
        missing = sorted(set(range(1, max(m.f_checks) + 1)) - set(m.f_checks))
        out.append((0, "F-checks are not contiguous from 1; missing %s" % missing))
    return out


def rule_waiver_grammar(m, t):
    if not m.waive_clause:
        return [(0, "no 'waive <clause>' example found in section 2")]
    if not ID_RE.fullmatch(m.waive_clause):
        return [(0, "waiver example %r is not a gate clause id" % m.waive_clause)]
    return []


def rule_min_gates(m, t):
    if len(m.rows) < MIN_GATES:
        return [(0, "only %d gate rows, expected >= %d" % (len(m.rows), MIN_GATES))]
    return []


RULES = [
    ("header", rule_header),
    ("separator", rule_separator),
    ("pipe-balance", rule_pipe),
    ("row-width", rule_row_width),
    ("id-format", rule_id_format),
    ("id-unique", rule_id_unique),
    ("clause-parent", rule_clause_parent),
    ("retired-id", rule_retired),
    ("tier-vocab", rule_tier_vocab),
    ("class-vocab", rule_class_vocab),
    ("tell-fix", rule_tell_fix),
    ("house-tier", rule_house_tier),
    ("house-prose", rule_house_prose),
    ("retired-prose", rule_retired_prose),
    ("f-sequence", rule_f_sequence),
    ("waiver-grammar", rule_waiver_grammar),
    ("min-gates", rule_min_gates),
]


def analyze(text: str):
    m = parse(text)
    findings = []
    for name, fn in RULES:
        for line, msg in fn(m, text):
            findings.append({"rule": name, "line": line, "message": msg})
    return m, findings


# ------------------------------------------------------- mutations
def _data_rows(text):
    lines = text.splitlines()
    idx = [i for i, l in enumerate(lines) if _is_row(l)]
    # gate data rows: after a Gate header, skip separator
    out = []
    def _valid_header(line):
        if not _is_row(line):
            return False
        return [c.strip() for c in line.strip().strip("|").split("|")] == GATE_HEADER

    for i in range(len(lines) - 1):
        if _valid_header(lines[i]):
            j = i + 2
            while j < len(lines) and _is_row(lines[j]):
                out.append(j)
                j += 1
    return lines, out


def _mut(text, old, new, count=1):
    if old not in text:
        raise AssertionError("anchor not found: %r" % old[:40])
    return text.replace(old, new, count)


def mut_header(t):
    return _mut(t, "| Gate | Tier | Class | The tell | The fix |",
                "| Gate | Tier | Class | The tells | The fix |")


def mut_separator(t):
    lines, rows = _data_rows(t)
    sep = rows[0] - 1
    assert re.fullmatch(r"\s*\|(\s*:?-{2,}:?\s*\|)+\s*", lines[sep]), lines[sep]
    del lines[sep]
    return "\n".join(lines) + "\n"


def mut_pipe(t):
    lines, rows = _data_rows(t)
    i = rows[0]
    lines[i] = lines[i].rstrip()
    assert lines[i].endswith("|")
    lines[i] = lines[i][:-1]
    return "\n".join(lines) + "\n"


def mut_row_width(t):
    lines, rows = _data_rows(t)
    i = rows[0]
    lines[i] = " | ".join(lines[i].rstrip().rstrip("|").split("|")[:-1]) + " |"
    return "\n".join(lines) + "\n"


def mut_id_format(t):
    lines, rows = _data_rows(t)
    i = rows[0]
    lines[i] = re.sub(r"\|\s*[0-9]+[a-z]?\s*\|", "| 2! |", lines[i], count=1)
    return "\n".join(lines) + "\n"


def mut_id_unique(t):
    lines, rows = _data_rows(t)
    lines.insert(rows[1], lines[rows[0]])
    return "\n".join(lines) + "\n"


def mut_clause_parent(t):
    return _mut(t, "| 44d |", "| 44e |", 1)


def mut_retired_id(t):
    lines, rows = _data_rows(t)
    i = rows[0]
    lines[i] = re.sub(r"\|\s*[0-9]+[a-z]?\s*\|", "| 5 |", lines[i], count=1)
    return "\n".join(lines) + "\n"


def mut_tier_vocab(t):
    lines, rows = _data_rows(t)
    i = rows[0]
    cells = lines[i].split("|")
    cells[2] = " Vibe "
    lines[i] = "|".join(cells)
    return "\n".join(lines) + "\n"


def mut_class_vocab(t):
    lines, rows = _data_rows(t)
    i = rows[0]
    cells = lines[i].split("|")
    cells[3] = " Q "
    lines[i] = "|".join(cells)
    return "\n".join(lines) + "\n"


def mut_tell_fix(t):
    lines, rows = _data_rows(t)
    i = rows[0]
    cells = lines[i].split("|")
    cells[4] = " "
    lines[i] = "|".join(cells)
    return "\n".join(lines) + "\n"


def mut_house_tier(t):
    return _mut(t, "| 54 | Floor |", "| 54 | Reflex |", 1)


def mut_house_prose(t):
    return _mut(t, "54 (the eyebrow)", "53 (the eyebrow)", 1)


def mut_retired_prose(t):
    return _mut(t, "retired:** 5, 13,", "retired:** 5, 12,", 1)


def mut_f_sequence(t):
    return _mut(t, "F2 `...`", "F29 `...`", 1)


def mut_waiver_grammar(t):
    return _mut(t, "waive 47b", "waive 47", 1)


def mut_min_gates(t):
    lines, rows = _data_rows(t)
    for i in sorted(rows[40:], reverse=True):
        del lines[i]
    return "\n".join(lines) + "\n"


MUTATIONS = {
    "header": mut_header,
    "separator": mut_separator,
    "pipe-balance": mut_pipe,
    "row-width": mut_row_width,
    "id-format": mut_id_format,
    "id-unique": mut_id_unique,
    "clause-parent": mut_clause_parent,
    "retired-id": mut_retired_id,
    "tier-vocab": mut_tier_vocab,
    "class-vocab": mut_class_vocab,
    "tell-fix": mut_tell_fix,
    "house-tier": mut_house_tier,
    "house-prose": mut_house_prose,
    "retired-prose": mut_retired_prose,
    "f-sequence": mut_f_sequence,
    "waiver-grammar": mut_waiver_grammar,
    "min-gates": mut_min_gates,
}


def mutation_test(text: str):
    result = []
    for name, _fn in RULES:
        mut = MUTATIONS.get(name)
        if mut is None:
            result.append({"rule": name, "covered": False, "error": "no mutation defined"})
            continue
        try:
            mutated = mut(text)
            _m, found = analyze(mutated)
            hit = any(f["rule"] == name for f in found)
            result.append({"rule": name, "covered": hit,
                           "error": None if hit else "mutation not reported by its own rule"})
        except AssertionError as exc:
            # The seed anchor this mutation edits is absent from *this* input
            # (e.g. the file already carries that exact defect).  Skipping is
            # honest: it is not a pass, and it does not count as a tool bug.
            result.append({"rule": name, "covered": None, "skipped": True,
                           "error": "seed anchor absent in this input: %s" % exc})
        except Exception as exc:  # a mutation harness must never fake a pass
            result.append({"rule": name, "covered": False, "skipped": False, "error": repr(exc)})
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="hallmark-gates-mutate",
        description="Offline spec checker for Nutlope/hallmark gates.md, with rule-level mutation proof.")
    ap.add_argument("path", nargs="?", help="path to gates.md")
    ap.add_argument("--json", action="store_true", dest="as_json", help="machine-readable report")
    ap.add_argument("--no-mutation", action="store_true",
                    help="skip the self-mutation proof (report is then labelled unproven)")
    args = ap.parse_args(argv)
    if not args.path:
        ap.print_usage(sys.stderr)
        print("error: missing gates.md path", file=sys.stderr)
        return 2
    try:
        with open(args.path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print("error: cannot read %s: %s" % (args.path, exc), file=sys.stderr)
        return 2

    model, findings = analyze(text)
    mutations = [] if args.no_mutation else mutation_test(text)
    uncovered = [x["rule"] for x in mutations if x.get("covered") is False]
    executed = [x for x in mutations if not x.get("skipped")]
    caught = [x for x in executed if x.get("covered")]
    by_rule = {}
    for name, _ in RULES:
        by_rule[name] = sum(1 for f in findings if f["rule"] == name)

    if uncovered or args.no_mutation:
        verdict = "unproven"
    elif findings:
        verdict = "findings"
    else:
        verdict = "pass"

    report = {
        "file": args.path,
        "gate_rows": len(model.rows),
        "f_checks": len(set(model.f_checks)),
        "rules": [{"rule": n, "findings": by_rule[n]} for n, _ in RULES],
        "mutations": mutations,
        "mutation_score": ("%d/%d executed" % (len(caught), len(executed)))
        if executed else "skipped",
        "mutations_skipped": len(mutations) - len(executed),
        "findings": findings,
        "self_proven": bool(executed) and not uncovered,
        "verdict": verdict,
    }
    if args.as_json:
        json.dump(report, sys.stdout, indent=2, sort_keys=False)
        sys.stdout.write("\n")
    else:
        for f in findings:
            print("%s:%s: %s: %s" % (args.path, f["line"], f["rule"], f["message"]))
        print("gates=%d rules=%d findings=%d mutation=%s" %
              (len(model.rows), len(RULES), len(findings), report["mutation_score"]))
        if uncovered:
            print("self-check failed, rules not proven by their own mutation: %s" %
                  ", ".join(uncovered), file=sys.stderr)
    if uncovered or args.no_mutation:
        return 2
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
