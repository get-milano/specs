#!/usr/bin/env python3
"""Generates the typing-rule conformance suite.

The numeric suite pins what expressions compute; this one pins what the
gate accepts. Every rule in the expression spec's "Typing and totality"
section is a family here: declared-position acceptance (T where T? is
expected, int where double, an enum where a string, a literal refined into
an enum position), `??`, `if`, `==`, arithmetic, the function signatures,
and field access. Each family is a small pool of operands enumerated
exhaustively, in a fixed order, and every (expression, target property)
pair is run through the reference gate: the outcome decides whether the
pair becomes an accepting or a rejecting vector.

Accepting pairs are packed twelve to a document, each on its own node, so
an engine that disagrees still names the node. Rejecting pairs are one
per vector, because the gate stops at the first defect. There is no seed:
the grammar is the whole input, so the suite is reproducible byte for
byte and a change to it is a reviewable diff.

The reference checker is the oracle, as for the numeric suite. The two
divergences this suite exists for (an `if` over a `T?` and a `T` branch,
an `int` expression in a `double` position) were both depth-one pairs in
this grammar and went unnoticed for a release because nothing generated
them.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_check import Checker, ExprError, GateError, Parser, ReferenceGate  # noqa: E402
from reference_check import parse_type, tokenize  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "conformance" / "generated-typing"
PACK = 12

# One property per declared kind, optional and not; the targets.
TARGETS = {
    "s": "string", "sOpt": "string?",
    "i": "int", "iOpt": "int?",
    "d": "double", "dOpt": "double?",
    "b": "bool", "bOpt": "bool?",
    "e": {"enum": ["a", "b"]},
    "eOpt": {"enum": ["a", "b"], "optional": True},
}

VOCABULARY = {
    "milano": "1.0.0",
    "name": "generated_typing",
    "version": "1.0.0",
    "components": {
        "Column": {"children": True},
        "Probe": {"properties": dict(TARGETS)},
    },
}

# The state a document may read: every kind again, plus a second enum with
# a different member set (distinct enums never mix) and two records (field
# access needs a non-optional record).
STATE = dict(TARGETS)
STATE.update({
    "e2": {"enum": ["a", "c"]},
    "r": {"record": {"f": "string", "g": "int?"}},
    "rOpt": {"record": {"f": "string"}, "optional": True},
})

# Optionals are null so `??` and `if` fallbacks are exercised.
VALUES = {
    "s": "x", "sOpt": None, "i": 7, "iOpt": None, "d": 2.5, "dOpt": None,
    "b": True, "bOpt": None, "e": "a", "eOpt": None, "e2": "c",
    "r": {"f": "rf", "g": None}, "rOpt": None,
}

# Operand pools. Every string is expression text.
REFS = ["state.s", "state.sOpt", "state.i", "state.iOpt", "state.d", "state.dOpt",
        "state.b", "state.bOpt", "state.e", "state.eOpt", "state.e2",
        "state.r.f", "state.r.g"]
LITERALS = ["'x'", "'a'", "'z'", "1", "1.5", "true", "null"]
SCALARS = ["state.s", "state.sOpt", "state.e", "state.e2", "state.i", "state.d", "state.b"]
# Optional operands: comparable only to null, never to a value or another
# optional (expression spec, Operators); the pairs pin both directions.
OPTIONAL_SCALARS = ["state.iOpt", "state.bOpt"]


def unordered_pairs(pool):
    return [(pool[a], pool[b]) for a in range(len(pool)) for b in range(a, len(pool))]


def families():
    """family name -> expressions, in the order they are emitted."""
    yield "position", REFS + LITERALS
    yield "coalesce", [f"{left} ?? {right}"
                       for left in ["state.sOpt", "state.iOpt", "state.dOpt", "state.eOpt",
                                    "state.bOpt", "state.s", "null"]
                       for right in ["'x'", "'a'", "'z'", "1", "1.5", "true",
                                     "state.s", "state.i", "state.e", "state.sOpt"]]
    branches = ["state.s", "state.sOpt", "state.e", "state.i", "state.d",
                "'a'", "'z'", "null", "state.sOpt ?? 'y'"]
    yield "branch", ([f"if(state.b, {then}, {otherwise})"
                      for then in branches for otherwise in branches]
                     + ["if(state.bOpt, 'x', 'y')", "if(1, 'x', 'y')",
                        "if(state.b, null, null)"])
    yield "equality", [f"{left} == {right}"
                       for left, right in unordered_pairs(SCALARS + OPTIONAL_SCALARS + ["'x'", "'a'", "'z'", "1",
                                                                     "null", "state.r"])]
    yield "arithmetic", ([f"{left} + {right}"
                          for left, right in unordered_pairs(["state.s", "state.e", "state.i",
                                                              "state.d", "state.iOpt", "'x'", "1"])]
                         + [f"-{operand}" for operand in ["state.i", "state.d", "state.iOpt",
                                                          "state.s"]]
                         + [f"!{operand}" for operand in ["state.b", "state.bOpt", "state.i"]]
                         + ["state.i < state.d", "state.s < state.s", "state.i < state.iOpt"])
    call_operands = ["state.s", "state.sOpt", "state.e", "state.i", "state.iOpt",
                     "state.d", "state.b", "'a'", "1", "1.5", "null"]
    yield "call", ([f"{function}({operand})"
                    for function in ["str", "length", "isEmpty", "trim", "int", "double"]
                    for operand in call_operands]
                   + [f"concat({operand}, 'y')" for operand in call_operands]
                   + ["concat('x')", "str(state.s, state.s)", "nope(1)", "contains(state.e, 'a')"])
    yield "access", ["state.r.f", "state.r.g", "state.rOpt.f", "state.s.f", "state.r.h",
                     "state.missing", "state", "context", "nope", "event", "result"]


# Where an expression that does not type on its own is placed: the slot its
# family would fill if the rule it breaks did not exist. A rejection there
# pins the rule itself; in a mismatched slot it could be the slot.
FALLBACK_TARGET = {
    "position": "s", "coalesce": "s", "branch": "sOpt", "equality": "b",
    "arithmetic": "s", "call": "s", "access": "s",
}


def candidate_targets(ty, family="position"):
    """The declared positions worth pinning for an expression of static
    type `ty`: its own kind and the optional flip (T versus T?), and the
    promotions, widenings, and refinements the spec names. A plainly wrong
    kind is not listed; the handwritten gate vectors cover that once."""
    if ty is None:
        return [FALLBACK_TARGET[family]]
    if ty.kind == "null":
        return ["sOpt", "s"]
    return {
        "string": ["s", "sOpt", "e"],
        "enum": ["e", "eOpt", "s"],
        "int": ["i", "iOpt", "d", "dOpt"],
        "double": ["d", "dOpt", "i"],
        "bool": ["b", "bOpt"],
    }.get(ty.kind, ["s"])


def static_type(expression):
    """The expression's type with no expectation, or None when it does
    not type-check on its own."""
    try:
        ast = Parser(tokenize(expression)).parse()
        return Checker({k: parse_type(v) for k, v in STATE.items()}, {}).check(ast)
    except ExprError:
        return None


def referenced_keys(expressions):
    keys = set()
    for expression in expressions:
        keys.update(re.findall(r"\bstate\.([A-Za-z][A-Za-z0-9_]*)", expression))
    return sorted(key for key in keys if key in STATE)


def document(nodes):
    """A Column of Probe nodes, each carrying one expression in one target,
    declaring only the state the expressions read."""
    keys = referenced_keys(expression for _, expression, _ in nodes)
    root = {
        "type": "Column",
        "id": "root",
        "children": [
            {"type": "Probe", "id": node_id,
             "properties": {target: {"$expr": expression}}}
            for node_id, expression, target in nodes
        ],
    }
    doc = {"version": "1.0.0"}
    if keys:
        doc["state"] = {key: STATE[key] for key in keys}
    doc["root"] = root
    return doc, {key: VALUES[key] for key in keys}


def build(doc, state):
    gate = ReferenceGate(VOCABULARY, "fail")
    resolved, _ = gate.build({"name": "generated", "document": doc,
                              "context": {}, "state": state})
    return resolved, gate.occurrences


def classify(expression, target):
    """Accept (resolved node) or reject (error fields) for one pair."""
    doc, state = document([("p", expression, target)])
    try:
        resolved, occurrences = build(doc, state)
    except GateError as error:
        return "reject", error.fields
    return "accept", (resolved, occurrences)


def type_name(descriptor):
    return repr(parse_type(descriptor))


def vectors():
    """Every vector, in emission order: (name, vector)."""
    for family, expressions in families():
        accepted, rejected = [], []
        for expression in expressions:
            for target in candidate_targets(static_type(expression), family):
                verdict, detail = classify(expression, target)
                if verdict == "accept":
                    accepted.append((expression, target))
                else:
                    rejected.append((expression, target, detail))

        for chunk in range(0, len(accepted), PACK):
            group = accepted[chunk:chunk + PACK]
            nodes = [(f"p{index}", expression, target)
                     for index, (expression, target) in enumerate(group)]
            doc, state = document(nodes)
            resolved, occurrences = build(doc, state)
            name = f"gen-typing-{family}-accept-{chunk // PACK:03d}"
            listing = "; ".join(f"{node_id}: {expression} in {target}"
                                for node_id, expression, target in nodes)
            vector = {
                "name": name,
                "description": f"Generated (exhaustive): accepted in their declared positions. {listing}",
                "document": doc,
            }
            if state:
                vector["state"] = state
            vector["expect"] = {"view": resolved, "occurrences": occurrences}
            yield name, vector

        for index, (expression, target, fields) in enumerate(rejected):
            doc, state = document([("p", expression, target)])
            name = f"gen-typing-{family}-reject-{index:03d}"
            expect = {"type": fields["type"]}
            for key in ("rule", "node", "expected"):
                if key in fields:
                    expect[key] = fields[key]
            vector = {
                "name": name,
                "description": (f"Generated (exhaustive): {expression} in a "
                                f"{type_name(TARGETS[target])} position is rejected at the gate"),
                "document": doc,
                "expect": {"error": expect},
            }
            yield name, vector


def main():
    SUITE.mkdir(parents=True, exist_ok=True)
    for stale in SUITE.glob("*.json"):
        stale.unlink()
    with open(SUITE / "vocabulary.json", "w") as handle:
        json.dump(VOCABULARY, handle, indent=2)
        handle.write("\n")

    emitted = 0
    for name, vector in vectors():
        with open(SUITE / f"{name}.json", "w") as handle:
            json.dump(vector, handle, indent=2)
            handle.write("\n")
        emitted += 1
    print(f"generated {emitted} vectors into {SUITE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
