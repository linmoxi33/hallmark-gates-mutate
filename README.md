# hallmark-gates-mutate

An offline spec checker for `Nutlope/hallmark`'s `references/gates.md` that will not print
a verdict until it has proved, by mutation, that every one of its own rules still catches the
defect it claims to catch. Run it in CI before you edit a gate: Hallmark's `sloplint.mjs`
derives its tier map from this file, so a broken spec row silently changes what ships.

Upstream: https://github.com/Nutlope/hallmark

## Why now

`gates.md` is the authority. It says so itself: *"`scripts/sloplint.mjs` implements every gate
tagged M and derives its tier map from this file, **which wins on any disagreement**"*
([source](https://github.com/Nutlope/hallmark/blob/main/skills/hallmark/references/gates.md)).
Nothing offline checks that file's internal consistency, and rule bugs do reach users:

- [#113 sloplint gate 63 misses a middle dot between JSX expressions](https://github.com/Nutlope/hallmark/issues/113)
- [#106 sloplint skips explicit build targets after their parent directory](https://github.com/Nutlope/hallmark/issues/106)
- [#114 sloplint Floor 56 flags a sticky `th` inside an `overflow-x` scroll container](https://github.com/Nutlope/hallmark/issues/114)

Those are three *rules* that do not do what they claim. `hallmark-gates-mutate` attacks the
same class of failure from the other side: it treats the spec table as data and verifies the
structure the implementation relies on.

## What it does / does not do

Does: parse the gate tables in `gates.md` and check 17 structural invariants — header shape,
separator rows, cell counts, gate-id format and uniqueness, clause-group contiguity, reuse of
retired numbers, tier and class vocabulary, non-empty tell/fix, the four house rules
(54, 58, 63, 67) being `Floor`, the prose lists matching the code constants, the F-check
sequence, waiver grammar, and a minimum gate count.

Before reporting, it runs **rule-level mutation testing**: for each of the 17 rules it injects
the exact defect that rule exists to catch, and the mutated document must make that same rule
fire. A rule that stays silent is not counted as coverage and the run exits `2` (`unproven`)
instead of vouching for the file.

Does not: run `sloplint`, render pages, judge design, or touch the network. It never edits the
file it reads.

## Install / usage

No dependencies, Python 3.8+.

```bash
python3 hallmark_gates_mutate.py examples/in/gates.md          # rc=0, clean spec
python3 hallmark_gates_mutate.py examples/in/gates-broken.md   # rc=1, 3 findings
python3 hallmark_gates_mutate.py examples/in/gates.md --json   # machine-readable report
```

`--json` prints one object (parse it with `python3 -c "import json,sys;json.load(sys.stdin)"`):

```json
{
  "gate_rows": 81,
  "mutation_score": "14/15 executed",
  "self_proven": true,
  "verdict": "findings",
  "findings": [
    {"rule": "house-tier", "line": 129,
     "message": "house rule 54 must be Floor, found 'Reflex'"}
  ]
}
```

Exit codes: `0` clean and self-proved · `1` findings · `2` usage, unreadable input, an
unproved rule, or `--no-mutation`.

## 本轮创新

First offline checker that makes a *specification document* prove its own test coverage:
before judging `gates.md`, it mutates every rule's target defect and requires the rule to fire
(17/17 executed on the real file, 3 seeded defects caught on the fixture). Existing trending
linters in this account scan a config for problems; this one refuses to report unless its rule
set is mutation-covered, so "0 findings" cannot mean "the checker is asleep" — the failure mode
that [#113](https://github.com/Nutlope/hallmark/issues/113)/[#106](https://github.com/Nutlope/hallmark/issues/106)
show in sloplint itself.

## Limits

The `RETIRED` and house-rule constants mirror the prose in `gates.md` § 1/§ 4; if upstream
rewrites that prose the tool reports a mismatch rather than guessing. Mutations whose seed row
is already defective in the input are reported as `skipped`, never as a pass. The checker
validates structure, not whether a gate's wording is good design.
