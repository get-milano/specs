#!/usr/bin/env python3
"""Structural validation of the conformance suite and schemas.

Checks that every schema in schemas/ is itself a valid 2020-12 JSON Schema,
validates each suite's vocabulary.json against the vocabulary meta-schema and
every vector against the vector schema (which binds embedded documents to the
document schema), and enforces the repository's no-em-dash style rule on
Markdown files.

Requires the jsonschema package (pip install jsonschema). Semantic checking
of vector expectations lives in tools/reference_check.py.
"""

import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import best_match
    from referencing import Registry, Resource
except ImportError:
    print("validate_suite.py requires the jsonschema package: "
          "pip install jsonschema", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent


def main():
    schemas = {}
    for path in sorted((ROOT / "schemas").glob("*.schema.json")):
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        schemas[schema["$id"]] = schema
    print(f"schemas: {len(schemas)} valid ({', '.join(sorted(schemas))})")

    registry = Registry().with_resources(
        (sid, Resource.from_contents(s)) for sid, s in schemas.items())
    vocab_validator = Draft202012Validator(
        schemas["vocabulary.schema.json"], registry=registry)
    vector_validator = Draft202012Validator(
        schemas["vector.schema.json"], registry=registry)

    problems = []
    for suite in sorted((ROOT / "conformance").iterdir()):
        if not suite.is_dir():
            continue
        vocab = json.loads((suite / "vocabulary.json").read_text())
        vocab_error = best_match(vocab_validator.iter_errors(vocab))
        if vocab_error:
            problems.append(f"{suite.relative_to(ROOT)}/vocabulary.json: "
                            f"{vocab_error.json_path}: {vocab_error.message}")
        vectors, failed = 0, 0
        for path in sorted(suite.glob("*.json")):
            if path.name == "vocabulary.json":
                continue
            vectors += 1
            vector = json.loads(path.read_text())
            error = best_match(vector_validator.iter_errors(vector))
            if error:
                failed += 1
                problems.append(f"{path.relative_to(ROOT)}: "
                                f"{error.json_path}: {error.message}")
        print(f"{suite.relative_to(ROOT)}: vocabulary "
              f"{'INVALID' if vocab_error else 'valid'}, "
              f"{vectors - failed}/{vectors} vectors valid")

    markdown, dashes = 0, 0
    for path in ROOT.glob("**/*.md"):
        if any(part.startswith(".") for part in path.relative_to(ROOT).parts[:-1]):
            continue
        markdown += 1
        if "—" in path.read_text(encoding="utf-8"):
            dashes += 1
            problems.append(f"{path.relative_to(ROOT)}: contains an em dash")
    print(f"markdown: {markdown - dashes}/{markdown} files free of em dashes")

    if problems:
        print()
        print("\n".join(problems))
        sys.exit(1)
    print("suite valid")


if __name__ == "__main__":
    main()
