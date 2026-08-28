#!/usr/bin/env python3
"""Tests for tools/reference_check.py.

The checker is the oracle: every vector's expectation was produced or
confirmed by it, the generated numeric suite is written from it, and every
engine is measured against the vectors it blesses. So an error here does
not fail loudly, it becomes the definition of correct. Nothing else in the
repository can catch that, because everything else agrees with it by
construction.

These tests therefore assert against the prose, not against the checker's
own output: each one names the rule in specs 00 to 03 that fixes the
answer. Where the checker is deliberately lenient, the leniency is pinned
too, so that a future tightening is a decision rather than an accident.

Run: python3 tools/test_reference_check.py
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
TOOL = TOOLS / "reference_check.py"

sys.path.insert(0, str(TOOLS))

import reference_check as rc  # noqa: E402

VOCABULARY = {
    "milano": "1.0.0",
    "name": "checker",
    "version": "1.0.0",
    "components": {
        "Text": {"properties": {"text": "string"}},
        "Strict": {"strict": True, "properties": {"text": "string"}},
        "Column": {"children": True},
    },
    "actions": {"go": {"parameters": {"url": "string"}}},
}


def document(expression, **envelope):
    """A one-node document whose only property is the expression."""
    doc = {
        "version": "1.0.0",
        "root": {
            "type": "Text",
            "id": "r",
            "properties": {"text": {"$expr": expression}},
        },
    }
    doc.update(envelope)
    return doc


class GateHarness(unittest.TestCase):
    """Shared helpers: build a document, or capture how it was refused."""

    vocabulary = VOCABULARY

    def build(self, doc, policy="fail", context=None, state=None, vocabulary=None):
        gate = rc.ReferenceGate(vocabulary or self.vocabulary, policy)
        resolved, _ = gate.build({
            "name": "test", "document": doc,
            "context": context or {}, "state": state or {},
        })
        return resolved, gate.occurrences

    def refusal(self, doc, policy="fail", context=None, state=None, vocabulary=None):
        """The typed error fields, or a failure if the gate accepted."""
        try:
            self.build(doc, policy, context, state, vocabulary)
        except rc.GateError as error:
            return error.fields
        self.fail("the gate accepted a document it should have refused")

    def value(self, expression, **kwargs):
        """The resolved `text` of the one-node document."""
        resolved, _ = self.build(document(expression), **kwargs)
        return resolved["properties"]["text"]

    def occurrences(self, expression, **kwargs):
        _, occurrences = self.build(document(expression), **kwargs)
        return occurrences


class ExpressionGrammar(GateHarness):
    """Spec 03: the grammar, precedence, and what is not in the language."""

    def test_multiplication_binds_tighter_than_addition(self):
        self.assertEqual(self.value("str(1 + 2 * 3)"), "7")
        self.assertEqual(self.value("str((1 + 2) * 3)"), "9")

    def test_subtraction_is_left_associative(self):
        # Right association would give 3.
        self.assertEqual(self.value("str(2 - 3 - 4)"), "-5")

    def test_boolean_and_comparison_operators(self):
        self.assertEqual(self.value("str(1 < 2)"), "true")
        self.assertEqual(self.value("str(true && false)"), "false")
        self.assertEqual(self.value("str(true || false)"), "true")
        self.assertEqual(self.value("str(!true)"), "false")

    def test_no_scientific_literals(self):
        # The grammar has no exponent form: `1e300` tokenizes as 1 followed
        # by an identifier, which is a parse error rather than a number.
        # Pinned because the numeric generator composes literals by hand and
        # would silently produce garbage if this ever became legal.
        fields = self.refusal(document("str(1e300)"))
        self.assertEqual(fields["rule"], "expression")

    def test_unterminated_string_is_a_parse_error(self):
        with self.assertRaises(rc.ExprError):
            rc.Parser(rc.tokenize("concat('a")).parse()

    def test_trailing_tokens_are_a_parse_error(self):
        with self.assertRaises(rc.ExprError):
            rc.Parser(rc.tokenize("1 2")).parse()

    def test_only_spaces_and_tabs_separate_tokens(self):
        # Spec 03 grammar: "Whitespace (spaces and tabs)". The wider Unicode
        # table belongs to `trim`, not to tokenization, and conflating the
        # two would make an engine accept expressions the grammar does not.
        self.assertEqual(len(rc.tokenize("1 +\t2")), 3)
        with self.assertRaises(rc.ExprError):
            rc.tokenize("1 + 2")

    def test_trim_removes_every_code_point_in_the_shared_table(self):
        # Spec 03: trim removes exactly the characters in an explicit table
        # both runtimes share, because platform helpers disagree about the
        # exotic ones. Each is exercised individually so a gap names itself.
        for code_point in sorted(rc.WHITE_SPACE):
            with self.subTest(code_point=hex(ord(code_point))):
                self.assertEqual(
                    self.value(f"trim('{code_point}x{code_point}')"), "x",
                    f"{code_point!r} survived trim")


class NumericSemantics(GateHarness):
    """Spec 03: 64-bit integers, IEEE 754 doubles, and total evaluation."""

    def test_integer_addition_wraps_at_the_int64_boundary(self):
        self.assertEqual(self.value("str(9223372036854775807 + 1)"),
                         "-9223372036854775808")

    def test_integer_division_truncates_toward_zero(self):
        self.assertEqual(self.value("str(3 / 2)"), "1")
        self.assertEqual(self.value("str((0 - 3) / 2)"), "-1")

    def test_modulo_takes_the_sign_of_the_dividend(self):
        self.assertEqual(self.value("str((0 - 7) % 3)"), "-1")
        self.assertEqual(self.value("str(7 % (0 - 3))"), "1")

    def test_integer_division_by_zero_yields_zero_and_is_reported(self):
        # Total evaluation: it cannot throw, so it must both define a result
        # and tell the host it happened.
        self.assertEqual(self.value("str(1 / 0)"), "0")
        self.assertEqual(self.occurrences("str(1 / 0)"),
                         [{"kind": "divisionByZero", "node": "r", "name": "text"}])

    def test_integer_modulo_by_zero_yields_zero_and_is_reported(self):
        self.assertEqual(self.value("str(7 % 0)"), "0")
        self.assertEqual(self.occurrences("str(7 % 0)"),
                         [{"kind": "divisionByZero", "node": "r", "name": "text"}])

    def test_double_division_by_zero_follows_ieee_754(self):
        self.assertEqual(self.value("str(0.0 / 0.0)"), "nan")
        self.assertEqual(self.value("str(1.0 / 0.0)"), "inf")
        self.assertEqual(self.value("str((0.0 - 1.0) / 0.0)"), "-inf")

    def test_double_modulo_with_non_finite_operands_follows_ieee_754(self):
        # An infinite dividend or a zero divisor is NaN; an infinite divisor
        # leaves the dividend alone. math.fmod raises on the first two, and
        # the checker used to crash where every engine answers nan.
        self.assertEqual(self.value("str((1.0 / 0.0) % 2.0)"), "nan")
        self.assertEqual(self.value("str(((0.0 - 1.0) / 0.0) % 2.0)"), "nan")
        self.assertEqual(self.value("str(2.0 % 0.0)"), "nan")
        self.assertEqual(self.value("str((0.0 / 0.0) % 2.0)"), "nan")
        self.assertEqual(self.value("str(2.0 % (1.0 / 0.0))"), "2.0")
        self.assertEqual(self.value("str((0.0 - 2.0) % (1.0 / 0.0))"), "-2.0")
        self.assertEqual(self.occurrences("str((1.0 / 0.0) % 2.0)"), [])

    def test_double_division_by_zero_is_not_reported(self):
        # Only the integer case is an occurrence: the double case has an
        # IEEE answer, so there is nothing to warn about.
        self.assertEqual(self.occurrences("str(1.0 / 0.0)"), [])

    def test_nan_compares_unequal_to_itself(self):
        self.assertEqual(self.value("str((0.0 / 0.0) == (0.0 / 0.0))"), "false")
        self.assertEqual(self.value("str((0.0 / 0.0) != (0.0 / 0.0))"), "true")

    def test_signed_zero_is_preserved(self):
        self.assertEqual(self.value("str(-(0.0))"), "-0.0")

    def test_int_conversion_truncates_toward_zero(self):
        self.assertEqual(self.value("str(int(1.9))"), "1")
        self.assertEqual(self.value("str(int(-(1.9)))"), "-1")

    def test_int_conversion_saturates_and_is_reported(self):
        self.assertEqual(self.value("str(int(9223372036854775807.0 * 2.0))"),
                         "9223372036854775807")
        self.assertEqual(self.occurrences("str(int(9223372036854775807.0 * 2.0))"),
                         [{"kind": "saturation", "node": "r", "name": "text"}])

    def test_int_of_nan_is_zero_and_reported_as_saturation(self):
        self.assertEqual(self.value("str(int(0.0 / 0.0))"), "0")
        self.assertEqual(self.occurrences("str(int(0.0 / 0.0))"),
                         [{"kind": "saturation", "node": "r", "name": "text"}])

    def test_double_conversion_rounds_at_the_precision_cliff(self):
        # 2^53 + 1 has no binary64 representation; it rounds to 2^53.
        self.assertEqual(self.value("str(double(9007199254740993))"),
                         "9007199254740992.0")

    def test_mixed_comparison_promotes_the_integer(self):
        self.assertEqual(self.value("str(1 == 1.0)"), "true")

    def test_wrap64_is_two_s_complement(self):
        self.assertEqual(rc.wrap64(rc.INT_MAX + 1), rc.INT_MIN)
        self.assertEqual(rc.wrap64(rc.INT_MIN - 1), rc.INT_MAX)
        self.assertEqual(rc.wrap64(0), 0)


class DoubleFormatting(GateHarness):
    """Spec 03: str() on a double, a Milano format rather than the host's."""

    def test_integral_values_keep_one_fractional_digit(self):
        self.assertEqual(self.value("str(5.0)"), "5.0")

    def test_plain_decimal_up_to_the_upper_exponent_edge(self):
        # The window is a normalized exponent in [-4, 15]; 1e15 is inside.
        self.assertEqual(self.value("str(1000000000000000.0)"),
                         "1000000000000000.0")

    def test_scientific_notation_above_the_upper_edge(self):
        self.assertEqual(self.value("str(10000000000000000.0)"), "1e16")

    def test_plain_decimal_down_to_the_lower_exponent_edge(self):
        self.assertEqual(self.value("str(0.0001)"), "0.0001")

    def test_scientific_notation_below_the_lower_edge(self):
        self.assertEqual(self.value("str(0.00001)"), "1e-5")

    def test_non_finite_values_have_fixed_spellings(self):
        # Not Python's 'inf'/'nan' by coincidence: the spec fixes these, and
        # a platform default would give "Infinity" or "NaN" elsewhere.
        self.assertEqual(rc.format_scalar(float("nan")), "nan")
        self.assertEqual(rc.format_scalar(float("inf")), "inf")
        self.assertEqual(rc.format_scalar(float("-inf")), "-inf")

    def test_booleans_are_lowercase(self):
        self.assertEqual(self.value("str(true)"), "true")
        self.assertEqual(self.value("str(false)"), "false")


class TypeChecking(GateHarness):
    """Spec 03: the gate rejects statically, so evaluation is total."""

    def test_unknown_identifier_is_refused(self):
        self.assertEqual(self.refusal(document("str(nope)"))["rule"], "expression")

    def test_wrong_argument_count_is_refused(self):
        self.assertEqual(self.refusal(document("concat('a')"))["rule"], "expression")

    def test_mismatched_operand_types_are_refused(self):
        self.assertEqual(self.refusal(document("str('a' + 1)"))["rule"], "expression")

    def test_coalescing_resolves_an_optional(self):
        doc = document("str(state.maybe ?? 5)", state={"maybe": "int?"})
        self.assertEqual(self.build(doc)[0]["properties"]["text"], "5")

    def test_coalescing_a_non_optional_is_refused(self):
        # `??` exists to discharge optionality; applying it where there is
        # none is a producer mistake, not a harmless no-op.
        doc = document("str(state.n ?? 5)", state={"n": "int"})
        self.assertEqual(self.refusal(doc)["rule"], "expression")

    def test_null_compares_only_to_an_optional_operand(self):
        # Spec 03: optionals are comparable to null. A non-optional beside
        # null, or null beside null, could only ever be constant and is
        # refused. Every engine did; the checker let the null literal's own
        # optionality stand in for the other operand's.
        doc = document("str(state.maybe == null)", state={"maybe": "string?"})
        resolved, _ = self.build(doc, state={"maybe": None})
        self.assertEqual(resolved["properties"]["text"], "true")
        for expression in ("state.n == null", "null == state.n", "null == null", "'x' != null"):
            with self.subTest(expression=expression):
                doc = document(f"str({expression})", state={"n": "string"})
                self.assertEqual(self.refusal(doc)["rule"], "expression")

    def test_enum_comparison_against_a_non_member_is_refused(self):
        doc = document("str(state.role == 'nope')",
                       state={"role": {"enum": ["a", "b"]}})
        self.assertEqual(self.refusal(doc)["rule"], "expression")

    def test_enum_comparison_against_a_member_is_accepted(self):
        doc = document("str(state.role == 'a')",
                       state={"role": {"enum": ["a", "b"]}})
        resolved, _ = self.build(doc, state={"role": "a"})
        self.assertEqual(resolved["properties"]["text"], "true")

    def test_if_branches_must_agree_on_optionality(self):
        # Spec 03: exactly the same T, optionality included. The null
        # literal is the only way an if makes an optional; a T? branch is
        # resolved with ?? before it can sit beside a T one. Swift and
        # Kotlin always refused this; the checker used to widen instead.
        doc = document("if(true, state.maybe, 'x') ?? ''",
                       state={"maybe": "string?"})
        self.assertEqual(self.refusal(doc)["rule"], "expression")
        resolved = document("if(true, state.maybe ?? 'y', 'x')",
                            state={"maybe": "string?"})
        self.assertEqual(
            self.build(resolved, state={"maybe": None})[0]["properties"]["text"],
            "y")

    def test_an_int_expression_is_promoted_where_a_double_is_declared(self):
        # Spec 03: accepted at every declared position and promoted at
        # evaluation, as an int literal or data value is. Every engine did
        # this; the checker refused it.
        vocabulary = {
            "milano": "1.0.0", "name": "gauge", "version": "1.0.0",
            "components": {"Gauge": {"properties": {"ratio": "double"}}},
        }
        doc = {"version": "1.0.0", "state": {"count": "int"},
               "root": {"type": "Gauge", "id": "g",
                        "properties": {"ratio": {"$expr": "state.count * 2"}}}}
        resolved, _ = self.build(doc, state={"count": 3}, vocabulary=vocabulary)
        ratio = resolved["properties"]["ratio"]
        self.assertIsInstance(ratio, float)
        self.assertEqual(ratio, 6.0)

    def test_a_double_expression_is_refused_where_an_int_is_declared(self):
        vocabulary = {
            "milano": "1.0.0", "name": "gauge", "version": "1.0.0",
            "components": {"Gauge": {"properties": {"count": "int"}}},
        }
        doc = {"version": "1.0.0",
               "root": {"type": "Gauge", "id": "g",
                        "properties": {"count": {"$expr": "1.5 * 2.0"}}}}
        self.assertEqual(self.refusal(doc, vocabulary=vocabulary)["rule"],
                         "expression")


class GateValidation(GateHarness):
    """Spec 01: the fixed validation order and its typed refusals."""

    def test_unsupported_versions_are_refused_with_the_ranges(self):
        # Foundations, Versioning: an unknown major, or a minor above the
        # ceiling of a known one; the patch never matters.
        for declared in ("3.0.0", "2.1.0", "1.1.0"):
            fields = self.refusal(document("str(1)", version=declared))
            self.assertEqual(fields["type"], "UnsupportedVersion", declared)
            self.assertEqual(fields["declared"], declared)
            self.assertEqual(fields["supported"], ["1.0", "2.0"])
        for declared in ("1.0.0", "2.0.0", "2.0.9"):
            self.build(document("str(1)", version=declared))

    def test_unknown_component_type_fails_under_the_fail_policy(self):
        doc = {"version": "1.0.0", "root": {"type": "Nope", "id": "r"}}
        fields = self.refusal(doc)
        self.assertEqual(fields["type"], "UnknownComponentType")
        self.assertEqual(fields["unknownType"], "Nope")

    def test_unknown_component_type_is_skipped_under_the_skip_policy(self):
        doc = {"version": "1.0.0", "root": {
            "type": "Column", "children": [{"type": "Nope", "id": "u"}]}}
        resolved, occurrences = self.build(doc, policy="skip")
        self.assertNotIn("children", resolved)
        self.assertEqual(occurrences, [{"kind": "unknownTypeSkipped", "node": "u", "name": "Nope"}])

    def test_unknown_component_type_becomes_a_placeholder_under_that_policy(self):
        doc = {"version": "1.0.0", "root": {
            "type": "Column", "children": [{"type": "Nope", "id": "u"}]}}
        resolved, occurrences = self.build(doc, policy="placeholder")
        self.assertTrue(resolved["children"][0]["placeholder"])
        self.assertEqual(occurrences, [{"kind": "unknownTypePlaceholder", "node": "u", "name": "Nope"}])

    def test_reserved_type_prefix_is_refused(self):
        doc = {"version": "1.0.0", "root": {"type": "$Nope", "id": "r"}}
        self.assertEqual(self.refusal(doc)["rule"], "construct")

    def test_an_empty_or_non_string_id_is_malformed(self):
        # Spec 01, node envelope: an id, when present, is a non-empty
        # string. The checker used to treat "" as absent and fall back to
        # the path, while every engine kept "" as the reference.
        for bad in ("", 5):
            doc = {"version": "1.0.0",
                   "root": {"type": "Text", "id": bad, "properties": {"text": "x"}}}
            self.assertEqual(self.refusal(doc)["type"], "MalformedDocument")

    def test_duplicate_ids_are_refused(self):
        doc = {"version": "1.0.0", "root": {
            "type": "Column", "id": "same",
            "children": [{"type": "Text", "id": "same",
                          "properties": {"text": "x"}}]}}
        fields = self.refusal(doc)
        self.assertEqual(fields["rule"], "id-uniqueness")
        self.assertEqual(fields["found"], "same")

    def test_declaration_keys_follow_the_ascii_identifier_grammar(self):
        # Vocabulary schema spec, Naming: a letter is an ASCII letter. The
        # checker used str.isalpha, which let a Unicode letter through where
        # every engine and the schemas refuse it.
        doc = document("str(1)", state={"caf\u00e9": "int"})
        fields = self.refusal(doc)
        self.assertEqual(fields["rule"], "state-declaration")
        self.assertEqual(fields["found"], "caf\u00e9")
        digits = document("str(1)", context={"a\u0663": "string"})
        self.assertEqual(self.refusal(digits)["rule"], "context-declaration")
        self.assertTrue(rc._identifier("a_1"))
        self.assertFalse(rc._identifier("_a"))
        self.assertFalse(rc._identifier(""))

    def test_a_literal_of_the_wrong_type_is_refused(self):
        doc = {"version": "1.0.0", "root": {
            "type": "Text", "id": "r", "properties": {"text": 5}}}
        fields = self.refusal(doc)
        self.assertEqual(fields["rule"], "property-type")
        self.assertEqual((fields["expected"], fields["found"]), ("string", "int"))

    def test_children_on_a_childless_type_are_refused(self):
        doc = {"version": "1.0.0", "root": {
            "type": "Text", "id": "r", "properties": {"text": "x"},
            "children": [{"type": "Text", "id": "c",
                          "properties": {"text": "y"}}]}}
        self.assertEqual(self.refusal(doc)["rule"], "children")

    def test_undeclared_properties_are_ignored_and_reported_by_default(self):
        # Foundations: tolerance is the default so a vocabulary can grow
        # without breaking older documents. The value is dropped from the
        # resolved node rather than passed through to renderers.
        doc = {"version": "1.0.0", "root": {
            "type": "Text", "id": "r",
            "properties": {"text": "x", "extra": 1}}}
        resolved, occurrences = self.build(doc)
        self.assertEqual(resolved["properties"], {"text": "x"})
        self.assertEqual(occurrences, [{"kind": "undeclaredProperty", "node": "r", "name": "extra"}])

    def test_undeclared_properties_are_refused_on_a_strict_type(self):
        doc = {"version": "1.0.0", "root": {
            "type": "Strict", "id": "r",
            "properties": {"text": "x", "extra": 1}}}
        fields = self.refusal(doc)
        self.assertEqual(fields["rule"], "undeclared-property")
        self.assertEqual(fields["found"], "extra")

    def test_an_omitted_declared_property_is_accepted(self):
        # Pinned leniency, not an endorsement: the spec type-checks declared
        # properties that are present and says nothing about presence, so a
        # node may omit one and the resolved node simply lacks it. Renderers
        # and generated bindings that treat a non-optional declaration as a
        # guarantee of presence are relying on more than the gate promises.
        doc = {"version": "1.0.0", "root": {"type": "Text", "id": "r"}}
        resolved, occurrences = self.build(doc)
        self.assertNotIn("properties", resolved)
        self.assertEqual(occurrences, [])


class ResourceLimits(GateHarness):
    """Spec 01: the limits, and that each is reported as itself."""

    def nested(self, depth):
        node = {"type": "Text", "properties": {"text": "x"}}
        for _ in range(depth):
            node = {"type": "Column", "children": [node]}
        return {"version": "1.0.0", "root": node}

    def test_a_tree_within_the_depth_limit_is_accepted(self):
        self.build(self.nested(rc.MAX_TREE_DEPTH - 2))

    def test_tree_depth_beyond_the_limit_is_refused(self):
        fields = self.refusal(self.nested(rc.MAX_TREE_DEPTH + 2))
        self.assertEqual(fields["type"], "LimitExceeded")
        self.assertEqual(fields["limit"], "maxTreeDepth")
        self.assertEqual(fields["value"], rc.MAX_TREE_DEPTH)

    def test_node_count_beyond_the_limit_is_refused(self):
        doc = {"version": "1.0.0", "root": {
            "type": "Column",
            "children": [{"type": "Text", "properties": {"text": "x"}}
                         for _ in range(rc.MAX_NODE_COUNT + 5)]}}
        fields = self.refusal(doc)
        self.assertEqual(fields["limit"], "maxNodeCount")

    def test_expression_length_beyond_the_limit_is_refused(self):
        long_expression = "str(" + "1 + " * 300 + "1)"
        self.assertGreater(len(long_expression), rc.MAX_EXPRESSION_LENGTH)
        fields = self.refusal(document(long_expression))
        self.assertEqual(fields["limit"], "maxExpressionLength")


class VocabularyRequirement(GateHarness):
    """Spec 01 step 3: the producer's opt-in guard for staggered rollouts."""

    def test_a_matching_name_and_no_minimum_is_accepted(self):
        self.build(document("str(1)", vocabulary={"name": "checker"}))

    def test_a_different_vocabulary_name_is_refused(self):
        fields = self.refusal(document("str(1)", vocabulary={"name": "other"}))
        self.assertEqual(fields["rule"], "vocabulary-requirement")
        self.assertEqual((fields["expected"], fields["found"]), ("other", "checker"))

    def test_a_minimum_above_the_engine_s_version_is_refused(self):
        doc = document("str(1)", vocabulary={"name": "checker", "min": "2.0.0"})
        fields = self.refusal(doc)
        self.assertEqual(fields["expected"], ">=2.0.0")

    def test_a_minimum_at_or_below_the_engine_s_version_is_accepted(self):
        self.build(document("str(1)",
                            vocabulary={"name": "checker", "min": "1.0.0"}))


class DataCrossChecks(GateHarness):
    """Spec 01 step 6: declarations versus what the host actually supplied."""

    def test_a_missing_context_key_is_refused(self):
        doc = document("context.who", context={"who": "string"})
        fields = self.refusal(doc)
        self.assertEqual(fields["rule"], "context-declaration")
        self.assertEqual(fields["expected"], "who")

    def test_a_context_value_of_the_wrong_type_is_refused(self):
        doc = document("context.who", context={"who": "string"})
        fields = self.refusal(doc, context={"who": 5})
        self.assertEqual((fields["expected"], fields["found"]), ("string", "int"))

    def test_a_supplied_context_value_reaches_the_resolved_tree(self):
        doc = document("concat('hi ', context.who)", context={"who": "string"})
        resolved, _ = self.build(doc, context={"who": "Ada"})
        self.assertEqual(resolved["properties"]["text"], "hi Ada")

    def test_undeclared_supplied_keys_are_ignored(self):
        # One context source can serve many views, so extra keys are not an
        # error: the document reads only what it declares.
        doc = document("context.who", context={"who": "string"})
        resolved, _ = self.build(doc, context={"who": "Ada", "unused": 1})
        self.assertEqual(resolved["properties"]["text"], "Ada")


class CommandLine(unittest.TestCase):
    """The --document mode producer builds run as a pre-build step."""

    def run_cli(self, document_value, vocabulary=VOCABULARY):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "v.json").write_text(json.dumps(vocabulary))
            (base / "d.json").write_text(json.dumps(document_value))
            return subprocess.run(
                [sys.executable, str(TOOL),
                 "--document", str(base / "d.json"),
                 "--vocabulary", str(base / "v.json")],
                capture_output=True, text=True)

    def test_a_valid_document_exits_zero_and_names_the_vocabulary(self):
        result = self.run_cli(document("str(1)"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("valid against checker@1.0.0", result.stdout)

    def test_a_rejected_document_exits_non_zero_with_the_reason(self):
        result = self.run_cli({"version": "1.0.0",
                               "root": {"type": "Nope", "id": "r"}})
        self.assertEqual(result.returncode, 1)
        self.assertIn("REJECTED", result.stdout)
        self.assertIn("UnknownComponentType", result.stdout)

    def test_occurrences_are_surfaced_on_success(self):
        # A document that builds but reports something has to say so: this
        # is the only signal a producer's build step gets.
        result = self.run_cli(document("str(1 / 0)"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("divisionByZero", result.stdout)


class StepLinting(unittest.TestCase):
    """Vectors with steps: statically linted here, executed by the engines."""

    def vector(self, **overrides):
        vector = {
            "name": "stepped",
            "document": {
                "version": "1.0.0",
                "state": {"n": "int"},
                "root": {
                    "type": "Text", "id": "r",
                    "properties": {"text": {"$expr": "str(state.n)"}},
                    "on": {"tap": [{"action": "$set", "key": "n",
                                    "value": {"$expr": "1"}}]},
                },
            },
            "state": {"n": 0},
            "steps": [{"event": {"node": "r", "name": "tap"}}],
            "expect": {
                "view": {"type": "Text", "reference": "r",
                         "properties": {"text": "1"}},
                "dispatched": [],
                "occurrences": [],
            },
        }
        vector.update(overrides)
        return vector

    @property
    def vocabulary(self):
        return {
            "milano": "1.0.0", "name": "stepper", "version": "1.0.0",
            "components": {"Text": {"properties": {"text": "string"},
                                    "events": {"tap": None}}},
            "actions": {},
        }

    def test_a_well_formed_step_vector_lints_clean(self):
        problems = rc.StepLinter(self.vector(), self.vocabulary).lint()
        self.assertEqual(problems, [])

    def test_a_set_of_an_undeclared_state_key_is_reported(self):
        vector = self.vector()
        vector["document"]["root"]["on"]["tap"][0]["key"] = "missing"
        problems = rc.StepLinter(vector, self.vocabulary).lint()
        self.assertTrue(problems, "an undeclared $set target linted clean")

    def test_a_binding_for_an_undeclared_event_is_reported(self):
        vector = self.vector()
        vector["document"]["root"]["on"] = {
            "nosuch": [{"action": "$set", "key": "n", "value": {"$expr": "1"}}]}
        problems = rc.StepLinter(vector, self.vocabulary).lint()
        self.assertTrue(problems, "an undeclared event binding linted clean")


class AgainstTheRepository(unittest.TestCase):
    """The committed suite, checked end to end by the tool's own main."""

    def test_every_committed_vector_passes_the_checker(self):
        result = subprocess.run([sys.executable, str(TOOL)],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        self.assertIn("vectors checked", result.stdout)

    def test_the_suite_is_large_enough_to_be_meaningful(self):
        # A checker that silently stopped finding vectors would still exit
        # zero above, so the count is asserted rather than assumed.
        result = subprocess.run([sys.executable, str(TOOL)],
                                cwd=ROOT, capture_output=True, text=True)
        checked = int(result.stdout.split("reference check: ")[1].split()[0])
        self.assertGreater(checked, 200, result.stdout.splitlines()[0])



class ValueSizeLimit(GateHarness):
    """Document model, Resource limits: the value size limit applies to
    every value entering state or context, at the gate and at runtime;
    the size counts scalars as one, strings per Unicode scalar, and
    arrays and records as one plus their contents."""

    def gate(self, limits):
        return rc.ReferenceGate(self.vocabulary, "fail", None, limits)

    def test_the_size_metric(self):
        self.assertEqual(rc.value_size(None), 1)
        self.assertEqual(rc.value_size(True), 1)
        self.assertEqual(rc.value_size(7), 1)
        self.assertEqual(rc.value_size(2.5), 1)
        self.assertEqual(rc.value_size(""), 0)
        # Scalars, never UTF-16 units: an emoji is one.
        self.assertEqual(rc.value_size("abcdefg\U0001F600"), 8)
        self.assertEqual(rc.value_size([]), 1)
        self.assertEqual(rc.value_size(["ab", "cd"]), 5)
        self.assertEqual(rc.value_size({"a": [1, 2], "b": "xyz"}), 1 + 3 + 3)

    def test_the_default_is_the_document_model_default(self):
        self.assertEqual(rc.DEFAULT_LIMITS["maxValueSize"], 65_536)
        self.assertEqual(self.gate(None).limits["maxValueSize"], 65_536)

    def test_an_initial_state_value_past_the_limit_is_a_limit_error(self):
        doc = document("state.label", state={"label": "string"})
        with self.assertRaises(rc.GateError) as caught:
            self.gate({"maxValueSize": 8}).build(
                {"name": "t", "document": doc, "context": {}, "state": {"label": "nine char"}})
        self.assertEqual(caught.exception.fields,
                         {"type": "LimitExceeded", "limit": "maxValueSize",
                          "value": 8, "actual": 9})

    def test_a_context_value_past_the_limit_is_a_limit_error(self):
        doc = document("str(length(context.tags))", context={"tags": {"array": "string"}})
        with self.assertRaises(rc.GateError) as caught:
            self.gate({"maxValueSize": 8}).build(
                {"name": "t", "document": doc, "context": {"tags": ["ab", "cd", "ef", "gh"]},
                 "state": {}})
        self.assertEqual(caught.exception.fields["actual"], 9)

    def test_a_value_exactly_at_the_limit_is_accepted(self):
        doc = document("state.label", state={"label": "string"})
        resolved, _ = self.gate({"maxValueSize": 8}).build(
            {"name": "t", "document": doc, "context": {}, "state": {"label": "abcdefg\U0001F600"}})
        self.assertEqual(resolved["properties"]["text"], "abcdefg\U0001F600")

    def test_every_limit_can_be_overridden_by_name(self):
        doc = {"version": "1.0.0", "root": {"type": "Column", "id": "root", "children": [
            {"type": "Text", "id": "a", "properties": {"text": "a"}},
            {"type": "Text", "id": "b", "properties": {"text": "b"}}]}}
        with self.assertRaises(rc.GateError) as caught:
            self.gate({"maxNodeCount": 2}).build(
                {"name": "t", "document": doc, "context": {}, "state": {}})
        self.assertEqual(caught.exception.fields["limit"], "maxNodeCount")
        self.assertEqual(caught.exception.fields["actual"], 3)
        text = json.dumps(doc)
        with self.assertRaises(rc.GateError) as caught:
            self.gate({"maxDocumentBytes": 10}).build(
                {"name": "t", "documentText": text, "context": {}, "state": {}})
        self.assertEqual(caught.exception.fields["actual"], len(text.encode()))


class SurfaceConfiguration(GateHarness):
    """Builder-level rules the document model pins: a document declaring
    state needs a state data provider, one binding custom actions needs an
    action handler, and metadata is an object."""

    def build_with(self, doc, surface, state=None):
        gate = rc.ReferenceGate(self.vocabulary, "fail", None, None, surface)
        return gate.build({"name": "t", "document": doc, "context": {}, "state": state or {}})

    def test_no_state_data_provider(self):
        doc = document("str(state.n)", state={"n": "int"})
        with self.assertRaises(rc.GateError) as caught:
            self.build_with(doc, {"stateDataProvider": False}, state={"n": 1})
        self.assertEqual(caught.exception.fields,
                         {"type": "SchemaViolation", "rule": "state-declaration",
                          "expected": "state data provider"})
        # With a provider that returns nothing, the omitted value is null and
        # the rule is the value's: the declared type against null.
        with self.assertRaises(rc.GateError) as caught:
            self.build_with(doc, {})
        self.assertEqual(caught.exception.fields["expected"], "int")
        self.assertEqual(caught.exception.fields["found"], "null")

    def test_no_action_handler(self):
        doc = {"version": "1.0.0", "root": {"type": "Text", "id": "r",
               "properties": {"text": "x"},
               "on": {"tap": [{"action": "go", "url": "https://x"}]}}}
        vocabulary = json.loads(json.dumps(self.vocabulary))
        vocabulary["components"]["Text"]["events"] = {"tap": None}
        gate = rc.ReferenceGate(vocabulary, "fail", None, None, {"actionHandler": False})
        with self.assertRaises(rc.GateError) as caught:
            gate.build({"name": "t", "document": doc, "context": {}, "state": {}})
        self.assertEqual(caught.exception.fields,
                         {"type": "SchemaViolation", "rule": "action-handler",
                          "expected": "action handler"})
        # Built-in actions alone need no handler.
        doc["root"]["on"] = {"tap": [{"action": "$sequence", "actions": []}]}
        rc.ReferenceGate(vocabulary, "fail", None, None, {"actionHandler": False}).build(
            {"name": "t", "document": doc, "context": {}, "state": {}})

    def test_metadata_must_be_an_object(self):
        for shape in ([1], "x", 3):
            with self.assertRaises(rc.GateError) as caught:
                self.build_with(document("'x'", metadata=shape), {})
            self.assertEqual(caught.exception.fields["type"], "MalformedDocument")
        self.build_with(document("'x'", metadata={"campaign": "summer"}), {})

    def test_unknown_key_warnings_name_the_object(self):
        doc = document("'x'", vocabulary={"name": "checker", "max": "2.0.0"}, extra=1,
                       state={"n": {"enum": ["a"], "optinal": True}})
        doc["root"]["style"] = {}
        warnings = rc.unknown_key_warnings(doc)
        self.assertEqual(sorted(warnings), sorted([
            "document: unknown top-level key 'extra'",
            "vocabulary: unknown key 'max'",
            "state.n: unknown type descriptor key 'optinal'",
            "root: unknown envelope key 'style'",
        ]))
        self.assertEqual(rc.unknown_key_warnings(document("'x'")), [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
