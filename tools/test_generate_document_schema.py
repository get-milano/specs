#!/usr/bin/env python3
"""Tests for tools/generate_document_schema.py.

The tool specializes the official document schema to one vocabulary, so
editors and producer CI can flag mistakes before the gate ever runs. Two
kinds of check here: the schema's shape, and, more importantly, what it
accepts and rejects when a real validator runs it over real documents.

The schema is an authoring-time approximation, never the source of truth,
so the tests also pin what it deliberately does not catch.

Run: python3 tools/test_generate_document_schema.py
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
TOOL = TOOLS / "generate_document_schema.py"

sys.path.insert(0, str(TOOLS))

import generate_document_schema as gds  # noqa: E402

DOCUMENT_SCHEMA = json.loads((ROOT / "schemas" / "document.schema.json").read_text())

VOCABULARY = {
    "milano": "1.0.0",
    "name": "authoring",
    "version": "1.0.0",
    "components": {
        "Column": {"children": True},
        "Text": {
            "properties": {
                "text": "string",
                "size": "int?",
                "weight": "double",
                "hidden": "bool",
                "role": {"enum": ["title", "body"]},
                "tone": {"enum": ["warm", "cool"], "optional": True},
                "tags": {"array": "string"},
                "meta": {"record": {"id": "string"}},
            },
            "events": {"tap": None},
        },
    },
    "actions": {"go": {"parameters": {"url": "string"}}},
}


def document(root):
    return {"version": "1.0.0", "root": root}


class LiteralSchemas(unittest.TestCase):
    """Each descriptor form becomes the JSON Schema an editor can use."""

    def test_scalars(self):
        self.assertEqual(gds.literal_schema("string"), {"type": "string"})
        self.assertEqual(gds.literal_schema("bool"), {"type": "boolean"})
        self.assertEqual(gds.literal_schema("int"), {"type": "integer"})
        self.assertEqual(gds.literal_schema("double"), {"type": "number"})

    def test_optional_scalars_admit_null(self):
        self.assertEqual(
            gds.literal_schema("int?"),
            {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        )

    def test_enums_are_sorted_so_the_output_is_stable(self):
        self.assertEqual(gds.literal_schema({"enum": ["b", "a"]}), {"enum": ["a", "b"]})

    def test_optional_enums_admit_null(self):
        self.assertEqual(
            gds.literal_schema({"enum": ["b", "a"], "optional": True}),
            {"anyOf": [{"enum": ["a", "b"]}, {"type": "null"}]},
        )

    def test_arrays_carry_their_element_schema(self):
        self.assertEqual(
            gds.literal_schema({"array": "int"}),
            {"type": "array", "items": {"type": "integer"}},
        )

    def test_records_stay_open(self):
        # An authoring aid, not the gate: the field shape is checked there.
        self.assertEqual(gds.literal_schema({"record": {"id": "string"}}), {"type": "object"})

    def test_every_property_also_accepts_an_expression(self):
        schema = gds.value_schema("string")
        self.assertEqual(schema["anyOf"][0], {"type": "string"})
        expression = schema["anyOf"][1]
        self.assertEqual(expression["required"], ["$expr"])
        self.assertFalse(expression["additionalProperties"])
        self.assertEqual(expression["properties"]["$expr"]["minLength"], 1)


class Specialization(unittest.TestCase):
    def setUp(self):
        self.schema = gds.specialize(DOCUMENT_SCHEMA, VOCABULARY)

    def test_names_the_vocabulary_it_was_built_for(self):
        self.assertIn("authoring@1.0.0", self.schema["title"])
        self.assertIn("gate remains the source of truth", self.schema["description"])

    def test_drops_the_official_identifier(self):
        # It is no longer that schema, and keeping the $id would make two
        # different documents claim the same identity.
        self.assertNotIn("$id", self.schema)

    def test_component_types_become_a_closed_sorted_enum_plus_the_construct(self):
        self.assertEqual(
            self.schema["$defs"]["node"]["properties"]["type"], {"enum": ["Column", "Text", "$repeat"]})

    def test_one_conditional_per_component_in_a_fixed_order_then_the_construct(self):
        branches = self.schema["$defs"]["node"]["allOf"]
        self.assertEqual(
            [branch["if"]["properties"]["type"]["const"] for branch in branches],
            ["Column", "Text", "$repeat"],
        )

    def test_the_construct_requires_its_own_keys_and_carries_no_component_keys(self):
        branch = self.schema["$defs"]["node"]["allOf"][-1]["then"]
        self.assertEqual(branch["required"], ["items", "as", "children"])
        self.assertEqual(branch["properties"]["properties"], {"type": "object", "maxProperties": 0})
        self.assertEqual(branch["properties"]["on"], {"type": "object", "maxProperties": 0})

    def test_childless_components_reject_children(self):
        branches = {b["if"]["properties"]["type"]["const"]: b["then"]["properties"] for b in self.schema["$defs"]["node"]["allOf"]}
        self.assertEqual(branches["Text"]["children"], {"type": "array", "maxItems": 0})
        self.assertNotIn("children", branches["Column"])

    def test_property_and_event_names_are_constrained(self):
        branches = {b["if"]["properties"]["type"]["const"]: b["then"]["properties"] for b in self.schema["$defs"]["node"]["allOf"]}
        self.assertEqual(
            branches["Text"]["properties"]["propertyNames"]["enum"],
            sorted(VOCABULARY["components"]["Text"]["properties"]),
        )
        self.assertEqual(branches["Text"]["on"]["propertyNames"]["enum"], ["tap"])
        # A component with no events constrains `on` to nothing at all.
        self.assertEqual(branches["Column"]["on"]["propertyNames"]["enum"], [])

    def test_a_vocabulary_with_no_components_is_left_alone(self):
        schema = gds.specialize(DOCUMENT_SCHEMA, {"name": "empty", "version": "1.0.0", "components": {}})
        self.assertIn("empty@1.0.0", schema["title"])
        self.assertNotIn("allOf", schema["$defs"]["node"])

    def test_does_not_mutate_the_schema_it_was_given(self):
        before = json.dumps(DOCUMENT_SCHEMA, sort_keys=True)
        gds.specialize(DOCUMENT_SCHEMA, VOCABULARY)
        self.assertEqual(json.dumps(DOCUMENT_SCHEMA, sort_keys=True), before)

    def test_is_deterministic(self):
        first = json.dumps(gds.specialize(DOCUMENT_SCHEMA, VOCABULARY), indent=2)
        second = json.dumps(gds.specialize(DOCUMENT_SCHEMA, VOCABULARY), indent=2)
        self.assertEqual(first, second)


class Behaviour(unittest.TestCase):
    """What the generated schema actually accepts and rejects. This is the
    part producers feel, so it is checked with a real validator rather than
    by reading the schema's shape."""

    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("jsonschema not installed")

    def setUp(self):
        import jsonschema

        self.validator = jsonschema.Draft202012Validator(
            gds.specialize(DOCUMENT_SCHEMA, VOCABULARY)
        )

    def valid(self, doc, why):
        errors = sorted(self.validator.iter_errors(doc), key=lambda e: e.path)
        self.assertEqual(errors, [], f"{why}: {[e.message for e in errors][:2]}")

    def invalid(self, doc, why):
        self.assertGreater(len(list(self.validator.iter_errors(doc))), 0, why)

    def test_accepts_a_well_formed_document(self):
        self.valid(
            document({
                "type": "Column",
                "children": [
                    {"type": "Text", "properties": {"text": "hello", "weight": 1.5,
                                                    "hidden": False, "role": "title",
                                                    "tags": ["a"], "meta": {"id": "x"}}}
                ],
            }),
            "a document using only declared types and properties",
        )

    def test_rejects_an_undeclared_component_type(self):
        self.invalid(document({"type": "Marquee"}), "a type the vocabulary never declared")

    def test_rejects_an_undeclared_property(self):
        self.invalid(
            document({"type": "Text", "properties": {"text": "hi", "colour": "red"}}),
            "a property the component never declared",
        )

    def test_rejects_a_mistyped_literal(self):
        self.invalid(
            document({"type": "Text", "properties": {"text": 42}}),
            "a number where the vocabulary declares a string",
        )

    def test_rejects_a_value_outside_a_declared_enum(self):
        self.invalid(
            document({"type": "Text", "properties": {"role": "headline"}}),
            "an enum value that is not a member",
        )

    def test_accepts_null_only_where_the_declaration_is_optional(self):
        self.valid(document({"type": "Text", "properties": {"size": None}}), "an optional int")
        self.invalid(
            document({"type": "Text", "properties": {"text": None}}),
            "null in a non-optional position",
        )

    def test_accepts_an_expression_anywhere_a_value_goes(self):
        self.valid(
            document({"type": "Text", "properties": {"text": {"$expr": "context.name"}}}),
            "an expression in a string property",
        )
        self.valid(
            document({"type": "Text", "properties": {"size": {"$expr": "state.n"}}}),
            "an expression in an optional int property",
        )

    def test_rejects_a_malformed_expression_wrapper(self):
        self.invalid(
            document({"type": "Text", "properties": {"text": {"$expr": ""}}}),
            "an empty expression",
        )
        self.invalid(
            document({"type": "Text", "properties": {"text": {"$expr": "a", "extra": 1}}}),
            "an expression wrapper with extra keys",
        )

    def test_rejects_children_on_a_childless_component(self):
        self.invalid(
            document({"type": "Text", "properties": {"text": "hi"},
                      "children": [{"type": "Text", "properties": {"text": "no"}}]}),
            "children under a component that does not accept them",
        )

    def test_accepts_children_where_the_vocabulary_allows_them(self):
        self.valid(
            document({"type": "Column", "children": [{"type": "Text", "properties": {"text": "hi"}}]}),
            "children under a container",
        )

    def test_rejects_an_undeclared_event_name(self):
        self.invalid(
            document({"type": "Text", "properties": {"text": "hi"},
                      "on": {"swipe": [{"action": "go", "url": "https://example.com"}]}}),
            "a binding for an event the component never declared",
        )

    def test_accepts_a_declared_event_name(self):
        self.valid(
            document({"type": "Text", "properties": {"text": "hi"},
                      "on": {"tap": [{"action": "go", "url": "https://example.com"}]}}),
            "a binding for a declared event",
        )

    def test_does_not_pretend_to_check_what_only_the_gate_can(self):
        # Authoring-time approximation: an expression's result type, an
        # ungranted action, and a reference to an undeclared state key all
        # pass here and fail at the gate. Pinned so nobody mistakes this
        # schema for the contract.
        self.valid(
            document({"type": "Text", "properties": {"text": {"$expr": "state.missing + 1"}},
                      "on": {"tap": [{"action": "neverGranted"}]}}),
            "checks that belong to the gate",
        )


class SuiteVocabulary(unittest.TestCase):
    """The repository's own vocabulary, and the documents shipped with it."""

    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("jsonschema not installed")

    def test_it_agrees_with_the_gate_except_where_it_means_to(self):
        """Every accepting vector in the suite validates, apart from two
        categories the schema is deliberately stricter about. Anything
        else diverging is a bug in the specialization."""
        import jsonschema

        vocabulary = json.loads(
            (ROOT / "conformance" / "examples" / "vocabulary.json").read_text()
        )
        validator = jsonschema.Draft202012Validator(
            gds.specialize(DOCUMENT_SCHEMA, vocabulary)
        )
        declared_types = set(vocabulary["components"])
        declared_properties = {
            name: set((component.get("properties") or {}))
            for name, component in vocabulary["components"].items()
        }

        def deliberate(node):
            """True when this subtree only breaks the schema in the two
            ways authoring-time strictness is meant to."""
            if not isinstance(node, dict):
                return False
            kind = node.get("type")
            if kind not in declared_types:
                return True  # unknown type: the skip and placeholder policies
            used = set(node.get("properties") or {})
            if used - declared_properties.get(kind, set()):
                return True  # undeclared property on a non-strict component
            return any(deliberate(child) for child in node.get("children") or [])

        accepted = strict_only = 0
        for path in sorted((ROOT / "conformance" / "examples").glob("*.json")):
            vector = json.loads(path.read_text())
            doc = vector.get("document")
            if not isinstance(doc, dict) or "expect" not in vector:
                continue
            if vector["expect"].get("error") is not None:
                continue
            errors = list(validator.iter_errors(doc))
            if not errors:
                accepted += 1
                continue
            self.assertTrue(
                deliberate(doc.get("root")),
                f"{path.name} diverges for an undocumented reason: {errors[0].message}",
            )
            strict_only += 1

        self.assertGreater(accepted, 0, "no accepting vectors validated")
        # The suite carries both kinds today; if it stops, this test has
        # quietly lost its teeth and should be revisited.
        self.assertGreater(strict_only, 0, "no deliberately-stricter vectors left in the suite")

    def test_the_two_deliberate_divergences_are_what_they_look_like(self):
        import jsonschema

        validator = jsonschema.Draft202012Validator(
            gds.specialize(DOCUMENT_SCHEMA, VOCABULARY)
        )
        # The gate reports an occurrence and builds; the schema flags it,
        # because at authoring time an undeclared property is a typo.
        undeclared = document({"type": "Text", "properties": {"text": "hi", "colour": "red"}})
        self.assertTrue(list(validator.iter_errors(undeclared)))
        # The gate can skip or placeholder an unknown type; the schema
        # closes the enum, because authoring against a vocabulary means
        # using the types it declares.
        unknown = document({"type": "Carousel"})
        self.assertTrue(list(validator.iter_errors(unknown)))


class CommandLine(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(TOOL), *args], capture_output=True, text=True, check=False
        )

    def test_writes_a_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            vocabulary_path = Path(directory) / "vocabulary.json"
            vocabulary_path.write_text(json.dumps(VOCABULARY))
            out = Path(directory) / "documents.schema.json"
            result = self.run_tool(str(vocabulary_path), "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            written = json.loads(out.read_text())
            self.assertIn("authoring@1.0.0", written["title"])

    def test_the_output_path_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            vocabulary_path = Path(directory) / "vocabulary.json"
            vocabulary_path.write_text(json.dumps(VOCABULARY))
            result = self.run_tool(str(vocabulary_path))
            self.assertNotEqual(result.returncode, 0)

    def test_a_missing_vocabulary_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_tool(
                str(Path(directory) / "absent.json"), "--out", str(Path(directory) / "s.json")
            )
            self.assertNotEqual(result.returncode, 0)

    def test_the_written_file_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            vocabulary_path = Path(directory) / "vocabulary.json"
            vocabulary_path.write_text(json.dumps(VOCABULARY))
            first, second = Path(directory) / "a.json", Path(directory) / "b.json"
            self.run_tool(str(vocabulary_path), "--out", str(first))
            self.run_tool(str(vocabulary_path), "--out", str(second))
            self.assertEqual(first.read_text(), second.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
