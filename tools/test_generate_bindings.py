#!/usr/bin/env python3
"""Tests for tools/generate_bindings.py.

Pure Python, no compilers: the specs repository stays engine-free, so
these check what can be checked from the text itself. Compiling the
generated code is the engine repositories' job, and the SDK does it: its
CI compiles the goldens under testdata/ against every engine
(scripts/verify-bindings.mjs), and the three samples compile what the
generator wrote for their vocabulary.

What is checked here:

- golden files, so a change to the generator is visible in review;
- that the emitters agree: every component, event and action reaches all
  three languages;
- that optionality survives, which is the whole point of the exercise: a
  declared non-optional must not come back nullable;
- determinism, balanced delimiters, and no Python leaking into the output;
- the CLI's contract, including its failure modes.

Run: python3 tools/test_generate_bindings.py
Refresh goldens: UPDATE_GOLDEN=1 python3 tools/test_generate_bindings.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
TESTDATA = TOOLS / "testdata"
GENERATOR = TOOLS / "generate_bindings.py"

sys.path.insert(0, str(TOOLS))

import generate_bindings as gb  # noqa: E402

FIXTURE = json.loads((TESTDATA / "bindings_fixture.json").read_text())
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


def golden(name, produced):
    """Compares against the committed output, or rewrites it on request."""
    path = TESTDATA / name
    if UPDATE:
        path.write_text(produced)
        return None
    return path.read_text()


class GoldenOutput(unittest.TestCase):
    """The generated text, byte for byte. Reviewable diffs on generator changes."""

    def test_swift(self):
        produced = gb.generate_swift(FIXTURE, "Fx")
        expected = golden("expected_bindings.swift", produced)
        if expected is not None:
            self.assertEqual(produced, expected)

    def test_kotlin(self):
        produced = gb.generate_kotlin(FIXTURE, "com.example.fixture", "")
        expected = golden("expected_bindings.kt", produced)
        if expected is not None:
            self.assertEqual(produced, expected)

    def test_typescript(self):
        produced = gb.generate_ts(FIXTURE, "Fx", "@get-milano/core")
        expected = golden("expected_bindings.ts", produced)
        if expected is not None:
            self.assertEqual(produced, expected)


class EveryEmitter(unittest.TestCase):
    """Properties that must hold in all three languages at once."""

    def outputs(self):
        """language -> (generated text, the type prefix it was given).

        Kotlin's prefix defaults to empty because its package already
        namespaces the types, which is how the Compose sample uses it; the
        assertions below account for that rather than assuming symmetry.
        """
        return {
            "swift": (gb.generate_swift(FIXTURE, "Fx"), "Fx"),
            "kotlin": (gb.generate_kotlin(FIXTURE, "com.example.fixture", ""), ""),
            "typescript": (gb.generate_ts(FIXTURE, "Fx", "@get-milano/core"), "Fx"),
        }

    def assertContains(self, produced, needle, message):
        """assertIn would print the whole generated file on failure."""
        self.assertTrue(needle in produced, message)

    def test_covers_every_component_property_and_event(self):
        for language, (produced, _) in self.outputs().items():
            for component, declaration in FIXTURE["components"].items():
                self.assertContains(produced, component, f"{language}: missing {component}")
                for prop in declaration.get("properties", {}):
                    self.assertContains(
                        produced, prop, f"{language}: {component}.{prop} missing"
                    )
                for event in declaration.get("events", {}):
                    self.assertContains(
                        produced,
                        gb.capitalize(event),
                        f"{language}: {component} {event} has no emitter",
                    )

    def test_covers_every_action_and_leaves_room_for_unknown_ones(self):
        for language, (produced, _) in self.outputs().items():
            for action in FIXTURE["actions"]:
                self.assertContains(produced, action, f"{language}: action {action} missing")
            # Swift spells it `unrecognized`, Kotlin `Unrecognized`.
            self.assertContains(
                produced.lower(), "unrecognized", f"{language}: no arm for undeclared actions"
            )

    def test_carries_the_vocabulary_identity(self):
        for language, (produced, _) in self.outputs().items():
            self.assertContains(produced, FIXTURE["name"], f"{language}: vocabulary name missing")
            self.assertContains(produced, FIXTURE["version"], f"{language}: version missing")

    def test_declares_one_type_per_enum_site(self):
        # Four sites: a property, an optional property, an event payload,
        # and an action parameter. Each gets its own nominal type, named
        # from the prefix that language was given.
        for language, (produced, prefix) in self.outputs().items():
            for site in ("WidgetLayout", "WidgetTone", "WidgetPickPayload", "SubmitMode"):
                self.assertContains(
                    produced, prefix + site, f"{language}: {prefix + site} missing"
                )

    def test_is_deterministic(self):
        first, second = self.outputs(), self.outputs()
        self.assertEqual(first, second)

    def test_has_balanced_delimiters(self):
        for language, (produced, _) in self.outputs().items():
            for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
                self.assertEqual(
                    produced.count(opener),
                    produced.count(closer),
                    f"{language}: unbalanced {opener}{closer}",
                )

    def test_leaks_no_python(self):
        for language, (produced, _) in self.outputs().items():
            for leak in ("None", "dict_keys", "0x7f", "<object"):
                self.assertTrue(
                    leak not in produced, f"{language}: Python leaked into the output ({leak})"
                )

    def test_generated_files_say_they_are_generated(self):
        for language, (produced, _) in self.outputs().items():
            first = produced.splitlines()[0]
            self.assertContains(first, "Generated from vocabulary", f"{language}: no provenance")
            self.assertContains(produced, "Do not edit", f"{language}: no warning against editing")


class Optionality(unittest.TestCase):
    """A declared non-optional must never come back nullable, and an
    optional must never come back non-nullable. This is the reason the
    generator exists, so it is checked per language rather than by
    coincidence of the goldens."""

    def test_swift(self):
        produced = gb.generate_swift(FIXTURE, "Fx")
        self.assertIn("public var title: String {", produced)
        self.assertIn("public var subtitle: String? {", produced)
        self.assertIn("public var count: Int64 {", produced)
        self.assertIn("public var ratio: Double? {", produced)
        self.assertIn("public var layout: FxWidgetLayout {", produced)
        self.assertIn("public var tone: FxWidgetTone? {", produced)

    def test_kotlin(self):
        produced = gb.generate_kotlin(FIXTURE, "com.example.fixture", "")
        self.assertRegex(produced, r"val title: String\b(?!\?)")
        self.assertRegex(produced, r"val subtitle: String\?")
        self.assertRegex(produced, r"val count: Long\b(?!\?)")
        self.assertRegex(produced, r"val ratio: Double\?")

    def test_typescript(self):
        produced = gb.generate_ts(FIXTURE, "Fx", "@get-milano/core")
        self.assertIn("get title(): string {", produced)
        self.assertIn("get subtitle(): string | null {", produced)
        self.assertIn("get count(): bigint {", produced)
        self.assertIn("get ratio(): number | null {", produced)
        self.assertIn("get layout(): FxWidgetLayout {", produced)
        self.assertIn("get tone(): FxWidgetLayout | null {".replace("Layout", "Tone"), produced)
        # A non-optional read asserts the type rather than defaulting: a
        # `?? ""` here would hide a gate violation behind an empty string.
        self.assertNotIn('?? ""', produced)


class TypeScriptShape(unittest.TestCase):
    """The TypeScript emitter's own contract, which has no compiler here
    to enforce it. The SDK compiles this output on every CI run; these
    checks are what catches an obvious break before it gets that far."""

    def setUp(self):
        self.produced = gb.generate_ts(FIXTURE, "Fx", "@get-milano/core")

    def test_imports_only_the_core_package(self):
        imports = re.findall(r'from "([^"]+)"', self.produced)
        self.assertEqual(set(imports), {"@get-milano/core"})

    def test_the_import_module_is_configurable(self):
        produced = gb.generate_ts(FIXTURE, "Fx", "../engine/ts/src/index.ts")
        self.assertIn('from "../engine/ts/src/index.ts"', produced)

    def test_describes_the_node_structurally(self):
        # Structural, so the file works with the React binding's MilanoNode
        # and with any other host wrapper, without importing a UI toolkit.
        self.assertIn("export interface MilanoNodeLike {", self.produced)
        self.assertIn("property(name: string): MilanoValue;", self.produced)

    def test_enums_are_string_literal_unions_in_sorted_order(self):
        # The fixture declares these out of order, so this pins sorting
        # rather than the order they happened to be written in: a
        # committed, diffed artifact must not move when a key does.
        self.assertIn('export type FxWidgetLayout = "compact" | "wide";', self.produced)
        self.assertIn('export type FxSubmitMode = "draft" | "final";', self.produced)

    def test_actions_are_a_discriminated_union_with_a_decoder(self):
        self.assertIn('| { readonly kind: "noop" }', self.produced)
        self.assertIn('readonly url: string', self.produced)
        self.assertIn('readonly referrer: string | null', self.produced)
        self.assertIn("export function fxAction(action: MilanoAction): FxAction {", self.produced)
        self.assertIn('return { kind: "unrecognized", action };', self.produced)

    def test_events_emit_typed_payloads(self):
        self.assertIn("emitTap(): void", self.produced)
        self.assertIn("emitChange(payload: string): void", self.produced)
        self.assertIn("emitResize(payload: bigint | null): void", self.produced)
        self.assertIn("emitPick(payload: FxWidgetPickPayload): void", self.produced)

    def test_a_result_declaration_is_documented(self):
        self.assertIn("bound to `result` in onSuccess", self.produced)

    def test_arrays_and_records(self):
        self.assertIn("get tags(): readonly string[] {", self.produced)
        self.assertIn("get payload(): FxWidgetPayload {", self.produced)
        self.assertIn("get items(): readonly FxWidgetItemsItem[] {", self.produced)


class Failures(unittest.TestCase):
    """The generator's own guardrails."""

    def test_enum_members_that_collide_when_capitalized_are_rejected(self):
        vocabulary = json.loads(json.dumps(FIXTURE))
        vocabulary["components"]["Widget"]["properties"]["layout"] = {"enum": ["wide", "Wide"]}
        with self.assertRaises(SystemExit):
            gb.generate_swift(vocabulary, "Fx")


class CommandLine(unittest.TestCase):
    """The CLI, exercised the way a build step uses it."""

    def run_generator(self, *args):
        return subprocess.run(
            [sys.executable, str(GENERATOR), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_writes_every_language_it_is_asked_for(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            result = self.run_generator(
                str(TESTDATA / "bindings_fixture.json"),
                "--swift-prefix", "Fx", "--swift-out", str(out / "b.swift"),
                "--kotlin-package", "com.example.fixture", "--kotlin-out", str(out / "b.kt"),
                "--ts-prefix", "Fx", "--ts-out", str(out / "b.ts"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("b.swift", "b.kt", "b.ts"):
                self.assertTrue((out / name).stat().st_size > 0, f"{name} is empty")

    def test_asking_for_nothing_is_an_error(self):
        result = self.run_generator(str(TESTDATA / "bindings_fixture.json"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("nothing to do", result.stderr)

    def test_kotlin_requires_a_package(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_generator(
                str(TESTDATA / "bindings_fixture.json"),
                "--kotlin-out", str(Path(directory) / "b.kt"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("--kotlin-package", result.stderr)

    def test_the_prefix_defaults_to_the_vocabulary_name(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "b.ts"
            result = self.run_generator(
                str(TESTDATA / "bindings_fixture.json"), "--ts-out", str(out)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("export type FixtureAction =", out.read_text())


class RealVocabularies(unittest.TestCase):
    """The conformance suite's own vocabularies, generated end to end. A
    fixture can be tuned to the generator; these were not."""

    def vocabularies(self):
        for path in sorted((ROOT / "conformance").glob("*/vocabulary.json")):
            yield path

    def test_every_suite_vocabulary_generates(self):
        seen = 0
        for path in self.vocabularies():
            vocabulary = json.loads(path.read_text())
            for language, produced in (
                ("swift", gb.generate_swift(vocabulary, "Suite")),
                ("kotlin", gb.generate_kotlin(vocabulary, "dev.getmilano.suite", "")),
                ("typescript", gb.generate_ts(vocabulary, "Suite", "@get-milano/core")),
            ):
                self.assertGreater(len(produced), 0, f"{path.name}/{language}: empty")
                self.assertEqual(
                    produced.count("{"), produced.count("}"), f"{path.name}/{language}: unbalanced"
                )
            seen += 1
        self.assertGreater(seen, 0, "no suite vocabularies found")


class Descriptors(unittest.TestCase):
    """`parse_descriptor` is the spine every emitter reads: each type
    descriptor the vocabulary schema permits has to come back with the
    right kind, optionality and element."""

    def test_scalars_and_their_optional_forms(self):
        for name in ("bool", "int", "double", "string"):
            self.assertEqual(gb.parse_descriptor(name), (name, False, None))
            self.assertEqual(gb.parse_descriptor(name + "?"), (name, True, None))

    def test_enum(self):
        self.assertEqual(gb.parse_descriptor({"enum": ["a"]}), ("enum", False, None))
        self.assertEqual(
            gb.parse_descriptor({"enum": ["a"], "optional": True}), ("enum", True, None)
        )

    def test_array_carries_its_element_kind(self):
        self.assertEqual(gb.parse_descriptor({"array": "string"}), ("array", False, "string"))
        self.assertEqual(gb.parse_descriptor({"array": "int?"}), ("array", False, "int"))
        self.assertEqual(
            gb.parse_descriptor({"array": "string", "optional": True}),
            ("array", True, "string"),
        )

    def test_an_array_of_non_scalars_names_its_element_kind(self):
        # The element kind is what sends the emitters to the record
        # wrapper path instead of the scalar accessors.
        self.assertEqual(
            gb.parse_descriptor({"array": {"record": {"a": "string"}}}),
            ("array", False, "record"),
        )

    def test_record(self):
        self.assertEqual(
            gb.parse_descriptor({"record": {"id": "string"}}), ("record", False, None)
        )
        self.assertEqual(
            gb.parse_descriptor({"record": {"id": "string"}, "optional": True}),
            ("record", True, None),
        )


class EnumSites(unittest.TestCase):
    """One nominal type per declaration site, deterministically ordered."""

    def test_two_structurally_identical_enums_get_their_own_types(self):
        # The contract compares enums structurally; the bindings name them
        # after where they are declared, so a later divergence at one site
        # cannot silently retype the other.
        vocabulary = {
            "milano": "1.0.0", "name": "twins", "version": "1.0.0",
            "components": {
                "A": {"properties": {"tone": {"enum": ["dark", "light"]}}},
                "B": {"properties": {"tone": {"enum": ["dark", "light"]}}},
            },
            "actions": {},
        }
        sites, lookup = gb.collect_enums(vocabulary, "Tw")
        self.assertEqual([name for name, _, _ in sites], ["TwATone", "TwBTone"])
        self.assertNotEqual(lookup[("property", "A", "tone")], lookup[("property", "B", "tone")])

    def test_sites_are_collected_in_a_fixed_order(self):
        # Components first, sorted, each contributing its properties then
        # its events; actions last. Deterministic, and not simply
        # alphabetical over the whole set: the file is committed and
        # diffed, so this order is part of the contract.
        sites, _ = gb.collect_enums(FIXTURE, "Fx")
        self.assertEqual(
            [name for name, _, _ in sites],
            ["FxWidgetLayout", "FxWidgetPayloadKind", "FxWidgetTone",
             "FxWidgetPickPayload", "FxSubmitMode", "FxSubmitFailure"],
        )

    def test_members_are_sorted_whatever_the_declaration_order(self):
        vocabulary = {
            "milano": "1.0.0", "name": "order", "version": "1.0.0",
            "components": {"A": {"properties": {"tone": {"enum": ["wide", "compact", "mid"]}}}},
            "actions": {},
        }
        sites, _ = gb.collect_enums(vocabulary, "Or")
        self.assertEqual(sites[0][1], ["compact", "mid", "wide"])


class RecordSites(unittest.TestCase):
    """One wrapper type per record declaration site, nesting through
    record fields and array elements, with typed field accessors whose
    optionality is the declared one and a memberwise constructor. Before
    these existed, a record-typed property, payload, or parameter came
    back as a raw MilanoValue, the one place the bindings stopped being
    typed."""

    def setUp(self):
        self.swift = gb.generate_swift(FIXTURE, "Fx")
        self.kotlin = gb.generate_kotlin(FIXTURE, "com.example.fixture", "")
        self.ts = gb.generate_ts(FIXTURE, "Fx", "@get-milano/core")

    def test_sites_are_collected_with_their_nesting(self):
        _, records, lookup = gb.collect_sites(FIXTURE, "Fx")
        names = [name for name, _, _, _ in records]
        self.assertEqual(
            names,
            ["FxWidgetItemsItem", "FxWidgetPayload", "FxWidgetPayloadOwner",
             "FxWidgetSubmitPayload", "FxOrderCart", "FxOrderNote", "FxOrderResult",
             "FxOrderFailure"],
        )
        self.assertEqual(lookup[("property", "Widget", "payload", "field", "owner")],
                         "FxWidgetPayloadOwner")
        self.assertEqual(lookup[("property", "Widget", "payload", "field", "kind")],
                         "FxWidgetPayloadKind")
        self.assertEqual(lookup[("property", "Widget", "items", "item")], "FxWidgetItemsItem")

    def test_swift_wrappers(self):
        self.assertIn("public struct FxWidgetPayload {", self.swift)
        self.assertIn("public init(_ value: MilanoValue) { self.value = value }", self.swift)
        self.assertIn("    public init(\n        id: String,\n        count: Int64?,\n"
                      "        kind: FxWidgetPayloadKind,\n        owner: FxWidgetPayloadOwner,\n"
                      "        labels: [String]?\n    ) {", self.swift)
        self.assertIn("public init(name: String) {", self.swift)
        self.assertIn("public var count: Int64? {", self.swift)
        self.assertIn("public var owner: FxWidgetPayloadOwner {", self.swift)
        self.assertIn("public var payload: FxWidgetPayload {", self.swift)
        self.assertIn("public var items: [FxWidgetItemsItem] {", self.swift)
        self.assertIn("case order(cart: FxOrderCart, note: FxOrderNote?)", self.swift)
        self.assertIn("public struct FxOrderResult {", self.swift)

    def test_kotlin_wrappers(self):
        self.assertIn("class WidgetPayload(", self.kotlin)
        self.assertRegex(self.kotlin, r"val count: Long\? get\(\)")
        self.assertRegex(self.kotlin, r"val owner: WidgetPayloadOwner get\(\)")
        self.assertIn("fun of(", self.kotlin)
        self.assertRegex(self.kotlin, r"val payload: WidgetPayload get\(\)")
        self.assertRegex(self.kotlin, r"val items: List<WidgetItemsItem> get\(\)")
        self.assertIn("val cart: OrderCart", self.kotlin)
        self.assertIn("val note: OrderNote?", self.kotlin)
        self.assertIn("class OrderResult(", self.kotlin)

    def test_typescript_wrappers(self):
        self.assertIn("export class FxWidgetPayload {", self.ts)
        self.assertIn("  static of(fields: {\n    readonly id: string;\n"
                      "    readonly count: bigint | null;\n    readonly kind: FxWidgetPayloadKind;\n"
                      "    readonly owner: FxWidgetPayloadOwner;\n"
                      "    readonly labels: readonly string[] | null;\n  }): FxWidgetPayload {", self.ts)
        self.assertIn("static of(fields: { readonly name: string }): FxWidgetPayloadOwner {", self.ts)
        self.assertIn("get count(): bigint | null {", self.ts)
        self.assertIn("get owner(): FxWidgetPayloadOwner {", self.ts)
        self.assertIn("readonly cart: FxOrderCart", self.ts)
        self.assertIn("readonly note: FxOrderNote | null", self.ts)
        self.assertIn("export class FxOrderResult {", self.ts)

    def test_no_declaration_site_is_left_untyped(self):
        for language, produced in (("swift", self.swift), ("kotlin", self.kotlin),
                                   ("typescript", self.ts)):
            self.assertNotIn("raw MilanoValue", produced, f"{language}: an untyped site remains")


class ReservedWords(unittest.TestCase):
    """A Milano identifier may be a keyword in the target language. The
    generator escapes the declaration and leaves the wire name alone;
    before it did, a vocabulary with a property called `class` produced
    Swift and Kotlin that could not compile."""

    VOCABULARY = {
        "milano": "1.0.0", "name": "keywords", "version": "1.0.0",
        "components": {
            "Object": {
                "properties": {"default": "string", "class": "int?", "val": "bool",
                               "object": "string?"},
                "events": {"in": None, "is": "string"},
            }
        },
        "actions": {"switch": {"parameters": {"if": "string", "url": "string?"}}, "when": {}},
    }

    def declarations(self, text, pattern):
        return re.findall(pattern, text)

    def test_swift_escapes_only_what_swift_reserves(self):
        produced = gb.generate_swift(self.VOCABULARY, "Kw")
        declared = self.declarations(produced, r"\b(?:var|case)\s+([A-Za-z_][A-Za-z0-9_]*)")
        offenders = [name for name in declared if name in gb.SWIFT_KEYWORDS]
        self.assertEqual(offenders, [], f"unescaped Swift keywords: {offenders}")
        self.assertIn("public var `class`:", produced)
        self.assertIn("case `switch`(", produced)
        # `val` is not a Swift keyword, so it is left alone: escaping
        # everything would be noise in generated code people read.
        self.assertIn("public var val:", produced)

    def test_kotlin_escapes_only_what_kotlin_reserves(self):
        produced = gb.generate_kotlin(self.VOCABULARY, "com.example", "")
        declared = self.declarations(produced, r"\bval\s+([A-Za-z_][A-Za-z0-9_]*)")
        offenders = [name for name in declared if name in gb.KOTLIN_KEYWORDS]
        self.assertEqual(offenders, [], f"unescaped Kotlin keywords: {offenders}")
        self.assertIn("val `class`:", produced)
        self.assertIn("val `val`:", produced)
        self.assertIn("`if` = action.parameters[\"if\"]", produced)
        # `default` is not a Kotlin keyword.
        self.assertIn("val default:", produced)

    def test_the_wire_name_is_never_escaped(self):
        for produced in (
            gb.generate_swift(self.VOCABULARY, "Kw"),
            gb.generate_kotlin(self.VOCABULARY, "com.example", ""),
            gb.generate_ts(self.VOCABULARY, "Kw", "@get-milano/core"),
        ):
            self.assertIn('property("class")', produced)
            self.assertNotIn('property("`class`")', produced)

    def test_typescript_needs_no_escaping(self):
        # Reserved words are legal as property and method names in
        # TypeScript, and every generated identifier is in that position.
        produced = gb.generate_ts(self.VOCABULARY, "Kw", "@get-milano/core")
        self.assertIn("get default(): string {", produced)
        self.assertIn("get class(): bigint | null {", produced)
        self.assertIn('readonly if: string', produced)
        # Backticks do appear, in doc comments and a template literal, but
        # never around a declared name.
        for escaped in ("get `", "`class`", "`default`", "`if`"):
            self.assertNotIn(escaped, produced, f"TypeScript should not escape: {escaped}")


class SparseVocabularies(unittest.TestCase):
    """Shapes a real vocabulary reaches on its first day."""

    def generate_all(self, vocabulary):
        return (
            gb.generate_swift(vocabulary, "Sp"),
            gb.generate_kotlin(vocabulary, "com.example.sparse", ""),
            gb.generate_ts(vocabulary, "Sp", "@get-milano/core"),
        )

    def test_a_vocabulary_with_no_actions(self):
        vocabulary = {
            "milano": "1.0.0", "name": "sparse", "version": "1.0.0",
            "components": {"Text": {"properties": {"text": "string"}}},
            "actions": {},
        }
        for produced in self.generate_all(vocabulary):
            self.assertGreater(len(produced), 0)
            self.assertEqual(produced.count("{"), produced.count("}"))
            # The unrecognized arm still exists: a builder can grant an
            # action the vocabulary never declared.
            self.assertIn("nrecognized", produced)

    def test_a_vocabulary_with_no_components(self):
        vocabulary = {
            "milano": "1.0.0", "name": "sparse", "version": "1.0.0",
            "components": {}, "actions": {"ping": {}},
        }
        for produced in self.generate_all(vocabulary):
            self.assertIn("ping", produced.lower())
            self.assertEqual(produced.count("{"), produced.count("}"))

    def test_a_component_with_neither_properties_nor_events(self):
        vocabulary = {
            "milano": "1.0.0", "name": "sparse", "version": "1.0.0",
            "components": {"Spacer": {}}, "actions": {},
        }
        for produced in self.generate_all(vocabulary):
            self.assertIn("Spacer", produced)

    def test_optional_arrays_and_record_payloads(self):
        vocabulary = {
            "milano": "1.0.0", "name": "sparse", "version": "1.0.0",
            "components": {
                "Widget": {
                    "properties": {"tags": {"array": "string", "optional": True}},
                    "events": {"submit": {"record": {"id": "string"}}},
                }
            },
            "actions": {},
        }
        swift, kotlin, ts = self.generate_all(vocabulary)
        self.assertIn("public var tags: [String]?", swift)
        self.assertIn("val tags: List<String>?", kotlin)
        self.assertIn("get tags(): readonly string[] | null {", ts)
        # A record payload gets a wrapper, and the emitter takes it.
        self.assertIn("emitSubmit(payload: SpWidgetSubmitPayload)", ts)
        self.assertIn("public func emitSubmit(_ payload: SpWidgetSubmitPayload)", swift)
        self.assertIn("fun emitSubmit(payload: WidgetSubmitPayload)", kotlin)


class SchemaCoverage(unittest.TestCase):
    """The fixture has to keep pace with the specification: when the
    vocabulary schema grows a descriptor form, this fails until the
    fixture exercises it."""

    def test_the_fixture_exercises_every_descriptor_form(self):
        schema_path = ROOT / "schemas" / "vocabulary.schema.json"
        schema = json.loads(schema_path.read_text())
        rendered = json.dumps(schema)
        forms = {
            '"array"': lambda text: '"array"' in text,
            '"record"': lambda text: '"record"' in text,
            '"enum"': lambda text: '"enum"' in text,
        }
        fixture_text = json.dumps(FIXTURE)
        for form, present in forms.items():
            if present(rendered):
                self.assertTrue(
                    present(fixture_text),
                    f"the schema allows {form} but the fixture never uses it",
                )

    def test_the_fixture_uses_every_scalar_the_schema_names(self):
        fixture_text = json.dumps(FIXTURE)
        for scalar in ("bool", "int", "double", "string"):
            self.assertIn(scalar, fixture_text, f"the fixture never declares a {scalar}")


class ResultDeclarations(unittest.TestCase):
    def test_an_action_without_a_result_gets_no_note(self):
        self.assertIsNone(gb.result_note({}))
        self.assertIsNone(gb.result_note({"parameters": {"a": "string"}}))

    def test_a_scalar_result_is_named_in_the_note(self):
        note = gb.result_note({"result": "string"})
        self.assertIn("`string`", note)
        self.assertIn("onSuccess", note)

    def test_a_structured_result_is_rendered_stably(self):
        note = gb.result_note({"result": {"enum": ["b", "a"]}})
        self.assertIn('"enum"', note)
        self.assertEqual(note, gb.result_note({"result": {"enum": ["b", "a"]}}))


class FailureDeclarations(unittest.TestCase):
    """Contract 2.1: a failure payload is a declaration site like a result,
    so it earns a doc note on the action and a nominal type when it is an
    enum or a record."""

    def test_an_action_without_a_failure_gets_no_note(self):
        self.assertIsNone(gb.failure_note({}))
        self.assertIsNone(gb.failure_note({"result": "string"}))

    def test_a_failure_is_named_in_the_note_with_how_to_raise_it(self):
        note = gb.failure_note({"failure": {"enum": ["b", "a"]}})
        self.assertIn('"enum"', note)
        self.assertIn("onFailure", note)
        self.assertIn("MilanoActionFailure", note)

    def test_both_notes_appear_in_a_fixed_order(self):
        notes = gb.action_notes({"result": "string", "failure": "int"})
        self.assertEqual(len(notes), 2)
        self.assertIn("result", notes[0])
        self.assertIn("failure", notes[1])

    def test_failure_sites_get_their_own_types_in_every_language(self):
        swift = gb.generate_swift(FIXTURE, "Fx")
        kotlin = gb.generate_kotlin(FIXTURE, "com.example.fixture", "")
        ts = gb.generate_ts(FIXTURE, "Fx", "@get-milano/core")
        self.assertIn("public enum FxSubmitFailure: String {", swift)
        self.assertIn("public struct FxOrderFailure {", swift)
        self.assertIn("enum class SubmitFailure(", kotlin)
        self.assertIn("class OrderFailure(", kotlin)
        self.assertIn('export type FxSubmitFailure = "offline" | "rejected";', ts)
        self.assertIn("export class FxOrderFailure {", ts)
        for produced in (swift, kotlin, ts):
            self.assertIn("bound to `failure` in onFailure", produced)


class CommandLineFailures(unittest.TestCase):
    def run_generator(self, *args):
        return subprocess.run(
            [sys.executable, str(GENERATOR), *args], capture_output=True, text=True, check=False
        )

    def test_a_missing_vocabulary_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_generator(
                str(Path(directory) / "absent.json"), "--ts-out", str(Path(directory) / "b.ts")
            )
            self.assertNotEqual(result.returncode, 0)

    def test_malformed_json_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "broken.json"
            broken.write_text("{ not json")
            result = self.run_generator(str(broken), "--ts-out", str(Path(directory) / "b.ts"))
            self.assertNotEqual(result.returncode, 0)


class Fixture(unittest.TestCase):
    def test_is_a_legal_vocabulary(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads((ROOT / "schemas" / "vocabulary.schema.json").read_text())
        jsonschema.Draft202012Validator(schema).validate(FIXTURE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
