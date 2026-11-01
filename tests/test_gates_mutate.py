#!/usr/bin/env python3
"""Tests for hallmark-gates-mutate.

Behavioural cases run the real CLI in a subprocess and assert stdout / exit code;
structural cases call the parser and rule engine directly.  All fixtures are local;
nothing here touches the network.
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "hallmark_gates_mutate.py")
CLEAN = os.path.join(ROOT, "examples", "in", "gates.md")
BROKEN = os.path.join(ROOT, "examples", "in", "gates-broken.md")
sys.path.insert(0, ROOT)
import hallmark_gates_mutate as h  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, CLI, *args], capture_output=True, text=True)


class Behavioural(unittest.TestCase):
    def test_clean_file_exits_zero(self):
        p = run(CLEAN)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("findings=0", p.stdout)

    def test_seeded_defects_exit_one(self):
        p = run(BROKEN)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("house-tier", p.stdout)
        self.assertIn("clause-parent", p.stdout)

    def test_missing_path_is_usage_error(self):
        self.assertEqual(run().returncode, 2)

    def test_unreadable_path_is_input_error(self):
        self.assertEqual(run(os.path.join(ROOT, "does-not-exist.md")).returncode, 2)

    def test_json_output_is_parseable(self):
        p = run(BROKEN, "--json")
        doc = json.loads(p.stdout)
        self.assertEqual(doc["verdict"], "findings")
        self.assertGreaterEqual(len(doc["findings"]), 3)
        self.assertEqual(p.returncode, 1)

    def test_json_on_clean_file_self_proves(self):
        doc = json.loads(run(CLEAN, "--json").stdout)
        self.assertTrue(doc["self_proven"])
        self.assertEqual(doc["mutations_skipped"], 0)


class Structure(unittest.TestCase):
    def test_real_doc_parses_90_gate_rows(self):
        model, findings = h.analyze(open(CLEAN).read())
        self.assertEqual(len(model.rows), 90)
        self.assertEqual(findings, [])

    def test_real_doc_has_26_finish_checks(self):
        model, _ = h.analyze(open(CLEAN).read())
        self.assertEqual(sorted(set(model.f_checks)), list(range(1, 27)))

    def test_duplicate_id_is_reported(self):
        text = open(CLEAN).read().replace("| 2b |", "| 2a |", 1)
        _m, findings = h.analyze(text)
        self.assertIn("id-unique", {f["rule"] for f in findings})

    def test_retired_number_is_reported(self):
        text = open(CLEAN).read().replace("| 2b |", "| 13 |", 1)
        _m, findings = h.analyze(text)
        self.assertIn("retired-id", {f["rule"] for f in findings})

    def test_tier_vocabulary_is_enforced(self):
        text = open(CLEAN).read().replace("| 2b | Reflex |", "| 2b | Vibe |", 1)
        _m, findings = h.analyze(text)
        self.assertIn("tier-vocab", {f["rule"] for f in findings})

    def test_every_rule_has_a_mutation(self):
        self.assertEqual({n for n, _ in h.RULES}, set(h.MUTATIONS))

    def test_mutation_harness_catches_every_rule(self):
        bad = [x["rule"] for x in h.mutation_test(open(CLEAN).read())
               if x.get("covered") is not True and not x.get("skipped")]
        self.assertEqual(bad, [])

    def test_no_mutation_flag_returns_unproven(self):
        p = run(CLEAN, "--no-mutation")
        self.assertEqual(p.returncode, 2)
        self.assertIn("unproven", json.loads(run(CLEAN, "--no-mutation", "--json").stdout)["verdict"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
