#!/usr/bin/env python3
"""Generates the numeric-determinism conformance suite.

Composes small, type-correct expressions from a pool of boundary constants
(int64 edges, the 2^53 precision cliff, signed zero, NaN and infinity
producers, the str() exponent-window edges) and evaluates each through the
reference checker, emitting ordinary conformance vectors into
conformance/generated-numeric/. Seeded and deterministic: rerunning the
tool reproduces the suite byte for byte, so the vectors are committed,
reviewable files. Both engines pick the suite up automatically, since
harnesses iterate every suite directory.

The reference checker is the oracle. If an engine disagrees with a
generated vector, the spec prose arbitrates which of the two is wrong;
if both engines disagree identically, the checker is the suspect.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_check import ReferenceGate, GateError  # noqa: E402

SEED = 20260816
COUNT = 150
ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "conformance" / "generated-numeric"

VOCABULARY = {
    "milano": "1.0.0",
    "name": "generated_numeric",
    "version": "1.0.0",
    "components": {
        "Text": {"properties": {"text": "string"}}
    }
}

# Leaf expressions by type. Every entry parses and type-checks on its own.
INT_LEAVES = [
    "0", "1", "2", "3", "7", "10", "100",
    "(0 - 1)", "(0 - 7)",
    "9223372036854775807",              # int64 max
    "(0 - 9223372036854775807 - 1)",    # int64 min
    "4611686018427387904",              # 2^62
    "9007199254740993",                 # 2^53 + 1: unrepresentable as double
]
DOUBLE_LEAVES = [
    "0.0", "1.0", "0.5", "2.0", "3.0", "0.1", "123.456",
    "-(0.0)",                            # signed zero
    "(0.0 / 0.0)",                       # NaN
    "(1.0 / 0.0)",                       # +infinity
    "(0.0 - 1.0) / 0.0",                 # -infinity
    "1000000000000000.0",                # str() plain-decimal upper edge
    "0.0001", "0.00001",                 # str() scientific lower edge
    "9007199254740992.0",                # 2^53
    "9223372036854775807.0",             # rounds to 2^63: saturation edge
]
ARITHMETIC = ["+", "-", "*", "/", "%"]
COMPARISONS = ["<", "<=", ">", ">=", "==", "!="]


def build_expressions(rng):
    """A deterministic mix of shapes over the leaf pools."""
    expressions = []

    def int_expr():
        if rng.random() < 0.35:
            return f"({rng.choice(INT_LEAVES)} {rng.choice(ARITHMETIC)} {rng.choice(INT_LEAVES)})"
        return rng.choice(INT_LEAVES)

    def double_expr():
        if rng.random() < 0.35:
            return f"({rng.choice(DOUBLE_LEAVES)} {rng.choice(ARITHMETIC)} {rng.choice(DOUBLE_LEAVES)})"
        return rng.choice(DOUBLE_LEAVES)

    def numeric_expr():
        return int_expr() if rng.random() < 0.5 else double_expr()

    while len(expressions) < COUNT * 3:
        shape = rng.randrange(6)
        if shape == 0:      # pure arithmetic, wrapped for display
            e = f"str({numeric_expr()} {rng.choice(ARITHMETIC)} {numeric_expr()})"
        elif shape == 1:    # comparison across promotion
            e = f"str({numeric_expr()} {rng.choice(COMPARISONS)} {numeric_expr()})"
        elif shape == 2:    # conversion: double to int (saturation territory)
            e = f"str(int({double_expr()}))"
        elif shape == 3:    # conversion: int to double (rounding territory)
            e = f"str(double({int_expr()}))"
        elif shape == 4:    # nested arithmetic
            e = f"str(({numeric_expr()} {rng.choice(ARITHMETIC)} {numeric_expr()}) {rng.choice(ARITHMETIC)} {numeric_expr()})"
        else:               # round-trip formatting of a computed double
            e = f"str({double_expr()} {rng.choice(['+', '-', '*', '/'])} {double_expr()})"
        expressions.append(e)
    return expressions


def vector_for(name, expression):
    document = {
        "version": "1.0.0",
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


def main():
    rng = random.Random(SEED)
    SUITE.mkdir(parents=True, exist_ok=True)
    for stale in SUITE.glob("*.json"):
        stale.unlink()

    with open(SUITE / "vocabulary.json", "w") as handle:
        json.dump(VOCABULARY, handle, indent=2)
        handle.write("\n")

    emitted, seen = 0, set()
    for expression in build_expressions(rng):
        if emitted >= COUNT:
            break
        if expression in seen:
            continue
        seen.add(expression)
        name = f"gen-numeric-{emitted:03d}"
        try:
            vector = vector_for(name, expression)
        except GateError:
            continue  # type mismatch by composition; skip, keep determinism
        except Exception:
            continue
        with open(SUITE / f"{name}.json", "w") as handle:
            json.dump(vector, handle, indent=2)
            handle.write("\n")
        emitted += 1

    print(f"generated {emitted} vectors into {SUITE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
