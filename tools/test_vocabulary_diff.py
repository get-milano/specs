#!/usr/bin/env python3
"""Tests for tools/vocabulary_diff.py.

The tool decides whether a vocabulary change is additive or breaking, and
whether the version bump matches. Producers gate publication on it, so a
misclassification either blocks a legitimate release or lets a breaking
change reach consumers as a minor. Both directions are checked here.

Run: python3 tools/test_vocabulary_diff.py
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
TOOL = TOOLS / "vocabulary_diff.py"

sys.path.insert(0, str(TOOLS))

import vocabulary_diff as vd  # noqa: E402


def vocabulary(version="1.0.0", components=None, actions=None, name="example"):
    return {
        "milano": "1.0.0",
        "name": name,
        "version": version,
        "components": components if components is not None else {},
        "actions": actions if actions is not None else {},
    }


def verdicts(old, new):
    """The classifications only, for comparing without message wording."""
    return sorted(verdict for verdict, _ in vd.diff(old, new))


def messages(old, new):
    return [message for _, message in vd.diff(old, new)]


class Semver(unittest.TestCase):
    def test_accepts_major_minor_patch(self):
        self.assertEqual(vd.semver("1.2.3"), (1, 2, 3))
        self.assertEqual(vd.semver("0.0.0"), (0, 0, 0))
        self.assertEqual(vd.semver("10.20.30"), (10, 20, 30))

    def test_rejects_everything_else(self):
        for text in ("1.2", "1.2.3.4", "x.y.z", "1.2.x", "", "v1.2.3"):
            self.assertIsNone(vd.semver(text), f"{text!r} should not parse")

    def test_prereleases_do_not_parse(self):
        # Documented consequence: a vocabulary versioned `1.1.0-rc.1`
        # cannot be diffed, and the tool says so rather than guessing at
        # an ordering for it.
        self.assertIsNone(vd.semver("1.1.0-rc.1"))


class TypeRepresentation(unittest.TestCase):
    def test_is_stable_across_key_order(self):
        self.assertEqual(
            vd.type_repr({"enum": ["a"], "optional": True}),
            vd.type_repr({"optional": True, "enum": ["a"]}),
        )

    def test_distinguishes_optionality(self):
        self.assertNotEqual(vd.type_repr("string"), vd.type_repr("string?"))

    def test_enum_members_are_read_with_their_optionality(self):
        self.assertEqual(vd.enum_members({"enum": ["b", "a"]}), ({"a", "b"}, False))
        self.assertEqual(
            vd.enum_members({"enum": ["a"], "optional": True}), ({"a"}, True)
        )
        self.assertIsNone(vd.enum_members("string"))
        self.assertIsNone(vd.enum_members({"array": "string"}))


class Components(unittest.TestCase):
    def test_adding_a_component_is_additive(self):
        old = vocabulary(components={"A": {}})
        new = vocabulary(components={"A": {}, "B": {}})
        self.assertEqual(verdicts(old, new), ["ADDITIVE"])
        self.assertIn("component B added", messages(old, new))

    def test_removing_a_component_is_breaking(self):
        old = vocabulary(components={"A": {}, "B": {}})
        new = vocabulary(components={"A": {}})
        self.assertEqual(verdicts(old, new), ["BREAKING"])
        self.assertIn("component B removed", messages(old, new))

    def test_accepting_children_is_additive_and_refusing_them_is_breaking(self):
        without = vocabulary(components={"A": {}})
        with_children = vocabulary(components={"A": {"children": True}})
        self.assertEqual(verdicts(without, with_children), ["ADDITIVE"])
        self.assertEqual(verdicts(with_children, without), ["BREAKING"])

    def test_becoming_strict_is_breaking_and_relaxing_is_additive(self):
        lenient = vocabulary(components={"A": {}})
        strict = vocabulary(components={"A": {"strict": True}})
        self.assertEqual(verdicts(lenient, strict), ["BREAKING"])
        self.assertIn("component A became strict", messages(lenient, strict))
        self.assertEqual(verdicts(strict, lenient), ["ADDITIVE"])


class Properties(unittest.TestCase):
    def component(self, properties):
        return vocabulary(components={"A": {"properties": properties}})

    def test_adding_a_property_is_additive(self):
        old, new = self.component({"a": "string"}), self.component({"a": "string", "b": "int"})
        self.assertEqual(verdicts(old, new), ["ADDITIVE"])

    def test_removing_a_property_is_breaking(self):
        old, new = self.component({"a": "string", "b": "int"}), self.component({"a": "string"})
        self.assertEqual(verdicts(old, new), ["BREAKING"])

    def test_retyping_a_property_is_breaking(self):
        old, new = self.component({"a": "string"}), self.component({"a": "int"})
        self.assertEqual(verdicts(old, new), ["BREAKING"])
        self.assertIn("type changed", messages(old, new)[0])

    def test_changing_optionality_is_breaking_in_both_directions(self):
        required, optional = self.component({"a": "string"}), self.component({"a": "string?"})
        # Both directions retype the property, and the tool does not try to
        # reason about which documents survive: the spec's rule is that a
        # type change needs a major bump.
        self.assertEqual(verdicts(required, optional), ["BREAKING"])
        self.assertEqual(verdicts(optional, required), ["BREAKING"])

    def test_an_enum_gaining_members_is_additive(self):
        old = self.component({"a": {"enum": ["one"]}})
        new = self.component({"a": {"enum": ["one", "two"]}})
        self.assertEqual(verdicts(old, new), ["ADDITIVE"])
        self.assertIn("enum gained: two", messages(old, new)[0])

    def test_an_enum_losing_members_is_breaking(self):
        old = self.component({"a": {"enum": ["one", "two"]}})
        new = self.component({"a": {"enum": ["one"]}})
        self.assertEqual(verdicts(old, new), ["BREAKING"])

    def test_an_enum_that_gains_and_loses_is_breaking(self):
        old = self.component({"a": {"enum": ["one", "two"]}})
        new = self.component({"a": {"enum": ["one", "three"]}})
        self.assertEqual(verdicts(old, new), ["BREAKING"])

    def test_an_enum_changing_optionality_is_breaking_even_with_the_same_members(self):
        old = self.component({"a": {"enum": ["one"]}})
        new = self.component({"a": {"enum": ["one"], "optional": True}})
        self.assertEqual(verdicts(old, new), ["BREAKING"])

    def test_reordering_enum_members_is_not_a_change(self):
        old = self.component({"a": {"enum": ["one", "two"]}})
        new = self.component({"a": {"enum": ["two", "one"]}})
        self.assertEqual(vd.diff(old, new), [])

    def test_reordering_declarations_is_not_a_change(self):
        old = self.component({"a": "string", "b": "int"})
        new = self.component({"b": "int", "a": "string"})
        self.assertEqual(vd.diff(old, new), [])


class Events(unittest.TestCase):
    def component(self, events):
        return vocabulary(components={"A": {"events": events}})

    def test_adding_an_event_is_additive(self):
        old, new = self.component({"tap": None}), self.component({"tap": None, "hold": None})
        self.assertEqual(verdicts(old, new), ["ADDITIVE"])

    def test_removing_an_event_is_breaking(self):
        old, new = self.component({"tap": None, "hold": None}), self.component({"tap": None})
        self.assertEqual(verdicts(old, new), ["BREAKING"])

    def test_giving_a_payloadless_event_a_payload_is_breaking(self):
        old, new = self.component({"tap": None}), self.component({"tap": "string"})
        self.assertEqual(verdicts(old, new), ["BREAKING"])

    def test_an_event_payload_enum_gaining_members_is_additive(self):
        old = self.component({"pick": {"enum": ["one"]}})
        new = self.component({"pick": {"enum": ["one", "two"]}})
        self.assertEqual(verdicts(old, new), ["ADDITIVE"])


class Actions(unittest.TestCase):
    def test_adding_an_action_is_additive(self):
        old, new = vocabulary(actions={"a": {}}), vocabulary(actions={"a": {}, "b": {}})
        self.assertEqual(verdicts(old, new), ["ADDITIVE"])

    def test_removing_an_action_is_breaking(self):
        old, new = vocabulary(actions={"a": {}, "b": {}}), vocabulary(actions={"a": {}})
        self.assertEqual(verdicts(old, new), ["BREAKING"])

    def test_adding_a_parameter_is_additive(self):
        old = vocabulary(actions={"a": {"parameters": {"x": "string"}}})
        new = vocabulary(actions={"a": {"parameters": {"x": "string", "y": "int?"}}})
        self.assertEqual(verdicts(old, new), ["ADDITIVE"])

    def test_removing_or_retyping_a_parameter_is_breaking(self):
        old = vocabulary(actions={"a": {"parameters": {"x": "string"}}})
        self.assertEqual(verdicts(old, vocabulary(actions={"a": {}})), ["BREAKING"])
        retyped = vocabulary(actions={"a": {"parameters": {"x": "int"}}})
        self.assertEqual(verdicts(old, retyped), ["BREAKING"])

    def test_a_result_declaration_is_not_compared(self):
        # Known limitation, pinned so a future change to it is deliberate:
        # only parameters are diffed, so adding or changing `result` reads
        # as no change at all.
        old = vocabulary(actions={"a": {}})
        new = vocabulary(actions={"a": {"result": "string"}})
        self.assertEqual(vd.diff(old, new), [])


class Combinations(unittest.TestCase):
    def test_a_change_set_reports_every_change(self):
        old = vocabulary(
            components={"A": {"properties": {"x": "string"}}, "Gone": {}},
            actions={"kept": {}},
        )
        new = vocabulary(
            components={"A": {"properties": {"x": "int", "y": "string?"}}, "New": {}},
            actions={"kept": {}, "added": {}},
        )
        found = verdicts(old, new)
        self.assertEqual(found.count("BREAKING"), 2)  # retyped x, removed Gone
        self.assertEqual(found.count("ADDITIVE"), 3)  # added y, New, added

    def test_an_unchanged_vocabulary_has_no_changes(self):
        artifact = vocabulary(
            components={"A": {"properties": {"x": "string"}, "events": {"tap": None}}},
            actions={"go": {"parameters": {"url": "string"}}},
        )
        self.assertEqual(vd.diff(artifact, json.loads(json.dumps(artifact))), [])


class CommandLine(unittest.TestCase):
    """The gate as CI uses it: the exit code is the whole point."""

    def run_diff(self, old, new):
        with tempfile.TemporaryDirectory() as directory:
            old_path = Path(directory) / "old.json"
            new_path = Path(directory) / "new.json"
            old_path.write_text(json.dumps(old))
            new_path.write_text(json.dumps(new))
            return subprocess.run(
                [sys.executable, str(TOOL), str(old_path), str(new_path)],
                capture_output=True, text=True, check=False,
            )

    def test_no_changes_passes(self):
        artifact = vocabulary(components={"A": {}})
        result = self.run_diff(artifact, artifact)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no declaration changes", result.stdout)

    def test_additive_with_a_minor_bump_passes(self):
        old = vocabulary("1.0.0", components={"A": {}})
        new = vocabulary("1.1.0", components={"A": {}, "B": {}})
        result = self.run_diff(old, new)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verdict: ok (0 breaking, 1 additive)", result.stdout)

    def test_additive_with_only_a_patch_bump_fails(self):
        old = vocabulary("1.0.0", components={"A": {}})
        new = vocabulary("1.0.1", components={"A": {}, "B": {}})
        result = self.run_diff(old, new)
        self.assertEqual(result.returncode, 1)
        self.assertIn("require at least a MINOR bump", result.stderr)

    def test_additive_without_a_bump_fails(self):
        old = vocabulary("1.0.0", components={"A": {}})
        new = vocabulary("1.0.0", components={"A": {}, "B": {}})
        result = self.run_diff(old, new)
        self.assertEqual(result.returncode, 1)
        self.assertIn("version did not increase", result.stderr)

    def test_breaking_with_a_minor_bump_fails(self):
        old = vocabulary("1.0.0", components={"A": {}, "B": {}})
        new = vocabulary("1.1.0", components={"A": {}})
        result = self.run_diff(old, new)
        self.assertEqual(result.returncode, 1)
        self.assertIn("require a MAJOR bump", result.stderr)

    def test_breaking_with_a_major_bump_passes(self):
        old = vocabulary("1.4.2", components={"A": {}, "B": {}})
        new = vocabulary("2.0.0", components={"A": {}})
        result = self.run_diff(old, new)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verdict: ok (1 breaking, 0 additive)", result.stdout)

    def test_a_version_going_backwards_fails(self):
        old = vocabulary("2.0.0", components={"A": {}})
        new = vocabulary("1.0.0", components={"A": {}, "B": {}})
        result = self.run_diff(old, new)
        self.assertEqual(result.returncode, 1)

    def test_renaming_the_vocabulary_fails(self):
        old = vocabulary("1.0.0", name="before")
        new = vocabulary("2.0.0", name="after")
        result = self.run_diff(old, new)
        self.assertEqual(result.returncode, 1)
        self.assertIn("vocabulary name changed", result.stderr)

    def test_an_unparseable_version_fails(self):
        old = vocabulary("1.0.0")
        new = vocabulary("1.1.0-rc.1", components={"A": {}})
        result = self.run_diff(old, new)
        self.assertEqual(result.returncode, 1)
        self.assertIn("major.minor.patch", result.stderr)

    def test_the_wrong_number_of_arguments_is_a_usage_error(self):
        result = subprocess.run(
            [sys.executable, str(TOOL)], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)

    def test_every_change_is_printed_with_its_verdict(self):
        old = vocabulary("1.0.0", components={"A": {"properties": {"x": "string"}}})
        new = vocabulary("2.0.0", components={"A": {"properties": {"x": "int", "y": "int?"}}})
        result = self.run_diff(old, new)
        self.assertIn("BREAKING", result.stdout)
        self.assertIn("ADDITIVE", result.stdout)


class SuiteVocabulary(unittest.TestCase):
    """The repository's own artifact, against itself and against edits."""

    def load(self):
        return json.loads((ROOT / "conformance" / "examples" / "vocabulary.json").read_text())

    def test_is_unchanged_against_itself(self):
        artifact = self.load()
        self.assertEqual(vd.diff(artifact, self.load()), [])

    def test_dropping_one_of_its_components_reads_as_breaking(self):
        old = self.load()
        new = self.load()
        removed = sorted(new["components"])[0]
        del new["components"][removed]
        self.assertIn(("BREAKING", f"component {removed} removed"), vd.diff(old, new))

    def test_adding_an_optional_property_reads_as_additive(self):
        old = self.load()
        new = self.load()
        component = sorted(new["components"])[0]
        new["components"][component].setdefault("properties", {})["addedLater"] = "string?"
        self.assertEqual(verdicts(old, new), ["ADDITIVE"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
