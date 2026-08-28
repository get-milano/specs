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
import re
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


RUNTIMES = ("swiftui", "compose", "typescript")


def engine_pinned_problems(root):
    """The engine-pinned registry (conformance suite spec, Harness):
    statements no vector can express, pinned by a named test in every
    runtime they apply to. Ids are unique kebab-case, every spec named
    exists and carries the named section as a heading, and `applies`
    names known runtimes only. A missing registry is not a problem: a
    fixture repository may have none."""
    path = root / "conformance" / "engine-pinned.json"
    if not path.exists():
        return []
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        return [f"conformance/engine-pinned.json: {error}"]
    statements = registry.get("statements") if isinstance(registry, dict) else None
    if not isinstance(statements, list) or not statements:
        return ["conformance/engine-pinned.json: no statements"]
    problems, seen = [], set()
    for index, entry in enumerate(statements):
        where = f"conformance/engine-pinned.json: statements[{index}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: not an object")
            continue
        ident = entry.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", ident):
            problems.append(f"{where}: id must be kebab-case")
        elif ident in seen:
            problems.append(f"{where}: duplicate id {ident}")
        seen.add(ident)
        spec = entry.get("spec")
        if not isinstance(spec, str) or not (root / spec).is_file():
            problems.append(f"{where}: spec {spec!r} is not a file in the repository")
        elif not isinstance(entry.get("section"), str) or \
                f"## {entry['section']}" not in (root / spec).read_text(encoding="utf-8"):
            problems.append(f"{where}: section {entry.get('section')!r} is not a heading in {spec}")
        if not isinstance(entry.get("statement"), str) or not entry["statement"].strip():
            problems.append(f"{where}: statement must be non-empty")
        applies = entry.get("applies")
        if not isinstance(applies, list) or not applies or \
                any(runtime not in RUNTIMES for runtime in applies):
            problems.append(f"{where}: applies must name runtimes from {', '.join(RUNTIMES)}")
    return problems


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

    pinned = engine_pinned_problems(ROOT)
    problems.extend(pinned)
    if (ROOT / "conformance" / "engine-pinned.json").exists():
        print(f"engine-pinned registry: {'INVALID' if pinned else 'valid'}")

    if problems:
        print()
        print("\n".join(problems))
        sys.exit(1)
    print("suite valid")


if __name__ == "__main__":
    main()
