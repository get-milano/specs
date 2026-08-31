#!/usr/bin/env python3
"""Tests for tools/generate_typing_vectors.py.

The tool writes the typing-rule suite by enumerating a small grammar and
running every (expression, target) pair through the reference gate. The
same two properties as the numeric suite carry the design: the run is
deterministic, so a regenerated suite is a reviewable diff, and the
committed files are exactly what today's tool produces. There is no seed
here; the grammar is the whole input.

Run: python3 tools/test_generate_typing_vectors.py
"""

import json
import re
import tempfile
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent

sys.path.insert(0, str(TOOLS))

import generate_typing_vectors as gtv  # noqa: E402

COMMITTED = ROOT / "conformance" / "generated-typing"


def committed_vectors():
    for path in sorted(COMMITTED.glob("gen-typing-*.json")):
        yield path.name, json.loads(path.read_text())


class RegeneratesTheCommittedSuite(unittest.TestCase):
    """The committed files are what the tool writes today, byte for byte."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        suite = Path(cls.directory.name) / "conformance" / "generated-typing"
        original_root, original_suite = gtv.ROOT, gtv.SUITE
        gtv.ROOT, gtv.SUITE = Path(cls.directory.name), suite
        try:
            gtv.main()
        finally:
            gtv.ROOT, gtv.SUITE = original_root, original_suite
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

    def test_the_committed_vocabulary_matches_the_tool_s(self):
        committed = json.loads((COMMITTED / "vocabulary.json").read_text())
        self.assertEqual(committed, gtv.VOCABULARY)


class Coverage(unittest.TestCase):
    """Every family pins both directions, and the two regressions that
    motivated the suite are present in it."""

    def test_every_family_accepts_and_rejects(self):
        # A family with only rejections would mean the pool never composes
        # a valid expression; one with only acceptances never exercises the
        # gate's refusal. Either is a pool that drifted from its rule.
        seen = {}
        for name, _ in committed_vectors():
            family, kind = re.match(r"gen-typing-([a-z]+)-(accept|reject)-", name).groups()
            seen.setdefault(family, set()).add(kind)
        families = [family for family, _ in gtv.families()]
        self.assertEqual(sorted(seen), sorted(families))
        for family, kinds in seen.items():
            self.assertEqual(kinds, {"accept", "reject"}, f"{family} is one-sided")

    def find(self, expression, target):
        """The vector carrying this pair, and whether it accepts."""
        for name, vector in committed_vectors():
            for node in vector["document"]["root"]["children"]:
                properties = node["properties"]
                if target in properties and properties[target]["$expr"] == expression:
                    return name, "accept" in name
        self.fail(f"no vector carries {expression!r} in {target}")

    def test_an_optional_branch_beside_a_non_optional_one_is_rejected(self):
        # The TypeScript engine accepted this and typed it `string?` while
        # Swift and Kotlin rejected it; nothing generated the pair. Spec 03:
        # both branches type-check to exactly the same T.
        _, accepted = self.find("$if(state.b, state.sOpt, state.s)", "sOpt")
        self.assertFalse(accepted)

    def test_an_int_expression_in_a_double_position_is_accepted(self):
        # Every engine accepted this and the checker refused it; nothing
        # generated the pair. Spec 03: int is accepted where double is
        # expected and promoted at evaluation.
        _, accepted = self.find("state.i", "d")
        self.assertTrue(accepted)

    def test_a_literal_refines_into_an_enum_position_only_when_a_member(self):
        self.assertTrue(self.find("'a'", "e")[1])
        # An optional operand compares only to null (expression spec,
        # Operators): both directions, and optional beside optional.
        self.assertFalse(self.find("state.sOpt == 'a'", "b")[1])
        self.assertFalse(self.find("state.s == state.sOpt", "b")[1])
        self.assertFalse(self.find("state.sOpt == state.iOpt", "b")[1])
        self.assertTrue(self.find("state.sOpt == null", "b")[1])
        self.assertFalse(self.find("'z'", "e")[1])

    def test_a_promoted_int_is_canonicalized_in_the_view(self):
        # The accepting vector's expectation carries the double the engines
        # produce, not the int the expression evaluated to.
        name, _ = self.find("state.i", "d")
        vector = dict(committed_vectors())[name]
        for node, expected in zip(vector["document"]["root"]["children"],
                                  vector["expect"]["view"]["children"]):
            if node["properties"].get("d", {}).get("$expr") == "state.i":
                self.assertIsInstance(expected["properties"]["d"], float)
                return
        self.fail("the promoted pair was not found in the view")


    def find_in(self, family, expression, target):
        """As find, within one family: the same expression sits in the
        numeric family (accepted, 2.1 documents) and the contract family
        (refused, 1.0 documents)."""
        for name, vector in committed_vectors():
            if not name.startswith(f"gen-typing-{family}-"):
                continue
            for node in vector["document"]["root"]["children"]:
                properties = node["properties"]
                if target in properties and properties[target]["$expr"] == expression:
                    return name, "accept" in name
        self.fail(f"no {family} vector carries {expression!r} in {target}")

    def test_the_numeric_functions_keep_their_types(self):
        # Contract 2.1: abs keeps int or double, the rounding functions take
        # exactly a double, min and max promote like the operators.
        self.assertTrue(self.find_in("numeric", "$abs(state.i)", "i")[1])
        self.assertTrue(self.find_in("numeric", "$abs(state.d)", "d")[1])
        self.assertFalse(self.find_in("numeric", "$abs(state.s)", "d")[1])
        self.assertFalse(self.find_in("numeric", "$round(state.i)", "d")[1])
        self.assertTrue(self.find_in("numeric", "$round(state.d)", "d")[1])
        self.assertTrue(self.find_in("numeric", "$min(state.i, state.d)", "d")[1])
        self.assertTrue(self.find_in("numeric", "$max(state.i, 1)", "i")[1])
        self.assertFalse(self.find_in("numeric", "$min(state.i)", "d")[1])
        self.assertFalse(self.find_in("numeric", "$min(state.i, state.iOpt)", "d")[1])

    def test_a_2_1_function_is_refused_by_name_in_a_1_0_document(self):
        self.assertTrue(self.find_in("numeric", "$abs(state.i)", "d")[1])
        self.assertFalse(self.find_in("contract", "$abs(state.i)", "d")[1])
        vectors = dict(committed_vectors())
        functions = {"$abs", "$min", "$max", "$floor", "$ceil", "$round"}
        gated = [v for n, v in vectors.items()
                 if n.startswith("gen-typing-contract-reject")
                 and v["document"]["root"]["children"][0]["properties"]
                 [next(iter(v["document"]["root"]["children"][0]["properties"]))]["$expr"]
                 .split("(")[0] in functions]
        self.assertEqual(len(gated), 10, "every 2.1 function over both numeric operands")
        for vector in gated:
            self.assertEqual(vector["document"]["version"], "1.0.0")
            self.assertEqual(vector["expect"]["error"]["rule"], "contract-feature")
            self.assertEqual(vector["expect"]["error"]["expected"], "2.1")
            self.assertIn(vector["expect"]["error"]["found"], functions)
        accepted_1_0 = [v for n, v in vectors.items() if n.startswith("gen-typing-contract-accept")]
        self.assertTrue(accepted_1_0, "1.0's own functions still build beside the refusals")


class Shape(unittest.TestCase):
    """What one vector claims and how it is packed."""

    def test_rejections_carry_one_expression_each(self):
        # The gate stops at the first defect, so a rejecting document can
        # pin exactly one.
        for name, vector in committed_vectors():
            if "reject" in name:
                self.assertEqual(len(vector["document"]["root"]["children"]), 1, name)
                self.assertIn("error", vector["expect"])

    def test_acceptances_are_packed_and_name_every_node(self):
        for name, vector in committed_vectors():
            if "accept" in name:
                children = vector["document"]["root"]["children"]
                self.assertLessEqual(len(children), gtv.PACK, name)
                for node in children:
                    self.assertIn(f"{node['id']}:", vector["description"], name)

    def test_documents_declare_only_the_state_they_read(self):
        for name, vector in committed_vectors():
            text = json.dumps(vector["document"]["root"])
            declared = set(vector["document"].get("state", {}))
            read = set(re.findall(r"state\.([A-Za-z][A-Za-z0-9_]*)", text)) & set(gtv.STATE)
            self.assertEqual(declared, read, name)

    def test_the_suite_is_large_enough_to_be_meaningful(self):
        self.assertGreater(sum(1 for _ in committed_vectors()), 300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
