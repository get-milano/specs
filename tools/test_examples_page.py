#!/usr/bin/env python3
"""Tests that every document printed in examples.md is a valid document.

The worked examples are read as the friendly face of the specification, and
they were the one place where a document could rot unnoticed: the vectors
are executed, the schemas are validated, the prose is proofread, and the
JSON on that page was checked by nobody. A rule renamed or a feature gated
differently would leave the page teaching something the gate refuses.

Every fenced `json` block on the page is built here through the reference
gate, against the same `examples` vocabulary the suite uses, with context
and state synthesized as a producer's `milano validate` does.

Run: python3 tools/test_examples_page.py
"""

import json
import re
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent

sys.path.insert(0, str(TOOLS))

import reference_check as rc  # noqa: E402

VOCABULARY = json.loads((ROOT / "conformance" / "examples" / "vocabulary.json").read_text())
FENCED_JSON = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


def documents():
    """Every fenced JSON block on the page, with the heading it sits under."""
    text = (ROOT / "examples.md").read_text()
    # A block belongs to the last heading before it, which is what a failure
    # message needs to name.
    found, current = [], "the page"
    position = 0
    for match in FENCED_JSON.finditer(text):
        for line in text[position:match.start()].splitlines():
            if line.startswith("## "):
                current = line[3:].strip()
        position = match.end()
        found.append((current, match.group(1)))
    return found


class ExamplesPage(unittest.TestCase):
    def test_the_page_shows_at_least_the_documents_it_promises(self):
        self.assertGreaterEqual(
            len(documents()), 4, "banner, contact form, shopping list, quick actions")

    def test_every_document_on_the_page_builds(self):
        for heading, source in documents():
            with self.subTest(heading=heading):
                document = json.loads(source)
                gate = rc.ReferenceGate(VOCABULARY, "fail")
                # No host is present, so a declared function answers with the
                # zero value of its return type, exactly as `milano validate`
                # does for a producer.
                gate.function_results = None
                context = rc.synthesized_values(document.get("context", {}))
                state = rc.synthesized_values(document.get("state", {}))
                try:
                    gate.build({"name": heading, "document": document,
                                "context": context, "state": state})
                except rc.GateError as error:
                    self.fail(f"{heading}: the gate refuses this document: {error.fields}")

    def test_no_document_on_the_page_reports_an_unknown_key(self):
        # The gate ignores unknown keys in contract-governed objects by rule,
        # so a typo on the page would render as prose and never fail a build.
        for heading, source in documents():
            with self.subTest(heading=heading):
                warnings = rc.unknown_key_warnings(json.loads(source))
                self.assertEqual(warnings, [], f"{heading}: {warnings}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
