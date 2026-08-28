#!/usr/bin/env python3
"""Tests for tools/validate_suite.py.

The tool is the repository's structural gate: it proves the schemas are
valid JSON Schema, that every vocabulary and vector conforms to them, and
that the prose holds the no-em-dash rule. It runs on every push, and a
green run is the only evidence anyone has that the suite is well formed.

A gate that has stopped detecting anything still exits zero, so these
tests are mostly about the failure paths: each is driven by building a
deliberately broken repository in a temp directory and pointing the tool's
ROOT at it.

Run: python3 tools/test_validate_suite.py
"""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
TOOL = TOOLS / "validate_suite.py"

sys.path.insert(0, str(TOOLS))

try:
    import validate_suite as vs
except SystemExit:  # pragma: no cover - the tool exits when jsonschema is absent
    raise unittest.SkipTest("validate_suite.py requires the jsonschema package")


VOCABULARY = {
    "milano": "1.0.0",
    "name": "fixture",
    "version": "1.0.0",
    "components": {"Text": {"properties": {"text": "string"}}},
    "actions": {},
}

VECTOR = {
    "name": "fixture-hello",
    "description": "A minimal accepting vector.",
    "document": {
        "version": "1.0.0",
        "root": {"type": "Text", "id": "r", "properties": {"text": "hi"}},
    },
    "expect": {
        "view": {"type": "Text", "reference": "r",
                 "properties": {"text": "hi"}},
        "occurrences": [],
    },
}


class Fixture:
    """A throwaway repository the tool can be pointed at."""

    def __init__(self, directory):
        self.root = Path(directory)
        shutil.copytree(ROOT / "schemas", self.root / "schemas")
        self.suite = self.root / "conformance" / "fixture"
        self.suite.mkdir(parents=True)
        self.write_vocabulary(VOCABULARY)
        self.write_vector("hello", VECTOR)

    def write_vocabulary(self, value):
        (self.suite / "vocabulary.json").write_text(json.dumps(value, indent=2))

    def write_vector(self, name, value):
        (self.suite / f"{name}.json").write_text(json.dumps(value, indent=2))

    def write_markdown(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8")


class ValidateSuiteHarness(unittest.TestCase):
    """Runs the tool's main() against a fixture and captures the verdict."""

    @contextlib.contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            original = vs.ROOT
            fixture = Fixture(directory)
            vs.ROOT = fixture.root
            try:
                yield fixture
            finally:
                vs.ROOT = original

    def run_tool(self):
        """Returns (exit_code, output); 0 means the suite validated."""
        stdout = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(stdout):
            try:
                vs.main()
            except SystemExit as exit_:
                code = exit_.code
        return code, stdout.getvalue()


class AcceptsAWellFormedRepository(ValidateSuiteHarness):

    def test_a_clean_fixture_validates(self):
        with self.fixture():
            code, output = self.run_tool()
        self.assertEqual(code, 0, output)
        self.assertIn("suite valid", output)

    def test_it_reports_what_it_looked_at(self):
        # The counts are the only evidence the tool did any work, so they
        # are part of the contract rather than decoration.
        with self.fixture():
            _, output = self.run_tool()
        self.assertIn("conformance/fixture: vocabulary valid, 1/1 vectors valid",
                      output)
        self.assertRegex(output, r"schemas: \d+ valid")


class DetectsBrokenVectors(ValidateSuiteHarness):

    def test_a_vector_missing_a_required_key_is_reported(self):
        with self.fixture() as fixture:
            broken = {k: v for k, v in VECTOR.items() if k != "expect"}
            fixture.write_vector("broken", broken)
            code, output = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("conformance/fixture/broken.json", output)
        self.assertIn("'expect' is a required property", output)

    def test_a_vector_with_a_malformed_document_is_reported(self):
        # The vector schema binds the embedded document to the document
        # schema, so a defect inside `document` has to surface here too.
        with self.fixture() as fixture:
            broken = json.loads(json.dumps(VECTOR))
            broken["document"]["root"] = "not an object"
            fixture.write_vector("broken", broken)
            code, output = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("conformance/fixture/broken.json", output)

    def test_a_valid_vector_alongside_a_broken_one_still_counts(self):
        with self.fixture() as fixture:
            fixture.write_vector("broken", {"name": "x"})
            _, output = self.run_tool()
        self.assertIn("1/2 vectors valid", output)


class DetectsBrokenVocabularies(ValidateSuiteHarness):

    def test_a_vocabulary_missing_its_contract_version_is_reported(self):
        with self.fixture() as fixture:
            broken = {k: v for k, v in VOCABULARY.items() if k != "milano"}
            fixture.write_vocabulary(broken)
            code, output = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("vocabulary INVALID", output)
        self.assertIn("conformance/fixture/vocabulary.json", output)

    def test_a_vocabulary_with_a_malformed_component_is_reported(self):
        with self.fixture() as fixture:
            broken = json.loads(json.dumps(VOCABULARY))
            broken["components"]["Text"]["properties"]["text"] = 5
            fixture.write_vocabulary(broken)
            code, output = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("vocabulary INVALID", output)


class EnforcesTheStyleRule(ValidateSuiteHarness):
    """The em-dash rule: mechanical, and the only prose rule in CI."""

    def test_an_em_dash_in_markdown_fails_the_run(self):
        with self.fixture() as fixture:
            fixture.write_markdown("prose.md", "A sentence — with an em dash.\n")
            code, output = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("prose.md: contains an em dash", output)
        self.assertIn("0/1 files free of em dashes", output)

    def test_other_dashes_are_left_alone(self):
        # En dashes and hyphens are fine; only the em dash is banned, and a
        # rule that caught the others would be unusable.
        with self.fixture() as fixture:
            fixture.write_markdown("prose.md", "Ranges 1–2, well-formed.\n")
            code, output = self.run_tool()
        self.assertEqual(code, 0, output)
        self.assertIn("1/1 files free of em dashes", output)

    def test_markdown_in_dot_directories_is_skipped(self):
        # Vendored or tooling directories are not the repository's prose.
        with self.fixture() as fixture:
            hidden = fixture.root / ".vendor"
            hidden.mkdir()
            (hidden / "README.md").write_text("Third party — not ours.\n",
                                              encoding="utf-8")
            code, output = self.run_tool()
        self.assertEqual(code, 0, output)


class AgainstTheRepository(unittest.TestCase):
    """The real thing, run the way CI runs it."""

    def test_the_committed_repository_validates(self):
        result = subprocess.run([sys.executable, str(TOOL)],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        self.assertIn("suite valid", result.stdout)

    def test_every_markdown_file_is_actually_being_checked(self):
        # A glob that quietly stopped matching would report 0/0 and pass.
        result = subprocess.run([sys.executable, str(TOOL)],
                                cwd=ROOT, capture_output=True, text=True)
        line = next(l for l in result.stdout.splitlines() if l.startswith("markdown:"))
        checked = int(line.split()[1].split("/")[1])
        on_disk = len([p for p in ROOT.glob("**/*.md")
                       if not any(part.startswith(".")
                                  for part in p.relative_to(ROOT).parts[:-1])])
        self.assertEqual(checked, on_disk)
        self.assertGreater(checked, 5, line)



class EnginePinnedRegistry(unittest.TestCase):
    """The engine-pinned registry (conformance suite spec, Harness)."""

    def test_the_committed_registry_validates(self):
        self.assertEqual(vs.engine_pinned_problems(ROOT), [])

    def test_defects_are_named(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "conformance").mkdir()
            (root / "04-state-and-actions.md").write_text("## Completion\n")
            registry = {"statements": [
                {"id": "Bad Id", "spec": "04-state-and-actions.md", "section": "Completion",
                 "statement": "x", "applies": ["swiftui"]},
                {"id": "ok", "spec": "missing.md", "section": "Completion",
                 "statement": "x", "applies": ["swiftui"]},
                {"id": "ok", "spec": "04-state-and-actions.md", "section": "Nowhere",
                 "statement": "", "applies": ["ios"]},
            ]}
            (root / "conformance" / "engine-pinned.json").write_text(json.dumps(registry))
            problems = "\n".join(vs.engine_pinned_problems(root))
            for expected in ("kebab-case", "not a file", "duplicate id ok",
                             "not a heading", "non-empty", "applies must name"):
                self.assertIn(expected, problems)
            self.assertEqual(vs.engine_pinned_problems(root / "elsewhere"), [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
