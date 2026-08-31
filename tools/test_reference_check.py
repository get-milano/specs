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
        self.assertEqual(self.value("$str(1 + 2 * 3)"), "7")
        self.assertEqual(self.value("$str((1 + 2) * 3)"), "9")

    def test_subtraction_is_left_associative(self):
        # Right association would give 3.
        self.assertEqual(self.value("$str(2 - 3 - 4)"), "-5")

    def test_boolean_and_comparison_operators(self):
        self.assertEqual(self.value("$str(1 < 2)"), "true")
        self.assertEqual(self.value("$str(true && false)"), "false")
        self.assertEqual(self.value("$str(true || false)"), "true")
        self.assertEqual(self.value("$str(!true)"), "false")

    def test_no_scientific_literals(self):
        # The grammar has no exponent form: `1e300` tokenizes as 1 followed
        # by an identifier, which is a parse error rather than a number.
        # Pinned because the numeric generator composes literals by hand and
        # would silently produce garbage if this ever became legal.
        fields = self.refusal(document("$str(1e300)"))
        self.assertEqual(fields["rule"], "expression")

    def test_unterminated_string_is_a_parse_error(self):
        with self.assertRaises(rc.ExprError):
            rc.Parser(rc.tokenize("$concat('a")).parse()

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
                    self.value(f"$trim('{code_point}x{code_point}')"), "x",
                    f"{code_point!r} survived trim")


class NumericSemantics(GateHarness):
    """Spec 03: 64-bit integers, IEEE 754 doubles, and total evaluation."""

    def test_integer_addition_wraps_at_the_int64_boundary(self):
        self.assertEqual(self.value("$str(9223372036854775807 + 1)"),
                         "-9223372036854775808")

    def test_integer_division_truncates_toward_zero(self):
        self.assertEqual(self.value("$str(3 / 2)"), "1")
        self.assertEqual(self.value("$str((0 - 3) / 2)"), "-1")

    def test_modulo_takes_the_sign_of_the_dividend(self):
        self.assertEqual(self.value("$str((0 - 7) % 3)"), "-1")
        self.assertEqual(self.value("$str(7 % (0 - 3))"), "1")

    def test_integer_division_by_zero_yields_zero_and_is_reported(self):
        # Total evaluation: it cannot throw, so it must both define a result
        # and tell the host it happened.
        self.assertEqual(self.value("$str(1 / 0)"), "0")
        self.assertEqual(self.occurrences("$str(1 / 0)"),
                         [{"kind": "divisionByZero", "node": "r", "name": "text"}])

    def test_integer_modulo_by_zero_yields_zero_and_is_reported(self):
        self.assertEqual(self.value("$str(7 % 0)"), "0")
        self.assertEqual(self.occurrences("$str(7 % 0)"),
                         [{"kind": "divisionByZero", "node": "r", "name": "text"}])

    def test_double_division_by_zero_follows_ieee_754(self):
        self.assertEqual(self.value("$str(0.0 / 0.0)"), "nan")
        self.assertEqual(self.value("$str(1.0 / 0.0)"), "inf")
        self.assertEqual(self.value("$str((0.0 - 1.0) / 0.0)"), "-inf")

    def test_double_modulo_with_non_finite_operands_follows_ieee_754(self):
        # An infinite dividend or a zero divisor is NaN; an infinite divisor
        # leaves the dividend alone. math.fmod raises on the first two, and
        # the checker used to crash where every engine answers nan.
        self.assertEqual(self.value("$str((1.0 / 0.0) % 2.0)"), "nan")
        self.assertEqual(self.value("$str(((0.0 - 1.0) / 0.0) % 2.0)"), "nan")
        self.assertEqual(self.value("$str(2.0 % 0.0)"), "nan")
        self.assertEqual(self.value("$str((0.0 / 0.0) % 2.0)"), "nan")
        self.assertEqual(self.value("$str(2.0 % (1.0 / 0.0))"), "2.0")
        self.assertEqual(self.value("$str((0.0 - 2.0) % (1.0 / 0.0))"), "-2.0")
        self.assertEqual(self.occurrences("$str((1.0 / 0.0) % 2.0)"), [])

    def test_double_division_by_zero_is_not_reported(self):
        # Only the integer case is an occurrence: the double case has an
        # IEEE answer, so there is nothing to warn about.
        self.assertEqual(self.occurrences("$str(1.0 / 0.0)"), [])

    def test_nan_compares_unequal_to_itself(self):
        self.assertEqual(self.value("$str((0.0 / 0.0) == (0.0 / 0.0))"), "false")
        self.assertEqual(self.value("$str((0.0 / 0.0) != (0.0 / 0.0))"), "true")

    def test_signed_zero_is_preserved(self):
        self.assertEqual(self.value("$str(-(0.0))"), "-0.0")

    def test_int_conversion_truncates_toward_zero(self):
        self.assertEqual(self.value("$str($int(1.9))"), "1")
        self.assertEqual(self.value("$str($int(-(1.9)))"), "-1")

    def test_int_conversion_saturates_and_is_reported(self):
        self.assertEqual(self.value("$str($int(9223372036854775807.0 * 2.0))"),
                         "9223372036854775807")
        self.assertEqual(self.occurrences("$str($int(9223372036854775807.0 * 2.0))"),
                         [{"kind": "saturation", "node": "r", "name": "text"}])

    def test_int_of_nan_is_zero_and_reported_as_saturation(self):
        self.assertEqual(self.value("$str($int(0.0 / 0.0))"), "0")
        self.assertEqual(self.occurrences("$str($int(0.0 / 0.0))"),
                         [{"kind": "saturation", "node": "r", "name": "text"}])

    def test_double_conversion_rounds_at_the_precision_cliff(self):
        # 2^53 + 1 has no binary64 representation; it rounds to 2^53.
        self.assertEqual(self.value("$str($double(9007199254740993))"),
                         "9007199254740992.0")

    def test_mixed_comparison_promotes_the_integer(self):
        self.assertEqual(self.value("$str(1 == 1.0)"), "true")

    def test_wrap64_is_two_s_complement(self):
        self.assertEqual(rc.wrap64(rc.INT_MAX + 1), rc.INT_MIN)
        self.assertEqual(rc.wrap64(rc.INT_MIN - 1), rc.INT_MAX)
        self.assertEqual(rc.wrap64(0), 0)


class NumericFunctions(GateHarness):
    """Spec 03, contract 2.1: abs, min, max, floor, ceil, round, to the bit."""

    def value(self, expression, **kwargs):
        resolved, _ = self.build(document(expression, version="2.1.0"), **kwargs)
        return resolved["properties"]["text"]

    def occurrences(self, expression, **kwargs):
        _, occurrences = self.build(document(expression, version="2.1.0"), **kwargs)
        return occurrences

    def test_abs_keeps_the_numeric_type(self):
        self.assertEqual(self.value("$str($abs(0 - 5))"), "5")
        self.assertEqual(self.value("$str($abs(2.5))"), "2.5")

    def test_abs_of_the_minimum_int_wraps_to_itself_without_a_report(self):
        # Two's complement has no positive counterpart; the expression spec
        # keeps wrapping semantics and reports nothing.
        expression = "$str($abs(0 - 9223372036854775807 - 1))"
        self.assertEqual(self.value(expression), "-9223372036854775808")
        self.assertEqual(self.occurrences(expression), [])

    def test_abs_follows_ieee_754_on_doubles(self):
        self.assertEqual(self.value("$str($abs(-(0.0)))"), "0.0")
        self.assertEqual(self.value("$str($abs(0.0 / 0.0))"), "nan")
        self.assertEqual(self.value("$str($abs((0.0 - 1.0) / 0.0))"), "inf")

    def test_min_and_max_stay_int_when_every_argument_is_int(self):
        self.assertEqual(self.value("$str($min(3, 1, 2))"), "1")
        self.assertEqual(self.value("$str($max(3, 1, 2))"), "3")

    def test_min_and_max_promote_when_any_argument_is_double(self):
        self.assertEqual(self.value("$str($min(1, 2.5))"), "1.0")
        self.assertEqual(self.value("$str($max(2, 1.5))"), "2.0")

    def test_min_and_max_keep_the_leftmost_of_equals(self):
        # Signed zeros compare equal, so position decides; the platform's
        # min would pick by sign and the engines would disagree.
        self.assertEqual(self.value("$str($min(0.0, -(0.0)))"), "0.0")
        self.assertEqual(self.value("$str($min(-(0.0), 0.0))"), "-0.0")
        self.assertEqual(self.value("$str($max(0.0, -(0.0)))"), "0.0")

    def test_min_and_max_propagate_nan(self):
        self.assertEqual(self.value("$str($max(1.0, 0.0 / 0.0))"), "nan")
        self.assertEqual(self.value("$str($min(0.0 / 0.0, 1.0))"), "nan")

    def test_floor_and_ceil_keep_the_sign_of_a_zero_result(self):
        self.assertEqual(self.value("$str($floor(-0.5))"), "-1.0")
        self.assertEqual(self.value("$str($floor(-(0.0)))"), "-0.0")
        self.assertEqual(self.value("$str($ceil(-0.5))"), "-0.0")
        self.assertEqual(self.value("$str($ceil(0.5))"), "1.0")

    def test_round_breaks_ties_away_from_zero(self):
        # Never the platform's rule: Kotlin rounds half to even, JavaScript
        # half toward positive infinity.
        self.assertEqual(self.value("$str($round(0.5))"), "1.0")
        self.assertEqual(self.value("$str($round(2.5))"), "3.0")
        self.assertEqual(self.value("$str($round(-2.5))"), "-3.0")
        self.assertEqual(self.value("$str($round(-0.4))"), "-0.0")

    def test_round_does_not_carry_the_classic_half_bug(self):
        # 0.49999999999999994 + 0.5 rounds to 1.0 in binary64, so the
        # floor(x + 0.5) shortcut answers 1.0; the spec answers 0.0.
        self.assertEqual(self.value("$str($round(0.49999999999999994))"), "0.0")

    def test_rounding_passes_non_finite_values_through(self):
        self.assertEqual(self.value("$str($round(1.0 / 0.0))"), "inf")
        self.assertEqual(self.value("$str($floor(0.0 / 0.0))"), "nan")
        self.assertEqual(self.value("$str($ceil((0.0 - 1.0) / 0.0))"), "-inf")

    def test_rounding_functions_take_exactly_a_double(self):
        # Like int() and double(): the int-to-double promotion applies to
        # declared positions, not to a function's argument.
        for function in ("floor", "ceil", "round"):
            fields = self.refusal(document(f"$str({function}(1))", version="2.1.0"))
            self.assertEqual(fields["rule"], "expression", function)

    def test_min_and_max_take_two_or_more_numeric_arguments(self):
        self.assertEqual(self.refusal(document("$str($min(1))", version="2.1.0"))["rule"],
                         "expression")
        self.assertEqual(self.refusal(document("$str($max('a', 1))", version="2.1.0"))["rule"],
                         "expression")
        self.assertEqual(self.value("$str($max(1, 2, 3, 4))"), "4")

    def test_abs_takes_a_number(self):
        self.assertEqual(self.refusal(document("$abs('x')", version="2.1.0"))["rule"],
                         "expression")


class ContractFeatures(GateHarness):
    """Spec 01, Validation: a document is processed under the rules of the
    minor it declares; a later minor's feature is refused by name."""

    def test_a_2_1_function_in_a_2_0_document_is_the_contract_feature_violation(self):
        # The detail names the feature as a document spells it, sigil
        # included, since that is what the producer has to change.
        for function, call in (("$abs", "$abs(1)"), ("$min", "$min(1, 2)"), ("$max", "$max(1, 2)"),
                               ("$floor", "$floor(1.5)"), ("$ceil", "$ceil(1.5)"),
                               ("$round", "$round(1.5)")):
            fields = self.refusal(document(f"$str({call})", version="2.0.0"))
            self.assertEqual(fields["rule"], "contract-feature", function)
            self.assertEqual(fields["expected"], "2.1", function)
            self.assertEqual(fields["found"], function)
            self.assertEqual(fields["node"], "r")

    def test_the_same_call_builds_once_the_document_declares_2_1(self):
        self.build(document("$str($abs(1))", version="2.1.0"))

    def test_the_failure_root_is_gated_by_name(self):
        vocabulary = dict(VOCABULARY, actions={"go": {"failure": "string"}})
        doc = {"version": "2.0.0", "state": {"s": "string"},
               "root": {"type": "Text", "id": "r", "properties": {"text": "x"}}}
        doc["root"]["on"] = {}
        vocabulary["components"] = dict(VOCABULARY["components"])
        vocabulary["components"]["Text"] = {"properties": {"text": "string"},
                                            "events": {"tap": None}}
        doc["root"]["on"] = {"tap": [{"action": "go", "onFailure": [
            {"action": "$set", "key": "s", "value": {"$expr": "failure"}}]}]}
        fields = self.refusal(doc, vocabulary=vocabulary, state={"s": ""})
        self.assertEqual(fields["rule"], "contract-feature")
        self.assertEqual(fields["found"], "failure")
        doc["version"] = "2.1.0"
        self.build(doc, vocabulary=vocabulary, state={"s": ""})

    def test_a_lifecycle_section_is_gated_with_no_node(self):
        doc = {"version": "2.0.0",
               "root": {"type": "Text", "id": "r", "properties": {"text": "x"}},
               "on": {"appear": []}}
        fields = self.refusal(doc)
        self.assertEqual(fields["rule"], "contract-feature")
        self.assertEqual(fields["found"], "on")
        self.assertNotIn("node", fields)

    def test_a_repeat_key_is_gated_on_the_construct(self):
        doc = {"version": "2.0.0", "state": {"rows": {"array": "string"}},
               "root": {"type": "Column", "id": "c", "children": [
                   {"type": "$repeat", "id": "each", "items": {"$expr": "state.rows"},
                    "as": "row", "key": {"$expr": "row"},
                    "children": [{"type": "Text", "id": "t", "properties": {"text": {"$expr": "row"}}}]}]}}
        fields = self.refusal(doc, state={"rows": ["a"]})
        self.assertEqual(fields["rule"], "contract-feature")
        self.assertEqual(fields["found"], "key")
        self.assertEqual(fields["node"], "each")

    def test_the_repeat_construct_itself_stays_the_construct_violation_in_1_x(self):
        doc = {"version": "1.0.0", "state": {"rows": {"array": "string"}},
               "root": {"type": "Column", "id": "c", "children": [
                   {"type": "$repeat", "id": "each", "items": {"$expr": "state.rows"},
                    "as": "row", "children": [{"type": "Text", "id": "t",
                                               "properties": {"text": "x"}}]}]}}
        self.assertEqual(self.refusal(doc, state={"rows": []})["rule"], "construct")


class RepeatKeys(GateHarness):
    """Spec 01, Constructs: the key of a $repeat (contract 2.1)."""

    def keyed(self, key, rows_type=None, version="2.1.0", text="row.name"):
        return {"version": version,
                "state": {"rows": rows_type or {"array": {"record": {"id": "string", "name": "string"}}}},
                "root": {"type": "Column", "id": "c", "children": [
                    {"type": "$repeat", "id": "each", "items": {"$expr": "state.rows"},
                     "as": "row", "key": key,
                     "children": [{"type": "Text", "id": "t",
                                   "properties": {"text": {"$expr": text}}}]}]}}

    ROWS = [{"id": "alpha", "name": "Alpha"}, {"id": "beta", "name": "Beta"}]

    def test_the_key_rendering_replaces_the_index_in_the_reference(self):
        resolved, _ = self.build(self.keyed({"$expr": "row.id"}), state={"rows": self.ROWS})
        self.assertEqual([child["reference"] for child in resolved["children"]],
                         ["t[alpha]", "t[beta]"])

    def test_an_int_key_renders_in_decimal_and_an_enum_as_its_member(self):
        rows = {"array": {"record": {"n": "int", "name": "string"}}}
        resolved, _ = self.build(self.keyed({"$expr": "row.n"}, rows),
                                 state={"rows": [{"n": -3, "name": "x"}]})
        self.assertEqual(resolved["children"][0]["reference"], "t[-3]")
        rows = {"array": {"record": {"tone": {"enum": ["a", "b"]}, "name": "string"}}}
        resolved, _ = self.build(self.keyed({"$expr": "row.tone"}, rows),
                                 state={"rows": [{"tone": "b", "name": "x"}]})
        self.assertEqual(resolved["children"][0]["reference"], "t[b]")

    def test_the_index_binding_still_counts_positions(self):
        resolved, _ = self.build(self.keyed({"$expr": "row.id"}, text="$str(row_index)"),
                                 state={"rows": self.ROWS})
        self.assertEqual([c["properties"]["text"] for c in resolved["children"]], ["0", "1"])

    def test_a_literal_key_is_refused(self):
        fields = self.refusal(self.keyed("abc"), state={"rows": self.ROWS})
        self.assertEqual((fields["rule"], fields["expected"], fields["found"]),
                         ("repeat", "key expression", "string"))

    def test_a_key_of_the_wrong_type_is_refused(self):
        rows = {"array": {"record": {"flag": "bool", "tag": "string?", "name": "string"}}}
        state = {"rows": [{"flag": True, "tag": None, "name": "x"}]}
        fields = self.refusal(self.keyed({"$expr": "row.flag"}, rows), state=state)
        self.assertEqual((fields["rule"], fields["expected"], fields["found"]),
                         ("repeat", "key type", "bool"))
        fields = self.refusal(self.keyed({"$expr": "row.tag"}, rows), state=state)
        self.assertEqual((fields["rule"], fields["expected"], fields["found"]),
                         ("repeat", "key type", "string?"))

    def test_a_key_that_does_not_type_check_is_the_expression_violation(self):
        fields = self.refusal(self.keyed({"$expr": "row.nope"}), state={"rows": self.ROWS})
        self.assertEqual((fields["rule"], fields["node"], fields["expected"]),
                         ("expression", "each", "string or int"))

    def test_repeated_keys_are_a_data_defect_at_build(self):
        fields = self.refusal(self.keyed({"$expr": "row.id"}),
                              state={"rows": [self.ROWS[0], self.ROWS[0]]})
        self.assertEqual((fields["rule"], fields["node"], fields["expected"], fields["found"]),
                         ("repeat", "each", "distinct key", "alpha"))

    def test_the_key_is_checked_after_the_items_type_and_before_the_template(self):
        doc = self.keyed("abc", rows_type="int")
        fields = self.refusal(doc, state={"rows": 3})
        self.assertEqual(fields["expected"], "array items")
        doc = self.keyed("abc", text="row.nope")
        fields = self.refusal(doc, state={"rows": self.ROWS})
        self.assertEqual(fields["expected"], "key expression")

    def test_the_key_counts_against_the_expression_length_limit(self):
        gate = rc.ReferenceGate(VOCABULARY, "fail", limits={"maxExpressionLength": 4})
        with self.assertRaises(rc.GateError) as caught:
            gate.build({"name": "t", "document": self.keyed({"$expr": "row.id"}),
                        "context": {}, "state": {"rows": self.ROWS}})
        self.assertEqual(caught.exception.fields["limit"], "maxExpressionLength")

    def test_unknown_key_lint_knows_the_key(self):
        self.assertEqual(rc.unknown_key_warnings(self.keyed({"$expr": "row.id"})), [])


class LifecycleBindings(GateHarness):
    """Spec 01, Lifecycle bindings: the document's on section (contract 2.1)."""

    def doc(self, on, version="2.1.0"):
        return {"version": version, "state": {"n": "int"},
                "root": {"type": "Text", "id": "r", "properties": {"text": {"$expr": "$str(state.n)"}}},
                "on": on}

    def test_appear_and_disappear_bind_action_lists(self):
        self.build(self.doc({"appear": [{"action": "$set", "key": "n", "value": 1}],
                             "disappear": {"action": "$set", "key": "n", "value": 0}}),
                   state={"n": 0})

    def test_any_other_signal_name_is_refused_with_no_node(self):
        fields = self.refusal(self.doc({"load": []}), state={"n": 0})
        self.assertEqual((fields["rule"], fields["expected"], fields["found"]),
                         ("event-binding", "lifecycle event", "load"))
        self.assertNotIn("node", fields)

    def test_the_event_root_is_unavailable(self):
        fields = self.refusal(self.doc({"appear": [{"action": "$set", "key": "n",
                                                    "value": {"$expr": "event"}}]}),
                              state={"n": 0})
        self.assertEqual(fields["rule"], "expression")

    def test_a_custom_action_needs_the_grant_and_the_handler(self):
        fields = self.refusal(self.doc({"appear": [{"action": "secret"}]}), state={"n": 0})
        self.assertEqual(fields["rule"], "action-capability")
        gate = rc.ReferenceGate(VOCABULARY, "fail", surface={"actionHandler": False})
        with self.assertRaises(rc.GateError) as caught:
            gate.build({"name": "t", "document": self.doc({"appear": [{"action": "go", "url": "x"}]}),
                        "context": {}, "state": {"n": 0}})
        self.assertEqual(caught.exception.fields["rule"], "action-handler")

    def test_the_section_is_validated_after_the_tree(self):
        doc = self.doc({"load": []})
        doc["root"]["properties"]["text"] = {"$expr": "state.nope"}
        self.assertEqual(self.refusal(doc, state={"n": 0})["rule"], "expression")

    def test_a_non_object_section_is_malformed(self):
        self.assertEqual(self.refusal(self.doc([]), state={"n": 0})["type"], "MalformedDocument")

    def test_unknown_key_lint_knows_the_section(self):
        self.assertEqual(rc.unknown_key_warnings(self.doc({"appear": []})), [])


class FailurePayloads(GateHarness):
    """Spec 02, Failure payloads: the failure root (contract 2.1)."""

    vocabulary = {
        "milano": "2.1.0", "name": "checker", "version": "1.0.0",
        "components": {"Button": {"properties": {"label": "string"}, "events": {"tap": None}}},
        "actions": {"go": {"failure": {"enum": ["limit", "offline"]}},
                    "fetch": {"result": "string", "failure": {"record": {"code": "int"}}},
                    "plain": {}},
    }

    def doc(self, bindings, version="2.1.0"):
        return {"version": version, "state": {"s": "string", "n": "int"},
                "root": {"type": "Button", "id": "b", "properties": {"label": "x"},
                         "on": {"tap": bindings}}}

    def test_failure_binds_inside_on_failure_with_the_declared_type(self):
        self.build(self.doc([{"action": "go", "onFailure": [
            {"action": "$set", "key": "s", "value": {"$expr": "failure"}},
            {"action": "$when", "condition": {"$expr": "failure == 'limit'"}}]}]),
            state={"s": "", "n": 0})
        self.build(self.doc([{"action": "fetch", "onFailure": [
            {"action": "$set", "key": "n", "value": {"$expr": "failure.code"}}]}]),
            state={"s": "", "n": 0})

    def test_the_declared_type_is_exact(self):
        fields = self.refusal(self.doc([{"action": "fetch", "onFailure": [
            {"action": "$set", "key": "s", "value": {"$expr": "failure"}}]}]),
            state={"s": "", "n": 0})
        self.assertEqual(fields["rule"], "expression")
        fields = self.refusal(self.doc([{"action": "go", "onFailure": [
            {"action": "$when", "condition": {"$expr": "failure == 'teapot'"}}]}]),
            state={"s": "", "n": 0})
        self.assertEqual(fields["rule"], "expression")

    def test_failure_is_unavailable_elsewhere(self):
        for bindings in (
                [{"action": "go", "onSuccess": [{"action": "$set", "key": "s", "value": {"$expr": "failure"}}]}],
                [{"action": "plain", "onFailure": [{"action": "$set", "key": "s", "value": {"$expr": "failure"}}]}],
                [{"action": "$set", "key": "s", "value": {"$expr": "failure"}}]):
            fields = self.refusal(self.doc(bindings), state={"s": "", "n": 0})
            self.assertEqual(fields["rule"], "expression", bindings)

    def test_failure_rebinds_at_each_nesting(self):
        # Inside the nested action's onFailure, failure is the nested
        # action's payload (a record here), not the outer enum.
        self.build(self.doc([{"action": "go", "onFailure": [
            {"action": "fetch", "onFailure": [
                {"action": "$set", "key": "n", "value": {"$expr": "failure.code"}}]}]}]),
            state={"s": "", "n": 0})
        fields = self.refusal(self.doc([{"action": "go", "onFailure": [
            {"action": "fetch", "onFailure": [
                {"action": "$set", "key": "s", "value": {"$expr": "failure"}}]}]}]),
            state={"s": "", "n": 0})
        self.assertEqual(fields["rule"], "expression")

    def test_the_outer_failure_flows_inward_as_a_parameter(self):
        vocabulary = dict(self.vocabulary)
        vocabulary["actions"] = dict(self.vocabulary["actions"],
                                     retry={"parameters": {"reason": "string"}})
        self.build(self.doc([{"action": "go", "onFailure": [
            {"action": "retry", "reason": {"$expr": "failure"}}]}]),
            vocabulary=vocabulary, state={"s": "", "n": 0})

    def test_builtins_nested_in_on_failure_keep_the_root(self):
        self.build(self.doc([{"action": "go", "onFailure": [
            {"action": "$sequence", "actions": [
                {"action": "$set", "key": "s", "value": {"$expr": "failure"}}]}]}]),
            state={"s": "", "n": 0})


VOCABULARY_2_1 = {
    "milano": "2.1.0",
    "name": "checker",
    "version": "1.0.0",
    "components": {
        "Text": {"properties": {"text": "string"}, "events": {"tap": None}},
        "Column": {"children": True},
    },
    "actions": {"go": {"parameters": {"url": "string"}}},
    "functions": {
        "formatMoney": {"arguments": ["int", "string"], "returns": "string"},
        "half": {"arguments": ["double"], "returns": "double"},
        "lookup": {"arguments": ["string"], "returns": "string?"},
        "tone": {"arguments": [{"enum": ["a", "b"]}], "returns": {"enum": ["x", "y"]}},
    },
}

ROWS = {"array": {"record": {"name": "string", "done": "bool"}}}


def stepped(actions, state_decls=None, version="2.1.0", **extra):
    """A one-node 2.1 document binding `actions` to the node's tap."""
    doc = {
        "version": version,
        "state": state_decls or {"rows": ROWS, "n": "int"},
        "root": {"type": "Text", "id": "r", "properties": {"text": "x"},
                 "on": {"tap": actions}},
    }
    doc.update(extra)
    return doc


class ArrayActions(GateHarness):
    """Spec 01, Actions: $append, $remove, $update target an array key and
    are encoded like every action; spec 04 fixes what they do at runtime,
    which the engines pin. Here: the gate's rules."""

    vocabulary = VOCABULARY_2_1

    def state(self):
        return {"rows": [], "n": 0}

    def test_well_formed_array_actions_build(self):
        doc = stepped([
            {"action": "$append", "key": "rows",
             "value": {"name": "a", "done": False}},
            {"action": "$remove", "key": "rows", "at": {"$expr": "state.n"}},
            {"action": "$update", "key": "rows", "at": 0, "field": "done",
             "value": {"$expr": "!state.rows[0].done || true"}},
        ])
        # Indexing is not in the grammar; the value above is a plain bool.
        doc["root"]["on"]["tap"][2]["value"] = True
        self.build(doc, state=self.state())

    def test_they_are_gated_by_the_declared_version(self):
        for name, action in (("$append", {"action": "$append", "key": "rows",
                                          "value": {"name": "a", "done": False}}),
                             ("$remove", {"action": "$remove", "key": "rows", "at": 0}),
                             ("$update", {"action": "$update", "key": "rows", "at": 0,
                                          "field": "done", "value": True})):
            fields = self.refusal(stepped([action], version="2.0.0"), state=self.state())
            self.assertEqual(fields["rule"], "contract-feature", name)
            self.assertEqual(fields["expected"], "2.1")
            self.assertEqual(fields["found"], name)
            self.assertEqual(fields["node"], "r")

    def test_the_target_must_be_a_declared_non_optional_array(self):
        fields = self.refusal(stepped([{"action": "$append", "key": "nope", "value": 1}]),
                              state=self.state())
        self.assertEqual((fields["rule"], fields["expected"], fields["found"]),
                         ("action-encoding", "declared state key", "nope"))
        fields = self.refusal(stepped([{"action": "$append", "key": "n", "value": 1}]),
                              state=self.state())
        self.assertEqual((fields["expected"], fields["found"]), ("array state key", "n"))
        doc = stepped([{"action": "$remove", "key": "maybe", "at": 0}],
                      state_decls={"maybe": {"array": "int", "optional": True}})
        fields = self.refusal(doc, state={"maybe": None})
        self.assertEqual((fields["expected"], fields["found"]), ("array state key", "maybe"))

    def test_update_needs_record_elements_and_a_declared_field(self):
        doc = stepped([{"action": "$update", "key": "ints", "at": 0, "field": "x", "value": 1}],
                      state_decls={"ints": {"array": "int"}})
        fields = self.refusal(doc, state={"ints": []})
        self.assertEqual((fields["expected"], fields["found"]), ("record element", "ints"))
        doc = stepped([{"action": "$update", "key": "rows", "at": 0, "field": "size",
                        "value": 1}])
        fields = self.refusal(doc, state=self.state())
        self.assertEqual((fields["expected"], fields["found"]), ("declared field", "size"))

    def test_parameters_are_exactly_the_declared_ones(self):
        doc = stepped([{"action": "$remove", "key": "rows", "at": 0, "value": 1}])
        fields = self.refusal(doc, state=self.state())
        self.assertEqual((fields["expected"], fields["found"]), ("declared parameter", "value"))
        doc = stepped([{"action": "$remove", "key": "rows"}])
        fields = self.refusal(doc, state=self.state())
        self.assertEqual(fields["expected"], "at")
        self.assertNotIn("found", fields)
        doc = stepped([{"action": "$update", "key": "rows", "at": 0, "field": "done"}])
        fields = self.refusal(doc, state=self.state())
        self.assertEqual(fields["expected"], "value")

    def test_values_are_typed_as_declared_positions(self):
        doc = stepped([{"action": "$remove", "key": "rows", "at": "first"}])
        fields = self.refusal(doc, state=self.state())
        self.assertEqual((fields["rule"], fields["expected"], fields["found"]),
                         ("action-encoding", "int", "string"))
        doc = stepped([{"action": "$append", "key": "rows", "value": {"$expr": "state.n"}}])
        fields = self.refusal(doc, state=self.state())
        self.assertEqual(fields["rule"], "expression")
        doc = stepped([{"action": "$append", "key": "doubles", "value": 1}],
                      state_decls={"doubles": {"array": "double"}})
        self.build(doc, state={"doubles": []})

    def test_the_repeat_index_binding_serves_as_at(self):
        doc = {
            "version": "2.1.0", "state": {"rows": ROWS},
            "root": {"type": "Column", "id": "c", "children": [
                {"type": "$repeat", "id": "list", "items": {"$expr": "state.rows"},
                 "as": "row", "key": {"$expr": "row.name"}, "children": [
                     {"type": "Text", "id": "t",
                      "properties": {"text": {"$expr": "row.name"}},
                      "on": {"tap": [{"action": "$remove", "key": "rows",
                                      "at": {"$expr": "row_index"}}]}}]}]},
        }
        self.build(doc, state={"rows": [{"name": "a", "done": False}]})


class WatchBindings(GateHarness):
    """Spec 01, Watch bindings: keys declared, lists under the lifecycle
    rules, gated by version, validated after the lifecycle section."""

    vocabulary = VOCABULARY_2_1

    def test_a_watch_binds_an_action_list_to_a_declared_key(self):
        doc = stepped([], watch={"n": [{"action": "$set", "key": "n",
                                        "value": {"$expr": "state.n + 1"}}]})
        self.build(doc, state={"rows": [], "n": 0})

    def test_an_undeclared_key_is_the_watch_rule_with_no_node(self):
        doc = stepped([], watch={"missing": []})
        fields = self.refusal(doc, state={"rows": [], "n": 0})
        self.assertEqual((fields["rule"], fields["expected"], fields["found"]),
                         ("watch", "declared state key", "missing"))
        self.assertNotIn("node", fields)

    def test_the_event_root_is_unavailable(self):
        doc = stepped([], watch={"n": [{"action": "$set", "key": "n",
                                        "value": {"$expr": "event"}}]})
        fields = self.refusal(doc, state={"rows": [], "n": 0})
        self.assertEqual(fields["rule"], "expression")

    def test_the_section_is_gated_by_the_declared_version(self):
        doc = stepped([], version="2.0.0", watch={"n": []})
        fields = self.refusal(doc, state={"rows": [], "n": 0})
        self.assertEqual((fields["rule"], fields["expected"], fields["found"]),
                         ("contract-feature", "2.1", "watch"))

    def test_a_custom_action_in_a_watch_needs_the_handler(self):
        doc = stepped([], watch={"n": [{"action": "go", "url": "x"}]})
        gate = rc.ReferenceGate(self.vocabulary, "fail", surface={"actionHandler": False})
        with self.assertRaises(rc.GateError) as caught:
            gate.build({"name": "t", "document": doc, "context": {},
                        "state": {"rows": [], "n": 0}})
        self.assertEqual(caught.exception.fields["rule"], "action-handler")

    def test_the_section_is_validated_after_the_lifecycle_section(self):
        doc = stepped([], on={"nosuch": []}, watch={"missing": []})
        fields = self.refusal(doc, state={"rows": [], "n": 0})
        self.assertEqual(fields["rule"], "event-binding")

    def test_a_non_object_section_is_malformed(self):
        doc = stepped([], watch=[])
        self.assertEqual(self.refusal(doc, state={"rows": [], "n": 0})["type"],
                         "MalformedDocument")

    def test_unknown_key_lint_knows_the_section(self):
        self.assertEqual(rc.unknown_key_warnings(stepped([], watch={})), [])


class HostFunctions(GateHarness):
    """Spec 03, Host functions: declared functions type like built-ins with
    declared positions, evaluate through the results table, and fall back
    to the zero value on an invalid result."""

    vocabulary = VOCABULARY_2_1

    def gate(self, results=None, handler=True, declare=None):
        surface = {"functionHandler": handler,
                   "functions": {"results": results or {}, "declare": declare or {}}}
        return rc.ReferenceGate(self.vocabulary, "fail", surface=surface)

    def resolve(self, expression, results=None, version="2.1.0", **kwargs):
        gate = self.gate(results, **kwargs)
        doc = document(expression, version=version, state={"cents": "int"})
        resolved, _ = gate.build({"name": "t", "document": doc, "context": {},
                                  "state": {"cents": 1250}})
        return resolved["properties"]["text"], gate.occurrences

    def test_a_call_resolves_through_the_results_table(self):
        value, occurrences = self.resolve(
            "$concat('Total: ', formatMoney(state.cents, 'EUR'))",
            results={"formatMoney": [{"arguments": [1250, "EUR"], "returns": "12.50 EUR"}]})
        self.assertEqual(value, "Total: 12.50 EUR")
        self.assertEqual(occurrences, [])

    def test_arguments_are_declared_positions(self):
        # An int literal promotes to the declared double before the call.
        value, _ = self.resolve("$str(half(3))",
                                results={"half": [{"arguments": [3.0], "returns": 1.5}]})
        self.assertEqual(value, "1.5")
        # A member literal refines to the declared enum; the result is the enum.
        value, _ = self.resolve("$str(tone('a'))",
                                results={"tone": [{"arguments": ["a"], "returns": "y"}]})
        self.assertEqual(value, "y")
        fields = self.refusal(document("$str(tone('c'))", version="2.1.0"))
        self.assertEqual(fields["rule"], "expression")

    def test_arity_and_argument_types_are_checked(self):
        for expression in ("formatMoney(1)", "formatMoney(1, 'EUR', 'x')",
                           "formatMoney('1', 'EUR')", "half(1.0 == 1.0)"):
            fields = self.refusal(document(expression, version="2.1.0"))
            self.assertEqual(fields["rule"], "expression", expression)

    def test_the_return_type_is_the_declared_one(self):
        fields = self.refusal(document("lookup('k')", version="2.1.0"))
        self.assertEqual(fields["rule"], "expression")  # string? where string is declared
        value, _ = self.resolve("lookup('k') ?? 'none'",
                                results={"lookup": [{"arguments": ["k"], "returns": None}]})
        self.assertEqual(value, "none")

    def test_an_unknown_name_stays_the_expression_violation(self):
        fields = self.refusal(document("nosuch(1)", version="2.1.0"))
        self.assertEqual(fields["rule"], "expression")

    def test_a_call_in_a_2_0_document_is_the_contract_feature_violation(self):
        fields = self.refusal(document("formatMoney(1, 'EUR')", version="2.0.0"))
        self.assertEqual((fields["rule"], fields["expected"], fields["found"]),
                         ("contract-feature", "2.1", "formatMoney"))

    def test_a_missing_handler_is_refused_at_build(self):
        gate = self.gate(handler=False)
        with self.assertRaises(rc.GateError) as caught:
            gate.build({"name": "t", "document": document("formatMoney(1, 'EUR')",
                                                           version="2.1.0"),
                        "context": {}, "state": {}})
        self.assertEqual((caught.exception.fields["rule"], caught.exception.fields["expected"]),
                         ("function-handler", "function handler"))
        # A document calling nothing builds without one.
        self.gate(handler=False).build({"name": "t", "document": document("'x'", version="2.1.0"),
                                        "context": {}, "state": {}})

    def test_an_invalid_result_is_reported_and_evaluates_to_the_zero_value(self):
        value, occurrences = self.resolve(
            "formatMoney(state.cents, 'EUR')",
            results={"formatMoney": [{"arguments": [1250, "EUR"], "returns": 12.5}]})
        self.assertEqual(value, "")
        self.assertEqual(occurrences, [{"kind": "invalidFunctionResult", "node": "r",
                                        "name": "formatMoney", "expected": "string",
                                        "found": "double"}])
        value, occurrences = self.resolve(
            "$str(half(1.0))", results={"half": [{"arguments": [1.0], "throws": True}]})
        self.assertEqual(value, "0.0")
        self.assertEqual(occurrences[0]["found"], "error")
        value, _ = self.resolve("$str(tone('a'))",
                                results={"tone": [{"arguments": ["a"], "returns": "z"}]})
        self.assertEqual(value, "x")

    def test_zero_values_follow_the_declared_type(self):
        self.assertEqual(rc.zero_value(rc.parse_type("string?")), None)
        self.assertEqual(rc.zero_value(rc.parse_type({"record": {"a": "int", "b": "bool"}})),
                         {"a": 0, "b": False})
        self.assertEqual(rc.zero_value(rc.parse_type({"array": "int"})), [])
        self.assertEqual(rc.zero_value(rc.parse_type({"enum": ["m", "n"]})), "m")

    def test_a_call_with_no_case_in_the_table_is_a_vector_defect(self):
        with self.assertRaises(rc.HostFunctionMiss):
            self.resolve("formatMoney(1, 'EUR')", results={"formatMoney": []})

    def test_builder_declarations_add_and_override(self):
        value, _ = self.resolve("$str(twice(2))",
                                results={"twice": [{"arguments": [2], "returns": 4}]},
                                declare={"twice": {"arguments": ["int"], "returns": "int"}})
        self.assertEqual(value, "4")
        value, _ = self.resolve("$str(half(2))",
                                results={"half": [{"arguments": [2], "returns": 1}]},
                                declare={"half": {"arguments": ["int"], "returns": "int"}})
        self.assertEqual(value, "1")

    def test_the_producer_cli_answers_zero_values(self):
        gate = rc.ReferenceGate(self.vocabulary, "fail")
        gate.function_results = None
        resolved, occurrences = gate.build({"name": "t", "document": document(
            "formatMoney(1, 'EUR')", version="2.1.0"), "context": {}, "state": {}}), gate.occurrences
        self.assertEqual(resolved[0]["properties"]["text"], "")
        self.assertEqual(occurrences, [])


class DoubleFormatting(GateHarness):
    """Spec 03: $str() on a double, a Milano format rather than the host's."""

    def test_integral_values_keep_one_fractional_digit(self):
        self.assertEqual(self.value("$str(5.0)"), "5.0")

    def test_plain_decimal_up_to_the_upper_exponent_edge(self):
        # The window is a normalized exponent in [-4, 15]; 1e15 is inside.
        self.assertEqual(self.value("$str(1000000000000000.0)"),
                         "1000000000000000.0")

    def test_scientific_notation_above_the_upper_edge(self):
        self.assertEqual(self.value("$str(10000000000000000.0)"), "1e16")

    def test_plain_decimal_down_to_the_lower_exponent_edge(self):
        self.assertEqual(self.value("$str(0.0001)"), "0.0001")

    def test_scientific_notation_below_the_lower_edge(self):
        self.assertEqual(self.value("$str(0.00001)"), "1e-5")

    def test_non_finite_values_have_fixed_spellings(self):
        # Not Python's 'inf'/'nan' by coincidence: the spec fixes these, and
        # a platform default would give "Infinity" or "NaN" elsewhere.
        self.assertEqual(rc.format_scalar(float("nan")), "nan")
        self.assertEqual(rc.format_scalar(float("inf")), "inf")
        self.assertEqual(rc.format_scalar(float("-inf")), "-inf")

    def test_booleans_are_lowercase(self):
        self.assertEqual(self.value("$str(true)"), "true")
        self.assertEqual(self.value("$str(false)"), "false")


class TypeChecking(GateHarness):
    """Spec 03: the gate rejects statically, so evaluation is total."""

    def test_unknown_identifier_is_refused(self):
        self.assertEqual(self.refusal(document("$str(nope)"))["rule"], "expression")

    def test_wrong_argument_count_is_refused(self):
        self.assertEqual(self.refusal(document("$concat('a')"))["rule"], "expression")

    def test_mismatched_operand_types_are_refused(self):
        self.assertEqual(self.refusal(document("$str('a' + 1)"))["rule"], "expression")

    def test_coalescing_resolves_an_optional(self):
        doc = document("$str(state.maybe ?? 5)", state={"maybe": "int?"})
        self.assertEqual(self.build(doc)[0]["properties"]["text"], "5")

    def test_coalescing_a_non_optional_is_refused(self):
        # `??` exists to discharge optionality; applying it where there is
        # none is a producer mistake, not a harmless no-op.
        doc = document("$str(state.n ?? 5)", state={"n": "int"})
        self.assertEqual(self.refusal(doc)["rule"], "expression")

    def test_null_compares_only_to_an_optional_operand(self):
        # Spec 03: optionals are comparable to null. A non-optional beside
        # null, or null beside null, could only ever be constant and is
        # refused. Every engine did; the checker let the null literal's own
        # optionality stand in for the other operand's.
        doc = document("$str(state.maybe == null)", state={"maybe": "string?"})
        resolved, _ = self.build(doc, state={"maybe": None})
        self.assertEqual(resolved["properties"]["text"], "true")
        for expression in ("state.n == null", "null == state.n", "null == null", "'x' != null"):
            with self.subTest(expression=expression):
                doc = document(f"$str({expression})", state={"n": "string"})
                self.assertEqual(self.refusal(doc)["rule"], "expression")

    def test_enum_comparison_against_a_non_member_is_refused(self):
        doc = document("$str(state.role == 'nope')",
                       state={"role": {"enum": ["a", "b"]}})
        self.assertEqual(self.refusal(doc)["rule"], "expression")

    def test_enum_comparison_against_a_member_is_accepted(self):
        doc = document("$str(state.role == 'a')",
                       state={"role": {"enum": ["a", "b"]}})
        resolved, _ = self.build(doc, state={"role": "a"})
        self.assertEqual(resolved["properties"]["text"], "true")

    def test_if_branches_must_agree_on_optionality(self):
        # Spec 03: exactly the same T, optionality included. The null
        # literal is the only way an if makes an optional; a T? branch is
        # resolved with ?? before it can sit beside a T one. Swift and
        # Kotlin always refused this; the checker used to widen instead.
        doc = document("$if(true, state.maybe, 'x') ?? ''",
                       state={"maybe": "string?"})
        self.assertEqual(self.refusal(doc)["rule"], "expression")
        resolved = document("$if(true, state.maybe ?? 'y', 'x')",
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
        for declared in ("3.0.0", "2.2.0", "1.1.0"):
            fields = self.refusal(document("$str(1)", version=declared))
            self.assertEqual(fields["type"], "UnsupportedVersion", declared)
            self.assertEqual(fields["declared"], declared)
            self.assertEqual(fields["supported"], ["1.0", "2.1"])
        for declared in ("1.0.0", "2.0.0", "2.0.9", "2.1.0", "2.1.4"):
            self.build(document("$str(1)", version=declared))

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
        doc = document("$str(1)", state={"caf\u00e9": "int"})
        fields = self.refusal(doc)
        self.assertEqual(fields["rule"], "state-declaration")
        self.assertEqual(fields["found"], "caf\u00e9")
        digits = document("$str(1)", context={"a\u0663": "string"})
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
        long_expression = "$str(" + "1 + " * 300 + "1)"
        self.assertGreater(len(long_expression), rc.MAX_EXPRESSION_LENGTH)
        fields = self.refusal(document(long_expression))
        self.assertEqual(fields["limit"], "maxExpressionLength")


class VocabularyRequirement(GateHarness):
    """Spec 01 step 3: the producer's opt-in guard for staggered rollouts."""

    def test_a_matching_name_and_no_minimum_is_accepted(self):
        self.build(document("$str(1)", vocabulary={"name": "checker"}))

    def test_a_different_vocabulary_name_is_refused(self):
        fields = self.refusal(document("$str(1)", vocabulary={"name": "other"}))
        self.assertEqual(fields["rule"], "vocabulary-requirement")
        self.assertEqual((fields["expected"], fields["found"]), ("other", "checker"))

    def test_a_minimum_above_the_engine_s_version_is_refused(self):
        doc = document("$str(1)", vocabulary={"name": "checker", "min": "2.0.0"})
        fields = self.refusal(doc)
        self.assertEqual(fields["expected"], ">=2.0.0")

    def test_a_minimum_at_or_below_the_engine_s_version_is_accepted(self):
        self.build(document("$str(1)",
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
        doc = document("$concat('hi ', context.who)", context={"who": "string"})
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
        result = self.run_cli(document("$str(1)"))
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
        result = self.run_cli(document("$str(1 / 0)"))
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
                    "properties": {"text": {"$expr": "$str(state.n)"}},
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

    def test_lifecycle_steps_and_bindings_lint(self):
        vector = self.vector()
        vector["document"]["version"] = "2.1.0"
        vector["document"]["on"] = {"appear": [{"action": "$set", "key": "n",
                                                "value": {"$expr": "state.n + 1"}}]}
        vector["steps"] = [{"appear": True}, {"disappear": True}]
        self.assertEqual(rc.StepLinter(vector, self.vocabulary).lint(), [])
        vector["steps"] = [{"appear": "yes"}]
        self.assertTrue(rc.StepLinter(vector, self.vocabulary).lint())
        vector["steps"] = [{"appear": True}]
        vector["document"]["on"]["appear"][0]["value"] = {"$expr": "event"}
        self.assertTrue(rc.StepLinter(vector, self.vocabulary).lint(),
                        "the event root linted clean in a lifecycle binding")

    def test_array_actions_and_watch_lists_lint(self):
        vector = self.vector()
        vector["document"]["version"] = "2.1.0"
        vector["document"]["state"] = {"n": "int", "rows": {"array": "string"}}
        vector["state"] = {"n": 0, "rows": []}
        vector["document"]["root"]["on"]["tap"] = [
            {"action": "$append", "key": "rows", "value": "a"},
            {"action": "$remove", "key": "rows", "at": 0}]
        vector["document"]["watch"] = {"rows": [{"action": "$set", "key": "n",
                                                  "value": {"$expr": "$length(state.rows)"}}]}
        self.assertEqual(rc.StepLinter(vector, self.vocabulary).lint(), [])
        vector["document"]["root"]["on"]["tap"][0]["value"] = 1
        self.assertTrue(rc.StepLinter(vector, self.vocabulary).lint(),
                        "an ill-typed $append value linted clean")
        vector["document"]["root"]["on"]["tap"][0]["value"] = "a"
        vector["document"]["watch"]["rows"][0]["value"] = {"$expr": "event"}
        self.assertTrue(rc.StepLinter(vector, self.vocabulary).lint(),
                        "the event root linted clean in a watch list")

    def test_replace_steps_build_the_replacement(self):
        vector = self.vector()
        replacement = json.loads(json.dumps(vector["document"]))
        replacement["state"] = {"n": "int", "extra": "string"}
        vector["steps"].append({"replace": {"document": replacement,
                                            "state": {"extra": "x"}}})
        self.assertEqual(rc.StepLinter(vector, self.vocabulary).lint(), [])
        # After the replacement, steps address the new document.
        replacement["root"]["id"] = "s"
        vector["steps"].append({"event": {"node": "s", "name": "tap"}})
        self.assertEqual(rc.StepLinter(vector, self.vocabulary).lint(), [])
        vector["steps"][-1] = {"event": {"node": "r", "name": "tap"}}
        self.assertTrue(rc.StepLinter(vector, self.vocabulary).lint(),
                        "an event on the replaced document's node linted clean")
        # A replacement expected to fail must fail as stated.
        broken = json.loads(json.dumps(vector["document"]))
        broken["root"]["type"] = "Nope"
        vector["steps"] = [{"replace": {"document": broken}}]
        self.assertTrue(rc.StepLinter(vector, self.vocabulary).lint())
        vector["steps"] = [{"replace": {"document": broken,
                                        "error": {"type": "UnknownComponentType"}}}]
        self.assertEqual(rc.StepLinter(vector, self.vocabulary).lint(), [])

    def test_the_failure_root_is_typed_in_on_failure(self):
        vector = self.vector()
        vector["document"]["version"] = "2.1.0"
        vector["config"] = {"actions": {"declare": {"go": {"failure": "int"}}}}
        vector["document"]["root"]["on"]["tap"] = [{"action": "go", "onFailure": [
            {"action": "$set", "key": "n", "value": {"$expr": "failure"}}]}]
        vector["steps"].append({"complete": {"dispatch": 0, "outcome": "failure", "payload": 7}})
        vector["expect"]["dispatched"] = [{"action": "go", "parameters": {}}]
        self.assertEqual(rc.StepLinter(vector, self.vocabulary).lint(), [])
        vector["config"]["actions"]["declare"]["go"]["failure"] = "string"
        self.assertTrue(rc.StepLinter(vector, self.vocabulary).lint(),
                        "a string failure in an int slot linted clean")

    def test_a_keyed_instance_reference_resolves_to_its_template(self):
        vector = self.vector()
        vector["document"] = {
            "version": "2.1.0", "state": {"rows": {"array": "string"}},
            "root": {"type": "Text", "id": "r", "properties": {"text": "x"}}}
        vector["document"]["root"] = {"type": "Text", "id": "r", "properties": {"text": "x"}}
        vocabulary = dict(self.vocabulary)
        vocabulary["components"] = {"Column": {"children": True},
                                    "Text": {"properties": {"text": "string"}, "events": {"tap": None}}}
        vector["document"]["root"] = {"type": "Column", "id": "c", "children": [
            {"type": "$repeat", "id": "each", "items": {"$expr": "state.rows"}, "as": "row",
             "key": {"$expr": "row"},
             "children": [{"type": "Text", "id": "t", "properties": {"text": {"$expr": "row"}},
                           "on": {"tap": [{"action": "$set", "key": "rows",
                                           "value": {"$expr": "state.rows"}}]}}]}]}
        vector["state"] = {"rows": ["a-b", "c"]}
        vector["steps"] = [{"event": {"node": "t[a-b]", "name": "tap"}}]
        vector["expect"] = {"dispatched": [], "occurrences": []}
        self.assertEqual(rc.StepLinter(vector, vocabulary).lint(), [])


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
        doc = document("$str($length(context.tags))", context={"tags": {"array": "string"}})
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
        doc = document("$str(state.n)", state={"n": "int"})
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
