#!/usr/bin/env python3
"""Generates the validation-order conformance suite.

The document model fixes the gate's order: parse, version, vocabulary
requirement, limits, then one walk over the tree in document order with a
fixed order of checks per node, then the data checks, so that a document
violating several rules fails identically everywhere. The handwritten
suite pins a few pairs; this one pins them all. Every gate violation is an
injector that plants exactly one defect in a shared base document (an
envelope-level defect, or a node-level one on either of two sibling
nodes), every pair of injectors is composed into one document, and the
reference gate decides which error wins. Node-level pairs are emitted in
both orders, first on the earlier sibling and then on the later one, so
the "first defect in document order wins" rule is pinned too.

No seed: the injector catalog is the whole input, the run is reproducible
byte for byte, and a change is a reviewable diff. A defect that is
schema-invalid by construction (an envelope violation) is carried as
`documentText`, per the conformance suite spec.
"""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_check import GateError, ReferenceGate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "conformance" / "generated-order"

VOCABULARY = {
    "milano": "1.0.0",
    "name": "generated_order",
    "version": "1.0.0",
    "components": {
        "Column": {"children": True},
        "Text": {"properties": {"text": "string"}},
        "Button": {"properties": {"label": "string", "enabled": "bool"},
                   "events": {"tap": None}},
        "Meta": {"properties": {"key": "string"}, "strict": True},
    },
    "actions": {"openUrl": {"parameters": {"url": "string"}}},
}


def base():
    """The shared document: a Column with two Button siblings, `a` before
    `b`, so a node-level defect can land on either and document order is
    observable."""
    return {
        "config": {},
        "context": {},
        "state": {},
        "document": {
            "version": "1.0.0",
            "root": {"type": "Column", "id": "root", "children": [
                {"type": "Button", "id": "a", "properties": {"label": "A", "enabled": True}},
                {"type": "Button", "id": "b", "properties": {"label": "B", "enabled": True}},
            ]},
        },
    }


# --- Envelope-level injectors, in the order the gate checks them. Each takes
# the whole vector. The third element says whether the defect is invisible
# to the document schema (False) or an envelope violation it rejects (True).

def malformed_id(v):
    v["document"]["root"]["id"] = ""


def unsupported_version(v):
    v["document"]["version"] = "9.0.0"


def vocabulary_requirement(v):
    v["document"]["vocabulary"] = {"name": "other"}


def depth_limit(v):
    v["config"].setdefault("limits", {})["maxTreeDepth"] = 1


def node_count_limit(v):
    v["config"].setdefault("limits", {})["maxNodeCount"] = 2


def context_missing(v):
    v["document"].setdefault("context", {})["who"] = "string"


def state_mismatch(v):
    v["document"].setdefault("state", {})["n"] = "int"
    v["state"]["n"] = "x"


def value_size(v):
    v["document"].setdefault("context", {})["big"] = "string"
    v["context"]["big"] = "0123456789"
    v["config"].setdefault("limits", {})["maxValueSize"] = 4


ENVELOPE = [
    ("malformed-id", malformed_id, True),
    ("unsupported-version", unsupported_version, False),
    ("vocabulary-requirement", vocabulary_requirement, False),
    ("depth-limit", depth_limit, False),
    ("node-count-limit", node_count_limit, False),
    ("context-missing", context_missing, False),
    ("state-mismatch", state_mismatch, False),
    ("value-size", value_size, False),
]


# --- Node-level injectors, in the walk's per-node order. Each takes the
# node it lands on and the whole vector.

def id_duplicate(n, v):
    n["id"] = "root"


def construct(n, v):
    n["type"] = "$Button"


def unknown_type(n, v):
    n["type"] = "Mystery"


def undeclared_property(n, v):
    n["type"] = "Meta"
    n["properties"] = {"key": "k", "extra": 1}


def property_type(n, v):
    n["properties"]["label"] = 1


def expression(n, v):
    n["properties"]["label"] = {"$expr": "state.nope"}


def contract_feature(n, v):
    # A contract 2.1 function in the base document, which declares 1.0.
    n["properties"]["label"] = {"$expr": "$str($abs(1))"}


def children(n, v):
    n["children"] = [{"type": "Text", "id": n["id"] + "-child", "properties": {"text": "x"}}]


def event_binding(n, v):
    n["on"] = {"nope": []}


def action_encoding(n, v):
    n["on"] = {"tap": [{"action": "$set", "key": "undeclared", "value": 1}]}


def action_capability(n, v):
    n["on"] = {"tap": [{"action": "secret"}]}


def no_handler(n, v):
    n["on"] = {"tap": [{"action": "openUrl", "url": "https://example.com"}]}
    v["config"]["actionHandler"] = False


NODE = [
    ("id-duplicate", id_duplicate),
    ("construct", construct),
    ("unknown-type", unknown_type),
    ("undeclared-property", undeclared_property),
    ("property-type", property_type),
    ("expression", expression),
    ("contract-feature", contract_feature),
    ("children", children),
    ("event-binding", event_binding),
    ("action-encoding", action_encoding),
    ("action-capability", action_capability),
    ("no-handler", no_handler),
]


def verdict(vector):
    """The reference gate's error for a vector, as expectation fields."""
    config = vector.get("config", {})
    gate = ReferenceGate(VOCABULARY, "fail", config.get("actions"),
                         config.get("limits"), config)
    try:
        gate.build(vector)
    except GateError as error:
        fields = error.fields
        expect = {"type": fields["type"]}
        # A MalformedDocument's location detail is non-normative (document
        # model spec, error taxonomy): the type alone is the pin.
        if fields["type"] == "MalformedDocument":
            return expect
        for key in ("rule", "node", "expected", "found", "limit", "value", "actual"):
            if key in fields:
                expect[key] = fields[key]
        return expect
    raise SystemExit(f"{vector['name']}: the injected defects were not detected")


def finish(name, description, vector, schema_invalid):
    """Trims empty sections, carries a schema-invalid document as text, and
    attaches the reference gate's verdict."""
    out = {"name": name, "description": description}
    if vector["config"]:
        out["config"] = vector["config"]
    if schema_invalid:
        out["documentText"] = json.dumps(vector["document"])
    else:
        out["document"] = vector["document"]
    for section in ("context", "state"):
        if vector[section]:
            out[section] = vector[section]
    probe = dict(out)
    out["expect"] = {"error": verdict(probe)}
    return name, out


def node_at(vector, index):
    return vector["document"]["root"]["children"][index]


def vectors():
    """Every vector, in emission order: (name, vector)."""
    # Each injector alone, so a reviewer sees what it plants.
    for name, inject, invalid in ENVELOPE:
        v = base()
        inject(v)
        yield finish(f"gen-order-{name}-alone",
                     f"Generated (order): {name} alone", v, invalid)
    for name, inject in NODE:
        v = base()
        inject(node_at(v, 0), v)
        yield finish(f"gen-order-{name}-alone",
                     f"Generated (order): {name} alone, on node a", v, False)

    # Envelope pairs: both defects, in either order of application.
    for i, (first, inject_first, invalid_first) in enumerate(ENVELOPE):
        for second, inject_second, invalid_second in ENVELOPE[i + 1:]:
            v = base()
            inject_first(v)
            inject_second(v)
            yield finish(f"gen-order-{first}-and-{second}",
                         f"Generated (order): {first} and {second} in one document; "
                         f"the gate's order decides which error wins",
                         v, invalid_first or invalid_second)

    # An envelope defect beside a node defect on node a.
    for first, inject_first, invalid in ENVELOPE:
        for second, inject_second in NODE:
            v = base()
            inject_first(v)
            inject_second(node_at(v, 0), v)
            yield finish(f"gen-order-{first}-and-{second}",
                         f"Generated (order): {first} beside {second} on node a; "
                         f"the gate's order decides which error wins",
                         v, invalid)

    # Two node defects on the two siblings, both orders: the earlier
    # sibling's defect wins whatever the rules are.
    for first, inject_first in NODE:
        for second, inject_second in NODE:
            if first == second:
                continue
            v = base()
            inject_first(node_at(v, 0), v)
            inject_second(node_at(v, 1), v)
            yield finish(f"gen-order-{first}-then-{second}",
                         f"Generated (order): {first} on node a, then {second} on node b; "
                         f"the first defect in document order wins",
                         v, False)


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
