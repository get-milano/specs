#!/usr/bin/env python3
"""Tests for tools/generate_order_vectors.py.

The tool composes every pair of gate violations into one document and
lets the reference gate say which error wins. As for the other generated
suites: the run is deterministic, the committed files are exactly what
today's tool produces, and the catalog is the whole input.

Run: python3 tools/test_generate_order_vectors.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import generate_order_vectors as gov  # noqa: E402

COMMITTED = ROOT / "conformance" / "generated-order"


def committed(name):
    return json.loads((COMMITTED / f"gen-order-{name}.json").read_text())


class RegeneratesTheCommittedSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        suite = Path(cls.directory.name) / "conformance" / "generated-order"
        original_root, original_suite = gov.ROOT, gov.SUITE
        gov.ROOT, gov.SUITE = Path(cls.directory.name), suite
        try:
            gov.main()
        finally:
            gov.ROOT, gov.SUITE = original_root, original_suite
        cls.regenerated = suite

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_the_same_files_are_produced(self):
        produced = sorted(p.name for p in self.regenerated.glob("*.json"))
        committed_names = sorted(p.name for p in COMMITTED.glob("*.json"))
        self.assertEqual(produced, committed_names)

    def test_every_file_matches_byte_for_byte(self):
        for path in sorted(self.regenerated.glob("*.json")):
            with self.subTest(vector=path.name):
                self.assertEqual(path.read_bytes(), (COMMITTED / path.name).read_bytes())


class Catalog(unittest.TestCase):
    """Each injector plants the defect it is named for, alone."""

    INTENDED = {
        "malformed-id": ("MalformedDocument", None),
        "unsupported-version": ("UnsupportedVersion", None),
        "vocabulary-requirement": ("SchemaViolation", "vocabulary-requirement"),
        "depth-limit": ("LimitExceeded", None),
        "node-count-limit": ("LimitExceeded", None),
        "context-missing": ("SchemaViolation", "context-declaration"),
        "state-mismatch": ("SchemaViolation", "state-declaration"),
        "value-size": ("LimitExceeded", None),
        "id-duplicate": ("SchemaViolation", "id-uniqueness"),
        "construct": ("SchemaViolation", "construct"),
        "unknown-type": ("UnknownComponentType", None),
        "undeclared-property": ("SchemaViolation", "undeclared-property"),
        "property-type": ("SchemaViolation", "property-type"),
        "expression": ("SchemaViolation", "expression"),
        "contract-feature": ("SchemaViolation", "contract-feature"),
        "children": ("SchemaViolation", "children"),
        "event-binding": ("SchemaViolation", "event-binding"),
        "action-encoding": ("SchemaViolation", "action-encoding"),
        "action-capability": ("SchemaViolation", "action-capability"),
        "no-handler": ("SchemaViolation", "action-handler"),
    }

    def test_every_injector_is_in_the_catalog_and_plants_its_defect(self):
        names = [name for name, *_ in gov.ENVELOPE] + [name for name, _ in gov.NODE]
        self.assertEqual(sorted(names), sorted(self.INTENDED))
        for name, (error_type, rule) in self.INTENDED.items():
            error = committed(f"{name}-alone")["expect"]["error"]
            self.assertEqual(error["type"], error_type, name)
            if rule is not None:
                self.assertEqual(error["rule"], rule, name)


class Order(unittest.TestCase):
    """The document model's order, as the suite pins it."""

    def test_the_earlier_sibling_wins_whatever_the_rules(self):
        # Any pair of walk-time defects in both orders: the error is
        # anchored to node a, or to the id it was given, never to node b.
        # The missing handler is planted on a node but raised after the
        # walk, so a walk-time defect on either sibling precedes it.
        walk = [name for name, _ in gov.NODE if name != "no-handler"]
        for first in walk:
            for second in walk:
                if first == second:
                    continue
                error = committed(f"{first}-then-{second}")["expect"]["error"]
                self.assertIn(error.get("node"), ("a", "root", "a-child"),
                              f"{first}-then-{second} anchored to {error.get('node')}")

    def test_the_envelope_precedes_the_walk_and_the_walk_precedes_data(self):
        self.assertEqual(committed("unsupported-version-and-construct")["expect"]["error"]["type"],
                         "UnsupportedVersion")
        self.assertEqual(committed("depth-limit-and-expression")["expect"]["error"]["type"],
                         "LimitExceeded")
        self.assertEqual(committed("context-missing-and-expression")["expect"]["error"]["rule"],
                         "expression")
        # The handler check sits between the walk and the data checks: a
        # walk-time defect on the later sibling still precedes it.
        self.assertEqual(committed("context-missing-and-no-handler")["expect"]["error"]["rule"],
                         "action-handler")
        self.assertEqual(committed("no-handler-then-construct")["expect"]["error"]["rule"],
                         "construct")

    def test_the_suite_is_large_enough_to_be_exhaustive(self):
        self.assertGreater(len(list(COMMITTED.glob("gen-order-*.json"))), 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
