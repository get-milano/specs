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
if every engine disagrees identically, the checker is the suspect.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_check import ReferenceGate, GateError  # noqa: E402

SEED = 20260816
COUNT = 150
# A second, separately seeded batch for the numeric functions contract 2.1
# added (abs, min, max, floor, ceil, round), in documents declaring 2.1, so
# the first batch stays byte for byte what it was.
FUNCTION_SEED = 20260830
FUNCTION_COUNT = 60
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
            e = f"$str({numeric_expr()} {rng.choice(ARITHMETIC)} {numeric_expr()})"
        elif shape == 1:    # comparison across promotion
            e = f"$str({numeric_expr()} {rng.choice(COMPARISONS)} {numeric_expr()})"
        elif shape == 2:    # conversion: double to int (saturation territory)
            e = f"$str($int({double_expr()}))"
        elif shape == 3:    # conversion: int to double (rounding territory)
            e = f"$str($double({int_expr()}))"
        elif shape == 4:    # nested arithmetic
            e = f"$str(({numeric_expr()} {rng.choice(ARITHMETIC)} {numeric_expr()}) {rng.choice(ARITHMETIC)} {numeric_expr()})"
        else:               # round-trip formatting of a computed double
            e = f"$str({double_expr()} {rng.choice(['+', '-', '*', '/'])} {double_expr()})"
        expressions.append(e)
    return expressions


def build_function_expressions(rng):
    """The contract 2.1 batch: the numeric functions over the same leaf
    pools, so their signed-zero, tie, wrapping, and non-finite edges are
    composed rather than hand-picked."""
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

    while len(expressions) < FUNCTION_COUNT * 3:
        shape = rng.randrange(6)
        if shape == 0:      # magnitude, either type
            e = f"$str($abs({numeric_expr()}))"
        elif shape == 1:    # extremum across promotion, two or three arguments
            function = rng.choice(["$min", "$max"])
            arguments = [numeric_expr() for _ in range(rng.choice([2, 3]))]
            e = f"$str({function}({', '.join(arguments)}))"
        elif shape == 2:    # rounding of a composed double
            e = f"$str({rng.choice(['$floor', '$ceil', '$round'])}({double_expr()}))"
        elif shape == 3:    # rounding then conversion: saturation territory
            e = f"$str($int({rng.choice(['$floor', '$ceil', '$round'])}({double_expr()})))"
        elif shape == 4:    # extremum fed into arithmetic
            e = f"$str({rng.choice(['$min', '$max'])}({numeric_expr()}, {numeric_expr()}) {rng.choice(ARITHMETIC)} {numeric_expr()})"
        else:               # nested: magnitude of a rounding, or the reverse
            if rng.random() < 0.5:
                e = f"$str($abs({rng.choice(['$floor', '$ceil', '$round'])}({double_expr()})))"
            else:
                e = f"$str({rng.choice(['$floor', '$ceil', '$round'])}($abs({double_expr()})))"
        expressions.append(e)
    return expressions


def vector_for(name, expression, version="1.0.0", seed=SEED):
    document = {
        "version": version,
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
        "description": f"Generated (seed {seed}): {expression}",
        "document": document,
        "expect": {
            "view": resolved,
            "occurrences": gate.occurrences
        }
    }


def emit(expressions, prefix, count, version, seed):
    """Writes up to `count` vectors from the pool, skipping duplicates and
    type-mismatched compositions; returns how many were written."""
    emitted, seen = 0, set()
    for expression in expressions:
        if emitted >= count:
            break
        if expression in seen:
            continue
        seen.add(expression)
        name = f"{prefix}{emitted:03d}"
        # Only a type mismatch is skipped. Anything else is a defect in the
        # checker and has to surface: a bare except here once hid a crash on
        # `inf % x`, and with it every vector that would have pinned it.
        try:
            vector = vector_for(name, expression, version, seed)
        except GateError:
            continue  # type mismatch by composition; skip, keep determinism
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

    emitted = emit(build_expressions(random.Random(SEED)), "gen-numeric-",
                   COUNT, "1.0.0", SEED)
    emitted += emit(build_function_expressions(random.Random(FUNCTION_SEED)),
                    "gen-numeric-fn-", FUNCTION_COUNT, "2.1.0", FUNCTION_SEED)

    print(f"generated {emitted} vectors into {SUITE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
