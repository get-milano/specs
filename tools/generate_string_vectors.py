#!/usr/bin/env python3
"""Generates the string-function conformance suite.

Composes type-correct expressions over the contract 2.1 string functions
(substring, indexOf, replace, split, join) from a pool of subjects and
needles chosen for their edges: empty strings, separators at the ends,
adjacent separators, needles that overlap themselves, indices outside the
string, and text outside the Basic Multilingual Plane, where a scalar
count and a UTF-16 code unit count disagree. Each is evaluated through the
reference checker and written as an ordinary vector into
conformance/generated-string/.

Seeded and deterministic: rerunning the tool reproduces the suite byte for
byte, so the vectors are committed, reviewable files. Every harness picks
the suite up automatically, since they iterate suite directories.

The reference checker is the oracle, exactly as in the numeric generator.
An engine that disagrees with a vector is wrong until the spec prose says
otherwise; every engine disagreeing identically means the checker is.

Run: python3 tools/generate_string_vectors.py
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_check import ReferenceGate, GateError  # noqa: E402

SEED = 20260831
COUNT = 220
ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "conformance" / "generated-string"

VOCABULARY = {
    "milano": "2.1.0",
    "name": "generated_string",
    "version": "1.0.0",
    "components": {
        "Text": {"properties": {"text": "string"}}
    }
}

# Subjects, as expression literals. The escaping matters: the grammar's
# string literal is single-quoted with \' and \\ as its only escapes.
SUBJECTS = [
    "''",                      # empty
    "'a'",
    "'abc'",
    "'hello world'",
    "'  padded  '",            # leading and trailing whitespace
    "',lead'",                 # separator first
    "'trail,'",                # separator last
    "'a,,b'",                  # adjacent separators
    "','",                     # the separator alone
    "'aaa'",                   # overlapping needles
    "'ababab'",
    "'4111111111111111'",      # the card number the sample masks
    "'ada@example.com'",
    "'\\'quoted\\''",          # an escaped quote
    "'\\\\'",                  # a lone backslash
    "'é'",               # combining acute: two scalars, one grapheme
    "'\U0001f600'",            # emoji: one scalar, two UTF-16 code units
    "'a\U0001f600b'",          # a surrogate pair between ASCII
    "'é'",                # precomposed acute: one scalar
    "'tab\tnewline\n'",
]

NEEDLES = [
    "''", "'a'", "'b'", "','", "'ab'", "'aa'", "'l'", "'o'", "' '",
    "'@'", "'.'", "'zz'", "'\U0001f600'", "'\\\\'", "'\\''",
]

REPLACEMENTS = ["''", "'-'", "'X'", "'ab'", "'\U0001f600'", "'..'"]

# Index expressions, including ones outside every subject, so the clamp is
# exercised from both ends and in the inverted order.
INDICES = [
    "0", "1", "2", "3", "4", "8", "12", "16", "99",
    "(0 - 1)", "(0 - 99)",
    "9223372036854775807",             # int64 max: clamps to the length
    "(0 - 9223372036854775807 - 1)",   # int64 min: clamps to zero
    "$length('abc')",
]


def build_expressions(rng):
    """A deterministic mix of shapes over the pools, every one a string so
    it can sit in a Text property without a conversion hiding the result."""
    expressions = []

    def subject():
        return rng.choice(SUBJECTS)

    def needle():
        return rng.choice(NEEDLES)

    while len(expressions) < COUNT * 4:
        shape = rng.randrange(9)
        if shape == 0:
            e = f"$substring({subject()}, {rng.choice(INDICES)}, {rng.choice(INDICES)})"
        elif shape == 1:
            e = f"$str($indexOf({subject()}, {needle()}))"
        elif shape == 2:
            e = f"$replace({subject()}, {needle()}, {rng.choice(REPLACEMENTS)})"
        elif shape == 3:
            e = f"$join($split({subject()}, {needle()}), {rng.choice(REPLACEMENTS)})"
        elif shape == 4:
            e = f"$str($length($split({subject()}, {needle()})))"
        elif shape == 5:
            # A split that round-trips: joining on the separator it split
            # by returns the subject, for every subject and separator.
            sep = needle()
            e = f"$join($split({subject()}, {sep}), {sep})"
        elif shape == 6:
            # substring composed with the length it clamps against.
            e = (f"$substring({subject()}, $indexOf({subject()}, {needle()}), "
                 f"$length({subject()}))")
        elif shape == 7:
            e = f"$str($isEmpty($split({subject()}, {needle()})))"
        else:
            # Nesting, where a bug in one function shows through another.
            e = (f"$replace($join($split({subject()}, {needle()}), "
                 f"{rng.choice(REPLACEMENTS)}), {needle()}, "
                 f"{rng.choice(REPLACEMENTS)})")
        expressions.append(e)
    return expressions


def vector_for(name, expression):
    document = {
        "version": "2.1.0",
        "root": {
            "type": "Text",
            "id": "r",
            "properties": {"text": {"$expr": expression}}
        }
    }
    gate = ReferenceGate(VOCABULARY, "fail")
    resolved, _ = gate.build({"name": name, "document": document,
                              "context": {}, "state": {}})
    return {
        "name": name,
        "description": f"Generated (seed {SEED}): {expression}",
        "document": document,
        "expect": {
            "view": resolved,
            "occurrences": gate.occurrences
        }
    }


def emit(expressions, prefix, count):
    """Writes up to `count` vectors, skipping duplicates. A GateError is a
    defect here, not a composition to skip: every shape above is typed by
    construction, so a refusal means the checker or the pools are wrong."""
    emitted, seen = 0, set()
    for expression in expressions:
        if emitted >= count:
            break
        if expression in seen:
            continue
        seen.add(expression)
        name = f"{prefix}{emitted:03d}"
        vector = vector_for(name, expression)
        with open(SUITE / f"{name}.json", "w") as handle:
            json.dump(vector, handle, indent=2)
            handle.write("\n")
        emitted += 1
    return emitted


def main():
    SUITE.mkdir(parents=True, exist_ok=True)
    for stale in SUITE.glob("*.json"):
        stale.unlink()

    with open(SUITE / "vocabulary.json", "w") as handle:
        json.dump(VOCABULARY, handle, indent=2)
        handle.write("\n")

    emitted = emit(build_expressions(random.Random(SEED)), "gen-string-", COUNT)
    print(f"generated {emitted} vectors into {SUITE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
