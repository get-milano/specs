#!/usr/bin/env python3
"""Tests for tools/generate_numeric_vectors.py.

The tool writes 150 of the suite's vectors by composing boundary constants
and evaluating each through the reference checker. Because the output is
committed, two properties carry the whole design: the run is deterministic,
so a regenerated suite is reviewable as a diff rather than a churn of 150
files, and the committed files are exactly what today's tool produces, so
nobody has hand-edited an expectation into the suite.

The second property is the one worth having. It is checked by regenerating
into a temp directory and comparing bytes with what is committed.

Run: python3 tools/test_generate_numeric_vectors.py
"""

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent

sys.path.insert(0, str(TOOLS))

import generate_numeric_vectors as gnv  # noqa: E402
import reference_check as rc  # noqa: E402

COMMITTED = ROOT / "conformance" / "generated-numeric"


class Determinism(unittest.TestCase):
    """The seed is the whole contract: same seed, same suite, every time."""

    def test_the_expression_pool_is_reproducible(self):
        first = gnv.build_expressions(random.Random(gnv.SEED))
        second = gnv.build_expressions(random.Random(gnv.SEED))
        self.assertEqual(first, second)

    def test_the_function_pool_is_reproducible_and_its_own(self):
        first = gnv.build_function_expressions(random.Random(gnv.FUNCTION_SEED))
        second = gnv.build_function_expressions(random.Random(gnv.FUNCTION_SEED))
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(set(first)), gnv.FUNCTION_COUNT)
        self.assertNotEqual(gnv.FUNCTION_SEED, gnv.SEED)

    def test_a_different_seed_produces_a_different_pool(self):
        # Guards against a build that ignores the rng and returns a constant
        # list, which would satisfy the test above perfectly.
        other = gnv.build_expressions(random.Random(gnv.SEED + 1))
        self.assertNotEqual(gnv.build_expressions(random.Random(gnv.SEED)), other)

    def test_the_pool_is_large_enough_to_fill_the_suite(self):
        # Emission skips duplicates and type-mismatched compositions, so the
        # pool has to over-produce or the suite comes up short in silence.
        pool = gnv.build_expressions(random.Random(gnv.SEED))
        self.assertGreaterEqual(len(set(pool)), gnv.COUNT)


class RegeneratesTheCommittedSuite(unittest.TestCase):
    """The committed files are what the tool writes today, byte for byte."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        suite = Path(cls.directory.name) / "conformance" / "generated-numeric"
        original_root, original_suite = gnv.ROOT, gnv.SUITE
        gnv.ROOT, gnv.SUITE = Path(cls.directory.name), suite
        try:
            gnv.main()
        finally:
            gnv.ROOT, gnv.SUITE = original_root, original_suite
        cls.regenerated = suite

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_the_same_files_are_produced(self):
        produced = sorted(p.name for p in self.regenerated.glob("*.json"))
        committed = sorted(p.name for p in COMMITTED.glob("*.json"))
        self.assertEqual(produced, committed)

    def test_every_file_matches_byte_for_byte(self):
        for path in sorted(self.regenerated.glob("*.json")):
            with self.subTest(vector=path.name):
                self.assertEqual(path.read_bytes(),
                                 (COMMITTED / path.name).read_bytes(),
                                 f"{path.name} differs from the committed vector")

    def test_the_declared_count_was_emitted(self):
        vectors = [p for p in self.regenerated.glob("*.json")
                   if p.name != "vocabulary.json"]
        self.assertEqual(len(vectors), gnv.COUNT + gnv.FUNCTION_COUNT)

    def test_names_are_sequential_and_zero_padded(self):
        # The names are the suite's stable identity: an engine reporting a
        # failure names one, so a renumbering would orphan every reference.
        names = sorted(p.stem for p in self.regenerated.glob("gen-numeric-[0-9]*.json"))
        self.assertEqual(names,
                         [f"gen-numeric-{i:03d}" for i in range(gnv.COUNT)])
        functions = sorted(p.stem for p in self.regenerated.glob("gen-numeric-fn-*.json"))
        self.assertEqual(functions,
                         [f"gen-numeric-fn-{i:03d}" for i in range(gnv.FUNCTION_COUNT)])

    def test_the_first_batch_declares_contract_1_0_and_the_function_batch_2_1(self):
        # The numeric functions arrived with contract 2.1 and are refused
        # in a document declaring less (document model spec, Validation),
        # so the batch that composes them has to declare it; the original
        # batch keeps pinning 1.0's acceptance, byte for byte.
        for path in self.regenerated.glob("gen-numeric-*.json"):
            version = json.loads(path.read_text())["document"]["version"]
            expected = "2.1.0" if "-fn-" in path.name else "1.0.0"
            self.assertEqual(version, expected, path.name)

    def test_the_function_batch_uses_every_function(self):
        text = "".join(path.read_text() for path in self.regenerated.glob("gen-numeric-fn-*.json"))
        for function in ("$abs(", "$min(", "$max(", "$floor(", "$ceil(", "$round("):
            self.assertIn(function, text, f"{function} never composed")


class VectorShape(unittest.TestCase):
    """What one generated vector claims, and who decided it."""

    def test_a_vector_carries_the_expectation_the_checker_computed(self):
        vector = gnv.vector_for("gen-numeric-test", "$str(1 + 1)")
        self.assertEqual(vector["name"], "gen-numeric-test")
        self.assertEqual(vector["expect"]["view"]["properties"]["text"], "2")
        self.assertEqual(vector["expect"]["occurrences"], [])

    def test_the_description_records_the_seed_and_the_expression(self):
        # A generated vector has no author to ask, so it has to say where it
        # came from and how to reproduce it.
        vector = gnv.vector_for("gen-numeric-test", "$str(2 * 3)")
        self.assertIn(str(gnv.SEED), vector["description"])
        self.assertIn("$str(2 * 3)", vector["description"])

    def test_a_function_vector_declares_the_contract_it_needs(self):
        vector = gnv.vector_for("gen-numeric-fn-test", "$str($round(2.5))",
                                "2.1.0", gnv.FUNCTION_SEED)
        self.assertEqual(vector["document"]["version"], "2.1.0")
        self.assertEqual(vector["expect"]["view"]["properties"]["text"], "3.0")
        self.assertIn(str(gnv.FUNCTION_SEED), vector["description"])

    def test_reported_occurrences_are_carried_into_the_expectation(self):
        # The interesting half of the numeric suite: an engine has to report
        # the same arithmetic occurrence, not just compute the same digits.
        vector = gnv.vector_for("gen-numeric-test", "$str(1 / 0)")
        self.assertEqual(vector["expect"]["view"]["properties"]["text"], "0")
        self.assertEqual(vector["expect"]["occurrences"],
                         [{"kind": "divisionByZero", "node": "r", "name": "text"}])

    def test_a_checker_defect_is_not_swallowed(self):
        # Only a type mismatch is a reason to skip a composition. A bare
        # except once hid a crash on `inf % x`, and with it every vector
        # that would have pinned the case; the generator has to fail.
        original = gnv.vector_for
        gnv.vector_for = lambda name, expression, *rest: (_ for _ in ()).throw(
            RuntimeError("checker defect"))
        with tempfile.TemporaryDirectory() as directory:
            root, suite = gnv.ROOT, gnv.SUITE
            gnv.ROOT = Path(directory)
            gnv.SUITE = Path(directory) / "conformance" / "generated-numeric"
            try:
                with self.assertRaises(RuntimeError):
                    gnv.main()
            finally:
                gnv.ROOT, gnv.SUITE = root, suite
                gnv.vector_for = original

    def test_an_ill_typed_composition_raises_rather_than_emitting(self):
        # main() relies on this to skip compositions the pool produced by
        # chance; if it silently emitted instead, the suite would carry a
        # vector no engine could satisfy.
        with self.assertRaises(rc.GateError):
            gnv.vector_for("gen-numeric-test", "$str('a' + 1)")


class TheCommittedSuiteItself(unittest.TestCase):
    """Properties of what is on disk, independent of regeneration."""

    def test_every_vector_resolves_to_a_string(self):
        # Every generated expression is wrapped in str(): the vocabulary has
        # one string property, so anything else would have failed the gate.
        for path in sorted(COMMITTED.glob("gen-numeric-*.json")):
            with self.subTest(vector=path.name):
                vector = json.loads(path.read_text())
                text = vector["expect"]["view"]["properties"]["text"]
                self.assertIsInstance(text, str)

    def test_the_committed_vocabulary_matches_the_tool_s(self):
        committed = json.loads((COMMITTED / "vocabulary.json").read_text())
        self.assertEqual(committed, gnv.VOCABULARY)

    def test_the_suite_covers_the_boundaries_it_exists_for(self):
        # The point of the suite is the edges: overflow, non-finite results,
        # saturation. A pool that drifted to only tame arithmetic would keep
        # every other test in this file green.
        texts = [json.loads(p.read_text())["expect"]["view"]["properties"]["text"]
                 for p in COMMITTED.glob("gen-numeric-*.json")]
        self.assertTrue(any(t in ("nan", "inf", "-inf") for t in texts),
                        "no non-finite results in the generated suite")
        self.assertTrue(any("e" in t for t in texts),
                        "no scientific-notation results in the generated suite")

    def test_some_vector_reports_an_arithmetic_occurrence(self):
        occurrences = [json.loads(p.read_text())["expect"]["occurrences"]
                       for p in COMMITTED.glob("gen-numeric-*.json")]
        self.assertTrue(any(entry for entry in occurrences),
                        "no generated vector exercises an arithmetic report")


if __name__ == "__main__":
    unittest.main(verbosity=2)
