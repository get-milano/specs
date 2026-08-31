#!/usr/bin/env python3
"""Reference checker for conformance vectors.

Executes step-free vectors against a minimal reference implementation of the
gate and the expression language, derived from specs 01-03, and compares the
outcome with the vector's expectation. This is a vector linter, not a runtime:
the spec prose stays normative, and a disagreement between this checker and a
vector is a defect in one of them, to be resolved by a human.

Scope: parse, version, limits, vocabulary validation, expression parsing and
type checking, cross-checks, and evaluation of the resolved tree for vectors
without steps. Vectors with steps exercise the runtime's dispatch machinery;
executing their steps is the engines' territory, but they are statically
linted here: the build must succeed, action lists must be well-formed and
type-correct (with the event, result, and failure roots bound to their
declared types), each step must be structurally valid, and an invalid or
unbound emission must be matched by the occurrence the vector expects.

Pure stdlib. Integer arithmetic is emulated at 64 bits; doubles are Python
floats, which are IEEE 754 binary64.
"""

import json
import math
import re
import sys
from pathlib import Path

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1
# Per contract major, the highest minor this checker implements (Foundations,
# Versioning). A document's patch never matters.
SUPPORTED_VERSIONS = {1: 0, 2: 1}
SUPPORTED_MAJORS = set(SUPPORTED_VERSIONS)

# Features a minor introduced, by the name the `contract-feature` detail
# carries (document model spec, Validation): a document declaring an
# earlier minor of the same major may not use them. Functions and roots
# are met inside expressions; `key` and `on` by the gate's walk.
FUNCTION_FEATURES = {f"${name}": (2, 1)
                     for name in ("abs", "min", "max", "floor", "ceil", "round",
                                  "substring", "indexOf", "replace", "split", "join")}
ROOT_FEATURES = {"failure": (2, 1)}
# The array actions (document model spec, Actions) and the top-level
# sections, gated the same way; a host function call is gated by the
# function's own name (expression spec, Host functions).
ACTION_FEATURES = {"$append": (2, 1), "$remove": (2, 1), "$update": (2, 1)}
# Construct node types, gated in their own namespace: `$if` is a construct
# here and a built-in function in expressions, two things in two
# namespaces, and only the construct arrived with 2.1.
CONSTRUCT_FEATURES = {"$if": (2, 1), "$switch": (2, 1)}
# Expression syntax a minor introduced, by the spelling a document uses.
EXPRESSION_FEATURES = {"[]": (2, 1)}
SECTION_FEATURES = {"on": (2, 1), "watch": (2, 1)}
HOST_FUNCTION_FEATURE = (2, 1)
LIFECYCLE_SIGNALS = ("appear", "disappear")
# Each array action's parameters, in the lexicographic order the walk
# visits them (document model spec, Validation).
ARRAY_ACTION_KEYS = {"$append": ("key", "value"),
                     "$remove": ("at", "key"),
                     "$update": ("at", "field", "key", "value")}


def supported_ranges():
    """The error detail's spelling of the ranges: "1.0", "2.1"."""
    return [f"{major}.{minor}" for major, minor in sorted(SUPPORTED_VERSIONS.items())]


def contract_text(contract):
    """The `contract-feature` detail's spelling of a version: "2.1"."""
    return f"{contract[0]}.{contract[1]}"
MAX_TREE_DEPTH = 32
MAX_NODE_COUNT = 10_000
MAX_EXPRESSION_LENGTH = 1_024
MAX_DOCUMENT_BYTES = 1_048_576
MAX_VALUE_SIZE = 65_536

# The document model's defaults, by the names the error detail and a
# vector's config.limits use.
DEFAULT_LIMITS = {
    "maxTreeDepth": MAX_TREE_DEPTH,
    "maxNodeCount": MAX_NODE_COUNT,
    "maxDocumentBytes": MAX_DOCUMENT_BYTES,
    "maxExpressionLength": MAX_EXPRESSION_LENGTH,
    "maxValueSize": MAX_VALUE_SIZE,
}


def count_resolved(node):
    """Nodes in a resolved tree, the node count limit's runtime measure."""
    return 1 + sum(count_resolved(child) for child in node.get("children", []))


def value_size(value):
    """The document model's value size: one per scalar or null, one per
    Unicode scalar of a string, and one plus the sizes of the elements or
    fields for an array or record. Python strings are sequences of code
    points, so len() is the scalar count."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return 1 + sum(value_size(element) for element in value)
    if isinstance(value, dict):
        return 1 + sum(value_size(field) for field in value.values())
    return 1

# The explicit Unicode White_Space table from the expression spec.
WHITE_SPACE = set(
    "\u0009\u000a\u000b\u000c\u000d\u0020\u0085\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008"
    "\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _identifier(name):
    """The one identifier grammar: an ASCII letter, then ASCII letters,
    digits, or underscores. Unicode letters and digits are not letters and
    digits here, exactly as in the expression grammar and the schemas;
    str.isalpha would accept what every engine rejects."""
    return isinstance(name, str) and _IDENTIFIER.match(name) is not None


def _semver(text):
    """Parse x.y.z into a comparable tuple; malformed sorts lowest."""
    parts = str(text).split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return tuple(int(p) for p in parts)
    return (-1, -1, -1)


def sorted_keys(value):
    """The document model's member order: every JSON object visited in
    lexicographic key order (document model spec, Validation), arrays in
    their own order. Applied once to a document and a vocabulary, so every
    walk below inherits it."""
    if isinstance(value, dict):
        return {key: sorted_keys(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [sorted_keys(element) for element in value]
    return value


class GateError(Exception):
    """A typed gate error; fields mirror the error taxonomy's detail."""

    def __init__(self, type_, **fields):
        super().__init__(type_)
        self.fields = {"type": type_, **fields}


# ---------------------------------------------------------------------------
# Types. Kind is one of bool/int/double/string/enum/array/record/null.
# ---------------------------------------------------------------------------


class Ty:
    def __init__(self, kind, optional=False, elem=None, fields=None,
                 members=None):
        self.kind = kind
        self.optional = optional
        self.elem = elem
        self.fields = fields
        self.members = members

    def __repr__(self):
        return self.kind + ("?" if self.optional else "")


SCALARS = ("bool", "int", "double", "string")


class BadDescriptor(Exception):
    """A type descriptor the contract does not define. The caller turns it
    into the violation its section names: a document declaration is a
    `state-declaration` or `context-declaration`, a vocabulary one is
    `InvalidVocabulary`."""


def parse_type(descriptor):
    """A type descriptor (document model spec, Types): a scalar name with
    an optional `?`, or an object carrying `enum`, `array`, or `record`
    with an optional `optional` flag. Anything else is rejected here
    rather than accepted as a type nothing can satisfy, which would fail
    later against a value and blame the value."""
    if isinstance(descriptor, str):
        optional = descriptor.endswith("?")
        name = descriptor[:-1] if optional else descriptor
        if name not in SCALARS:
            raise BadDescriptor(descriptor)
        return Ty(name, optional)
    if not isinstance(descriptor, dict):
        raise BadDescriptor(descriptor)
    optional = descriptor.get("optional", False)
    if not isinstance(optional, bool):
        raise BadDescriptor(descriptor)
    # Unknown keys are ignored, per the tolerance rule, so a descriptor can
    # grow in a minor contract version.
    if "enum" in descriptor:
        members = descriptor["enum"]
        if not isinstance(members, list) or not members:
            raise BadDescriptor(descriptor)
        for member in members:
            if not _identifier(member) or members.count(member) > 1:
                raise BadDescriptor(descriptor)
        return Ty("enum", optional, members=list(members))
    if "array" in descriptor:
        return Ty("array", optional, elem=parse_type(descriptor["array"]))
    if "record" in descriptor:
        fields = descriptor["record"]
        if not isinstance(fields, dict):
            raise BadDescriptor(descriptor)
        for name in fields:
            if not _identifier(name):
                raise BadDescriptor(descriptor)
        return Ty("record", optional,
                  fields={k: parse_type(v) for k, v in fields.items()})
    raise BadDescriptor(descriptor)


def same_type(left, right):
    """Kind equality, member-aware for enums: two enum types are the same
    exactly when their member sets are equal (structural, like records)."""
    if left.kind != right.kind:
        return False
    if left.kind == "enum":
        return set(left.members) == set(right.members)
    return True


def type_accepts(declared, actual):
    """Whether a value of static type `actual` may appear where `declared`
    is expected: same type, an int promoting to double, or an enum
    widening to string."""
    if same_type(declared, actual):
        return True
    if declared.kind == "double" and actual.kind == "int":
        return True
    return declared.kind == "string" and actual.kind == "enum"


def json_kind(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "record"
    return "null"


def validate_value(value, ty, rule, **detail):
    """Validate a supplied data value against a declaration; canonicalize."""
    if value is None:
        if not ty.optional:
            raise GateError("SchemaViolation", rule=rule,
                            expected=repr(ty), found="null", **detail)
        return None
    kind = json_kind(value)
    if ty.kind == "enum":
        if kind != "string" or value not in ty.members:
            raise GateError("SchemaViolation", rule=rule,
                            expected="enum member", found=value, **detail)
        return value
    if ty.kind == "double" and kind == "int":
        return float(value)
    if ty.kind == "array" and kind == "array":
        return [validate_value(v, ty.elem, rule, **detail) for v in value]
    if ty.kind == "record" and kind == "record":
        out = {}
        for name, field_ty in ty.fields.items():
            if name in value:
                out[name] = validate_value(value[name], field_ty, rule, **detail)
            elif field_ty.optional:
                out[name] = None
            else:
                raise GateError("SchemaViolation", rule=rule,
                                expected=name, found="missing", **detail)
        for name in value:
            if name not in ty.fields:
                raise GateError("SchemaViolation", rule=rule,
                                expected=repr(ty), found=name, **detail)
        return out
    if ty.kind != kind:
        raise GateError("SchemaViolation", rule=rule,
                        expected=repr(ty).rstrip("?"), found=kind, **detail)
    return value


def zero_value(ty):
    """The zero value of a declared type (expression spec, Host functions):
    what an invalid function result evaluates to, so evaluation stays
    total. Optionals are null; an enum is its first declared member."""
    if ty.optional:
        return None
    if ty.kind == "enum":
        return ty.members[0]
    if ty.kind == "array":
        return []
    if ty.kind == "record":
        return {name: zero_value(field) for name, field in ty.fields.items()}
    return {"bool": False, "int": 0, "double": 0.0, "string": ""}[ty.kind]


def parse_function(declaration):
    """A host function declaration's types (vocabulary schema spec,
    Function declarations)."""
    return {"arguments": [parse_type(a) for a in declaration["arguments"]],
            "returns": parse_type(declaration["returns"])}


class HostFunctionMiss(Exception):
    """A host function was called with arguments the vector's results
    table has no case for: a vector defect, not a gate outcome."""

    def __init__(self, name, arguments):
        super().__init__(f"{name}({arguments!r})")
        self.name = name
        self.arguments = arguments


# ---------------------------------------------------------------------------
# Expression language: tokenizer, parser, type checker, evaluator.
# ---------------------------------------------------------------------------


class ExprError(Exception):
    pass


class FeatureError(ExprError):
    """A function or root the document's declared contract version does
    not have yet: the gate reports it as `contract-feature`, not as an
    ordinary expression defect."""

    def __init__(self, name, introduced):
        super().__init__(f"{name} requires contract {contract_text(introduced)}")
        self.name = name
        self.introduced = introduced


def _ascii_letter(c):
    """The grammar's letter: ASCII only, per the expression spec."""
    return "a" <= c <= "z" or "A" <= c <= "Z"


def _ascii_digit(c):
    return "0" <= c <= "9"


def tokenize(text):
    tokens = []
    i, n = 0, len(text)
    two = {"??", "||", "&&", "==", "!=", "<=", ">="}
    one = set("+-*/%<>!().,[]")
    while i < n:
        c = text[i]
        if c in " \t":
            i += 1
            continue
        if text[i:i + 2] in two:
            tokens.append(("op", text[i:i + 2]))
            i += 2
        elif _ascii_digit(c):
            j = i
            while j < n and _ascii_digit(text[j]):
                j += 1
            if j < n and text[j] == "." and j + 1 < n and _ascii_digit(text[j + 1]):
                j += 1
                while j < n and _ascii_digit(text[j]):
                    j += 1
                tokens.append(("double", float(text[i:j])))
            else:
                tokens.append(("int", int(text[i:j])))
            i = j
        elif c == "'":
            j, out = i + 1, []
            while j < n:
                if text[j] == "\\":
                    if j + 1 >= n or text[j + 1] not in "'\\":
                        raise ExprError("bad escape")
                    out.append(text[j + 1])
                    j += 2
                elif text[j] == "'":
                    break
                else:
                    out.append(text[j])
                    j += 1
            else:
                raise ExprError("unterminated string")
            tokens.append(("string", "".join(out)))
            i = j + 1
        elif _ascii_letter(c):
            j = i
            while j < n and (_ascii_letter(text[j]) or _ascii_digit(text[j])
                             or text[j] == "_"):
                j += 1
            tokens.append(("ident", text[i:j]))
            i = j
        elif c == "$":
            # A built-in function: the contract's namespace, as in $set and
            # $repeat (expression spec, Grammar). Valid only in call
            # position, which the parser enforces.
            j = i + 1
            if j >= n or not _ascii_letter(text[j]):
                raise ExprError("$ must be followed by a function name")
            while j < n and (_ascii_letter(text[j]) or _ascii_digit(text[j])
                             or text[j] == "_"):
                j += 1
            tokens.append(("builtin", text[i:j]))
            i = j
        elif c in one:
            tokens.append(("op", c))
            i += 1
        else:
            raise ExprError(f"unexpected character {c!r}")
    return tokens


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, kind=None, value=None):
        token = self.peek()
        if token is None or (kind and token[0] != kind) or (value and token[1] != value):
            raise ExprError(f"expected {value or kind}, got {token}")
        self.pos += 1
        return token

    def at_op(self, *values):
        token = self.peek()
        return token is not None and token[0] == "op" and token[1] in values

    def parse(self):
        node = self.coalesce()
        if self.peek() is not None:
            raise ExprError(f"trailing tokens at {self.peek()}")
        return node

    def coalesce(self):
        left = self.binary(0)
        if self.at_op("??"):
            self.take()
            return ("??", left, self.coalesce())
        return left

    LEVELS = [["||"], ["&&"], ["==", "!="], ["<", "<=", ">", ">="],
              ["+", "-"], ["*", "/", "%"]]

    def binary(self, level):
        if level == len(self.LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while self.at_op(*self.LEVELS[level]):
            op = self.take()[1]
            left = (op, left, self.binary(level + 1))
        return left

    def unary(self):
        if self.at_op("!", "-"):
            op = self.take()[1]
            return ("neg" if op == "-" else "not", self.unary())
        return self.postfix()

    def postfix(self):
        node = self.primary()
        while self.at_op(".") or self.at_op("["):
            if self.at_op("."):
                self.take()
                node = ("field", node, self.take("ident")[1])
            else:
                # A lookup: the key is an expression, so the member is
                # chosen at evaluation rather than written in the document.
                self.take()
                key = self.coalesce()
                self.take("op", "]")
                node = ("lookup", node, key)
        return node

    def primary(self):
        token = self.peek()
        if token is None:
            raise ExprError("unexpected end of expression")
        kind, value = token
        if kind in ("int", "double", "string"):
            self.take()
            return ("lit", kind, value)
        if kind == "ident":
            self.take()
            if value in ("true", "false"):
                return ("lit", "bool", value == "true")
            if value == "null":
                return ("lit", "null", None)
            if self.at_op("("):
                return ("call", value, self.arguments())
            return ("ref", value)
        if kind == "builtin":
            self.take()
            if not self.at_op("("):
                raise ExprError(f"{value} is a function and needs arguments")
            return ("call", value, self.arguments())
        if kind == "op" and value == "(":
            self.take()
            node = self.coalesce()
            self.take("op", ")")
            return node
        raise ExprError(f"unexpected token {token}")

    def arguments(self):
        """The parenthesized argument list of a call, the opening paren
        still unconsumed."""
        self.take("op", "(")
        args = []
        if not self.at_op(")"):
            args.append(self.coalesce())
            while self.at_op(","):
                self.take()
                args.append(self.coalesce())
        self.take("op", ")")
        return args


class Checker:
    """Static typing per spec 03; raises ExprError on any violation.

    `event`, when given, is the Ty of the enclosing event binding's declared
    payload: within action expressions the bare `event` root has that type.
    `result` and `failure` are the enclosing custom action's declared
    completion types, in scope inside its onSuccess and onFailure lists.
    `contract` is the document's declared major.minor: a function or root a
    later minor introduced is a FeatureError there. `functions` are the
    surface's declared host functions (name to parsed declaration), and
    `used` a set the checker adds every called one to, so the gate knows
    the document needs a function handler.
    """

    def __init__(self, state, context, event=None, result=None, bindings=None,
                 failure=None, contract=(2, 1), functions=None, used=None):
        self.roots = {"state": state, "context": context}
        self.scalar_roots = {"event": event, "result": result, "failure": failure}
        # $repeat bindings (document model spec, Constructs): the element
        # and its index, roots like event and result.
        self.scalar_roots.update(bindings or {})
        self.contract = tuple(contract)
        self.functions = functions or {}
        self.used = used if used is not None else set()

    def declared_position(self, node, declared):
        """A declared position's acceptance (expression spec, Typing): the
        expected type propagates in (enum literals refine), null needs an
        optional, int promotes to double, an enum widens to string, and a
        non-optional fits an optional; never the reverse."""
        result = self.check(node, expecting=declared)
        if result.kind == "null":
            if not declared.optional:
                raise ExprError("null in a non-optional position")
            return
        if not type_accepts(declared, result) \
                or (result.optional and not declared.optional):
            raise ExprError(f"expected {declared!r}, found {result!r}")

    def gate_feature(self, name, features):
        introduced = features.get(name)
        if introduced is not None and self.contract < introduced:
            raise FeatureError(name, introduced)

    def check(self, node, expecting=None):
        op = node[0]
        if op == "lit":
            _, kind, value = node
            if kind == "int" and not INT_MIN <= value <= INT_MAX:
                raise ExprError("int literal out of 64-bit range")
            # A string literal in an enum position is refined to the enum:
            # membership is checked here, at the gate.
            if kind == "string" and expecting is not None \
                    and expecting.kind == "enum":
                if value not in expecting.members:
                    raise ExprError(
                        f"{value!r} is not a member of the declared enum")
                return Ty("enum", members=expecting.members)
            return Ty(kind, optional=(kind == "null"))
        if op == "ref":
            self.gate_feature(node[1], ROOT_FEATURES)
            scalar = self.scalar_roots.get(node[1])
            if scalar is not None:
                return scalar
            raise ExprError(f"bare identifier {node[1]!r} is not a reserved root")
        if op == "lookup":
            _, base, key = node
            self.gate_feature("[]", EXPRESSION_FEATURES)
            subject = self.scalar(base)
            if subject.kind != "record" or subject.optional:
                raise ExprError("a lookup reads a non-optional record")
            key_type = self.scalar(key)
            if key_type.kind != "enum" or key_type.optional:
                raise ExprError("a lookup's key is a non-optional enum")
            # The member set and the field set must be equal, which is
            # what makes the lookup total and the coverage exhaustive: a
            # member added later no longer has a field, and the gate says
            # so instead of the view rendering the wrong thing.
            if set(key_type.members) != set(subject.fields):
                raise ExprError(
                    "a lookup's enum members and the record's fields must match")
            types = list(subject.fields.values())
            first = types[0]
            for other in types[1:]:
                if not same_type(first, other) or first.optional != other.optional:
                    raise ExprError("a lookup's record fields must share one type")
            return first
        if op == "field":
            _, base, name = node
            if base[0] == "ref":
                root = base[1]
                if self.scalar_roots.get(root) is not None:
                    ty = self.scalar_roots[root]
                    if ty.kind != "record" or ty.optional:
                        raise ExprError(
                            "field access requires a non-optional record")
                    if name not in ty.fields:
                        raise ExprError(f"{root}.{name} is not declared")
                    return ty.fields[name]
                if root not in self.roots:
                    raise ExprError(f"{root!r} is not a reserved root")
                decls = self.roots[root]
                if name not in decls:
                    raise ExprError(f"{root}.{name} is not declared")
                return decls[name]
            base_ty = self.check(base)
            if base_ty.kind != "record" or base_ty.optional:
                raise ExprError("field access requires a non-optional record")
            if name not in base_ty.fields:
                raise ExprError(f"field {name!r} is not declared")
            return base_ty.fields[name]
        if op == "not":
            self.expect(node[1], "bool")
            return Ty("bool")
        if op == "neg":
            ty = self.scalar(node[1])
            if ty.kind not in ("int", "double") or ty.optional:
                raise ExprError("unary - requires int or double")
            return Ty(ty.kind)
        if op == "??":
            left = self.check(node[1], expecting)
            right = self.check(node[2], expecting)
            if not left.optional:
                raise ExprError("?? requires an optional left side")
            if right.optional:
                raise ExprError("?? requires a non-optional right side")
            if left.kind != "null" and not same_type(left, right):
                raise ExprError("?? sides must share a type")
            return right
        if op in ("&&", "||"):
            self.expect(node[1], "bool")
            self.expect(node[2], "bool")
            return Ty("bool")
        if op in ("==", "!="):
            left, right = self.check(node[1]), self.check(node[2])
            for ty in (left, right):
                if ty.kind in ("array", "record"):
                    raise ExprError("arrays and records are not comparable")
            if left.kind == "null" or right.kind == "null":
                # The null literal's own type is optional, so the test is
                # on the other operand: it must be an optional, and there
                # must be one. A non-optional compared to null, or null to
                # null, could only ever be constant, and is refused like an
                # enum compared to a non-member.
                other = right if left.kind == "null" else left
                if other.kind == "null" or not other.optional:
                    raise ExprError("null compares only to optionals")
                return Ty("bool")
            if left.optional or right.optional:
                raise ExprError("optionals compare only to null")
            if {left.kind, right.kind} <= {"int", "double"}:
                return Ty("bool")
            # Enums: a string-literal operand must be a member; two enums
            # must be the same enum; a non-literal string compares as a
            # string (the enum widens).
            if "enum" in (left.kind, right.kind):
                return self.check_enum_comparison(node, left, right)
            if left.kind != right.kind:
                raise ExprError("== requires matching scalar types")
            return Ty("bool")
        if op in ("<", "<=", ">", ">="):
            for side in (node[1], node[2]):
                ty = self.scalar(side)
                if ty.kind not in ("int", "double"):
                    raise ExprError("ordering requires numeric operands")
            return Ty("bool")
        if op in ("+", "-", "*", "/", "%"):
            left, right = self.scalar(node[1]), self.scalar(node[2])
            if op == "+" and left.kind in ("string", "enum") \
                    and right.kind in ("string", "enum"):
                return Ty("string")
            if left.kind not in ("int", "double") or right.kind not in ("int", "double"):
                raise ExprError(f"{op} requires numeric operands")
            if "double" in (left.kind, right.kind):
                return Ty("double")
            return Ty("int")
        if op == "call":
            return self.call(node[1], node[2], expecting)
        raise ExprError(f"unhandled node {op}")

    def check_enum_comparison(self, node, left, right):
        if left.kind == "enum" and right.kind == "enum":
            if not same_type(left, right):
                raise ExprError("distinct enum types are not comparable")
            return Ty("bool")
        enum_ty = left if left.kind == "enum" else right
        other_node = node[2] if left.kind == "enum" else node[1]
        if other_node[0] == "lit" and other_node[1] == "string" \
                and other_node[2] not in enum_ty.members:
            raise ExprError(
                f"{other_node[2]!r} is not a member of the declared enum")
        other = right if left.kind == "enum" else left
        if other.kind != "string":
            raise ExprError("== requires matching scalar types")
        return Ty("bool")

    def scalar(self, node):
        ty = self.check(node)
        if ty.optional:
            raise ExprError("optional value must be resolved with ?? first")
        return ty

    def expect(self, node, kind):
        ty = self.scalar(node)
        if ty.kind != kind and not (kind == "string" and ty.kind == "enum"):
            raise ExprError(f"expected {kind}, found {ty.kind}")
        return ty

    def call(self, name, args, expecting=None):
        def arity(count):
            if len(args) != count:
                raise ExprError(f"{name} takes {count} argument(s)")

        # A bare name is a host function the surface declares; the contract's
        # own functions are called through `$` and cannot be shadowed
        # (expression spec, Host functions).
        if not name.startswith("$"):
            declared = self.functions.get(name)
            if declared is None:
                raise ExprError(f"unknown function {name!r}")
            self.gate_feature(name, {name: HOST_FUNCTION_FEATURE})
            arity(len(declared["arguments"]))
            for arg, ty in zip(args, declared["arguments"]):
                self.declared_position(arg, ty)
            self.used.add(name)
            returns = declared["returns"]
            return Ty(returns.kind, returns.optional, elem=returns.elem,
                      fields=returns.fields, members=returns.members)

        self.gate_feature(name, FUNCTION_FEATURES)
        name = name[1:]
        if name == "abs":
            # The magnitude keeps its numeric type: int to int, double to
            # double (expression spec, Functions).
            arity(1)
            ty = self.scalar(args[0])
            if ty.kind not in ("int", "double"):
                raise ExprError("abs takes an int or a double")
            return Ty(ty.kind)
        if name in ("min", "max"):
            # Two or more numeric arguments, promoting like the arithmetic
            # operators: all int stays int, any double makes it double.
            if len(args) < 2:
                raise ExprError(f"{name} takes two or more arguments")
            kinds = [self.scalar(arg).kind for arg in args]
            if any(kind not in ("int", "double") for kind in kinds):
                raise ExprError(f"{name} takes numeric arguments")
            return Ty("int" if all(kind == "int" for kind in kinds) else "double")
        if name in ("floor", "ceil", "round"):
            # Exactly a double, like int() and double(): the promotion of
            # an int expression applies to declared positions, never to a
            # function's argument.
            arity(1)
            self.expect(args[0], "double")
            return Ty("double")
        if name == "str":
            arity(1)
            if self.scalar(args[0]).kind not in (
                    "bool", "int", "double", "string", "enum"):
                raise ExprError("str takes a scalar")
            return Ty("string")
        if name == "int":
            arity(1)
            self.expect(args[0], "double")
            return Ty("int")
        if name == "double":
            arity(1)
            self.expect(args[0], "int")
            return Ty("double")
        if name == "concat":
            if len(args) < 2:
                raise ExprError("concat takes two or more arguments")
            for arg in args:
                self.expect(arg, "string")
            return Ty("string")
        if name in ("length", "isEmpty"):
            arity(1)
            if self.scalar(args[0]).kind not in ("string", "enum", "array"):
                raise ExprError(f"{name} takes a string or array")
            return Ty("int" if name == "length" else "bool")
        if name in ("contains", "startsWith", "endsWith"):
            arity(2)
            self.expect(args[0], "string")
            self.expect(args[1], "string")
            return Ty("bool")
        if name == "trim":
            arity(1)
            self.expect(args[0], "string")
            return Ty("string")
        if name == "substring":
            arity(3)
            self.expect(args[0], "string")
            self.expect(args[1], "int")
            self.expect(args[2], "int")
            return Ty("string")
        if name == "indexOf":
            arity(2)
            self.expect(args[0], "string")
            self.expect(args[1], "string")
            return Ty("int")
        if name == "replace":
            arity(3)
            for arg in args:
                self.expect(arg, "string")
            return Ty("string")
        if name == "split":
            arity(2)
            self.expect(args[0], "string")
            self.expect(args[1], "string")
            return Ty("array", elem=Ty("string"))
        if name == "join":
            arity(2)
            # The array's element type is what matters: an array of enum
            # widens to string like any enum in a string position.
            first = self.scalar(args[0])
            if first.kind != "array" or first.elem is None or \
                    first.elem.kind not in ("string", "enum") or first.elem.optional:
                raise ExprError("join takes an array of string")
            self.expect(args[1], "string")
            return Ty("string")
        if name == "if":
            arity(3)
            self.expect(args[0], "bool")
            # Both branches type-check to the same T, and T may itself be
            # optional: a null branch makes the result optional. The
            # expected type propagates into the branches, so enum member
            # literals refine.
            left = self.check(args[1], expecting)
            right = self.check(args[2], expecting)
            if left.kind == "null" and right.kind == "null":
                raise ExprError("if branches cannot both be null")
            if left.kind == "null":
                return Ty(right.kind, optional=True, members=right.members)
            if right.kind == "null":
                return Ty(left.kind, optional=True, members=left.members)
            # Exactly the same type, optionality included: a T? branch is
            # resolved with ?? before it can sit beside a T one; the null
            # literal above is the only way an if makes an optional.
            if not same_type(left, right) or left.optional != right.optional:
                raise ExprError("if branches must share a type")
            return left
        raise ExprError(f"unknown built-in function ${name}")


def wrap64(value):
    return ((value - INT_MIN) % 2**64) + INT_MIN


def double_remainder(left, right):
    """IEEE 754 truncating remainder, what every platform's double `%`
    computes: NaN when either operand is NaN, the divisor is zero, or the
    dividend is infinite; the dividend itself when only the divisor is.
    math.fmod agrees on the finite cases and raises on the rest."""
    if math.isnan(left) or math.isnan(right) or right == 0.0 or math.isinf(left):
        return math.nan
    return math.fmod(left, right)


class Evaluator:
    """Total evaluation per spec 03. Values: Python int (64-bit emulated),
    float, str, bool, None; report() receives arithmetic occurrences."""

    def __init__(self, state, context, report, event=None, bindings=None,
                 functions=None, results=None):
        self.roots = {"state": state, "context": context}
        if event is not None:
            self.roots["event"] = event
        self.roots.update(bindings or {})
        self.report = report
        # Host functions: the declarations, and the harness's answers as a
        # table (conformance suite spec, config.functions.results). A table
        # of None answers every call with the zero value silently: the
        # producer CLI, which has no host.
        self.functions = functions or {}
        self.results = results

    def eval(self, node):
        op = node[0]
        if op == "lit":
            return node[2]
        if op == "ref":
            return self.roots[node[1]]
        if op == "lookup":
            _, base, key = node
            # An enum value is its member string, and the gate proved the
            # record has a field of exactly that name.
            return self.eval(base)[self.eval(key)]
        if op == "field":
            _, base, name = node
            if base[0] == "ref":
                return self.roots[base[1]][name]
            return self.eval(base)[name]
        if op == "not":
            return not self.eval(node[1])
        if op == "neg":
            value = self.eval(node[1])
            return wrap64(-value) if isinstance(value, int) else -value
        if op == "??":
            left = self.eval(node[1])
            return self.eval(node[2]) if left is None else left
        if op == "&&":
            return self.eval(node[1]) and self.eval(node[2])
        if op == "||":
            return self.eval(node[1]) or self.eval(node[2])
        if op in ("==", "!="):
            left, right = self.eval(node[1]), self.eval(node[2])
            if isinstance(left, int) and not isinstance(left, bool) \
                    and isinstance(right, float):
                left = float(left)
            if isinstance(right, int) and not isinstance(right, bool) \
                    and isinstance(left, float):
                right = float(right)
            equal = left == right and type(left) is type(right) \
                if not isinstance(left, float) else left == right
            return equal if op == "==" else not equal
        if op in ("<", "<=", ">", ">="):
            left, right = self.eval(node[1]), self.eval(node[2])
            if isinstance(left, float) and math.isnan(left) \
                    or isinstance(right, float) and math.isnan(right):
                return False
            return {"<": left < right, "<=": left <= right,
                    ">": left > right, ">=": left >= right}[op]
        if op in ("+", "-", "*", "/", "%"):
            return self.arithmetic(op, self.eval(node[1]), self.eval(node[2]))
        if op == "call":
            if node[1] == "$if":
                # Lazy conditional: only the taken branch evaluates, like
                # && || and ??, so guards suppress the reports they guard.
                taken = 1 if self.eval(node[2][0]) else 2
                return self.eval(node[2][taken])
            return self.call(node[1], [self.eval(arg) for arg in node[2]])
        raise AssertionError(f"unhandled node {op}")

    def arithmetic(self, op, left, right):
        if op == "+" and isinstance(left, str):
            return left + right
        both_int = isinstance(left, int) and isinstance(right, int)
        if not both_int:
            left, right = float(left), float(right)
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            if op == "/":
                if right == 0.0:
                    if left == 0.0 or math.isnan(left):
                        return math.nan
                    return math.copysign(math.inf, left) * math.copysign(1.0, right)
                return left / right
            return double_remainder(left, right)
        if op == "+":
            return wrap64(left + right)
        if op == "-":
            return wrap64(left - right)
        if op == "*":
            return wrap64(left * right)
        if right == 0:
            self.report("divisionByZero")
            return 0
        quotient = abs(left) // abs(right)
        if (left < 0) != (right < 0):
            quotient = -quotient
        if op == "/":
            return wrap64(quotient)
        return wrap64(left - quotient * right)

    def call(self, name, args):
        if not name.startswith("$"):
            declared = self.functions.get(name)
            if declared is None:
                raise AssertionError(f"unknown function {name}")
            return self.host_call(name, args, declared)
        name = name[1:]
        if name == "abs":
            value = args[0]
            if isinstance(value, int):
                # Two's complement: the minimum int negates to itself.
                return wrap64(abs(value))
            return abs(value)  # IEEE magnitude: abs(-0.0) is 0.0, NaN stays NaN.
        if name in ("min", "max"):
            return extremum(name, args)
        if name in ("floor", "ceil", "round"):
            return round_double(name, args[0])
        if name == "str":
            return format_scalar(args[0])
        if name == "int":
            value = args[0]
            if math.isnan(value):
                self.report("saturation")
                return 0
            if value >= float(2**63):
                self.report("saturation")
                return INT_MAX
            if value < float(INT_MIN):
                self.report("saturation")
                return INT_MIN
            return math.trunc(value)
        if name == "double":
            return float(args[0])
        if name == "concat":
            return "".join(args)
        if name == "length":
            return len(args[0])
        if name == "isEmpty":
            return len(args[0]) == 0
        if name == "contains":
            return args[1] in args[0]
        if name == "startsWith":
            return args[0].startswith(args[1])
        if name == "endsWith":
            return args[0].endswith(args[1])
        if name == "trim":
            text = args[0]
            start, end = 0, len(text)
            while start < end and text[start] in WHITE_SPACE:
                start += 1
            while end > start and text[end - 1] in WHITE_SPACE:
                end -= 1
            return text[start:end]
        if name == "substring":
            text, start, end = args
            # Clamped, so every pair of indices names a slice: the
            # function is total and reports nothing.
            length = len(text)
            start = min(max(start, 0), length)
            end = min(max(end, 0), length)
            return text[start:end] if start < end else ""
        if name == "indexOf":
            return args[0].find(args[1])
        if name == "replace":
            text, needle, replacement = args
            # An empty needle matches everywhere; returning the subject
            # unchanged is what keeps the result bounded.
            return text if needle == "" else text.replace(needle, replacement)
        if name == "split":
            text, separator = args
            # An empty separator would explode the string into scalars,
            # unbounded in the value size; one element is the answer.
            return [text] if separator == "" else text.split(separator)
        if name == "join":
            return args[1].join(args[0])
        raise AssertionError(f"unknown built-in function ${name}")

    def host_call(self, name, args, declared):
        """A host function call (expression spec, Host functions): the
        arguments promoted to their declared types, the answer validated
        against the declared return; a mismatch or a throw is reported as
        an invalid function result and evaluates to the zero value."""
        promoted = [float(value) if ty.kind == "double" and isinstance(value, int)
                    and not isinstance(value, bool) else value
                    for value, ty in zip(args, declared["arguments"])]
        returns = declared["returns"]
        if self.results is None:
            return zero_value(returns)
        for case in self.results.get(name, []):
            if deep_equal(case.get("arguments"), promoted):
                break
        else:
            raise HostFunctionMiss(name, promoted)
        if case.get("throws"):
            self.report("invalidFunctionResult", name=name,
                        expected=repr(returns), found="error")
            return zero_value(returns)
        value = case.get("returns")
        try:
            return validate_value(value, returns, "function")
        except GateError:
            self.report("invalidFunctionResult", name=name,
                        expected=repr(returns), found=json_kind(value))
            return zero_value(returns)


def extremum(name, values):
    """min and max per the expression spec: the first argument, replaced by
    each later one that is strictly less (min) or greater (max), so ties
    keep the leftmost and min(0.0, -0.0) is 0.0; all int stays int, any
    double promotes every argument; a NaN anywhere is NaN."""
    if not all(isinstance(value, int) for value in values):
        values = [float(value) for value in values]
        if any(math.isnan(value) for value in values):
            return math.nan
    best = values[0]
    for value in values[1:]:
        if (value < best) if name == "min" else (value > best):
            best = value
    return best


def round_double(name, value):
    """floor, ceil, and round per the expression spec, IEEE 754 doubles in
    and out: non-finite values pass through, round breaks ties away from
    zero (never the platform's rule), and a zero result keeps the
    argument's sign, so ceil(-0.5) and round(-0.4) are -0.0."""
    if math.isnan(value) or math.isinf(value):
        return value
    if name == "floor":
        result = float(math.floor(value))
    elif name == "ceil":
        result = float(math.ceil(value))
    else:
        truncated = math.trunc(value)
        if abs(value - truncated) >= 0.5:
            truncated += 1 if value > 0 else -1
        result = float(truncated)
    if result == 0.0:
        result = math.copysign(0.0, value)
    return result


def format_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    # Python's repr yields the shortest round-trip digits and switches to
    # scientific notation outside the same normalized-exponent window the
    # spec fixes ([-4, 15]); only the exponent spelling differs.
    text = repr(value)
    if "e" in text:
        mantissa, exponent = text.split("e")
        if mantissa.endswith(".0"):
            mantissa = mantissa[:-2]
        return f"{mantissa}e{int(exponent)}"
    return text


# ---------------------------------------------------------------------------
# The gate and resolution, per spec 01.
# ---------------------------------------------------------------------------


class ReferenceGate:
    def __init__(self, vocabulary, policy, actions_config=None, limits=None,
                 surface=None):
        self.vocabulary = sorted_keys(vocabulary)
        vocabulary = self.vocabulary
        self.policy = policy
        self.occurrences = []
        # The surface's inputs: a vector's config may build without a state
        # data provider or an action handler to pin the builder-level rules.
        surface = surface or {}
        self.state_data_provider = surface.get("stateDataProvider", True)
        self.action_handler = surface.get("actionHandler", True)
        self.function_handler = surface.get("functionHandler", True)
        self.uses_custom_actions = False
        # The surface's declared host functions: the vocabulary's, overridden
        # by builder declarations; and the harness's answers.
        functions_config = surface.get("functions") or {}
        declared_functions = dict(vocabulary.get("functions", {}))
        declared_functions.update(functions_config.get("declare", {}))
        self.granted_functions = {name: parse_function(declaration)
                                  for name, declaration in declared_functions.items()}
        self.function_results = functions_config.get("results", {})
        self.used_functions = set()
        # Engine limits: the defaults, overridden by a vector's config.
        self.limits = dict(DEFAULT_LIMITS)
        self.limits.update(limits or {})
        # The surface's granted action set: the vocabulary's declarations,
        # overridden by builder declarations, narrowed by the allowlist.
        # Built-in $ actions are contract, not capabilities.
        actions_config = actions_config or {}
        granted = dict(vocabulary.get("actions", {}))
        granted.update(actions_config.get("declare", {}))
        allow = actions_config.get("allow")
        if allow is not None:
            granted = {name: declaration for name, declaration in granted.items()
                       if name in allow}
        self.granted_actions = granted

    def build(self, vector):
        # 1. Parse; document size is checked on the raw bytes first.
        if "documentText" in vector:
            raw = vector["documentText"].encode("utf-8")
            if len(raw) > self.limits["maxDocumentBytes"]:
                raise GateError("LimitExceeded", limit="maxDocumentBytes",
                                value=self.limits["maxDocumentBytes"],
                                actual=len(raw))
            try:
                document = json.loads(vector["documentText"])
            except ValueError:
                raise GateError("MalformedDocument")
            if not isinstance(document, dict):
                raise GateError("MalformedDocument")
        else:
            document = vector["document"]
        self.check_envelope(document)
        document = sorted_keys(document)

        # 2. Version.
        version = document["version"]
        major, minor = (int(part) for part in version.split(".")[:2])
        if major not in SUPPORTED_VERSIONS or minor > SUPPORTED_VERSIONS[major]:
            raise GateError("UnsupportedVersion", declared=version,
                            supported=supported_ranges())
        self.major = major
        # The document is processed under the rules of the major.minor it
        # declares; a feature a later minor introduced is `contract-feature`.
        self.contract = (major, minor)
        self.bindings = {}

        # Vocabulary requirement: when the document declares one, the
        # engine's vocabulary must match by name and be at least the
        # required version. Semantics per the document model spec.
        requirement = document.get("vocabulary")
        if isinstance(requirement, dict):
            name = requirement.get("name")
            if not isinstance(name, str) or not name:
                raise GateError("MalformedDocument")
            minimum_text = requirement.get("min")
            if minimum_text is not None and _semver(minimum_text) == (-1, -1, -1):
                raise GateError("MalformedDocument")
            held_name = self.vocabulary.get("name")
            if requirement.get("name") != held_name:
                raise GateError("SchemaViolation", rule="vocabulary-requirement",
                                expected=requirement.get("name"), found=held_name)
            minimum = requirement.get("min")
            if minimum is not None:
                held_version = self.vocabulary.get("version", "")
                if _semver(held_version) < _semver(minimum):
                    raise GateError("SchemaViolation",
                                    rule="vocabulary-requirement",
                                    expected=f">={minimum}", found=held_version)

        # Resource limits.
        depth, count = self.measure(document["root"], 1)
        if depth > self.limits["maxTreeDepth"]:
            raise GateError("LimitExceeded", limit="maxTreeDepth",
                            value=self.limits["maxTreeDepth"], actual=depth)
        if count > self.limits["maxNodeCount"]:
            raise GateError("LimitExceeded", limit="maxNodeCount",
                            value=self.limits["maxNodeCount"], actual=count)

        # Declaration keys follow the identifier grammar (vocabulary
        # schema spec, Naming): a letter, then letters, digits, or
        # underscores; never a $ prefix.
        # Members of an object are visited in lexicographic order of the
        # key, never in document order (document model spec, Validation),
        # and each declaration is checked whole before the next: the key
        # against the identifier grammar, then its type descriptor.
        state_decls, context_decls = {}, {}
        for section, rule, into in (("state", "state-declaration", state_decls),
                                    ("context", "context-declaration",
                                     context_decls)):
            for key in sorted(document.get(section, {})):
                if not _identifier(key):
                    raise GateError("SchemaViolation", rule=rule,
                                    expected="identifier", found=key)
                try:
                    into[key] = parse_type(document[section][key])
                except BadDescriptor:
                    raise GateError("SchemaViolation", rule=rule,
                                    expected="type descriptor", found=key)

        # 3-4. Vocabulary and expressions, walking in document order.
        # Unknown subtrees are opaque: no vocabulary or expression checks
        # inside, and no evaluation later.
        self.state_decls = state_decls
        self.context_decls = context_decls
        checker = Checker(state_decls, context_decls, contract=self.contract,
                          functions=self.granted_functions, used=self.used_functions)
        self.validate_node(document["root"], "root", checker)
        self.validate_lifecycle(document)
        self.validate_watch(document)

        # A document binding custom actions needs somewhere to send them:
        # raised by the builder, before dispatch exists. A document calling
        # host functions needs a function handler the same way.
        if self.uses_custom_actions and not self.action_handler:
            raise GateError("SchemaViolation", rule="action-handler",
                            expected="action handler")
        if self.used_functions and not self.function_handler:
            raise GateError("SchemaViolation", rule="function-handler",
                            expected="function handler")

        # 6. Data checks.
        context_values = self.check_supplied(
            vector.get("context", {}), context_decls, "context-declaration")
        if state_decls and not self.state_data_provider:
            raise GateError("SchemaViolation", rule="state-declaration",
                            expected="state data provider")
        state_values = self.check_supplied(
            vector.get("state", {}), state_decls, "state-declaration")

        # Resolution, and the node count limit on the materialized tree.
        resolved = self.resolve(document["root"], "root",
                                state_values, context_values)
        materialized = count_resolved(resolved)
        if materialized > self.limits["maxNodeCount"]:
            raise GateError("LimitExceeded", limit="maxNodeCount",
                            value=self.limits["maxNodeCount"], actual=materialized)
        return resolved, state_values

    def check_envelope(self, document, node=None, path="root"):
        if node is None:
            if not isinstance(document, dict) or "version" not in document \
                    or "root" not in document \
                    or not isinstance(document["version"], str):
                raise GateError("MalformedDocument")
            return self.check_envelope(document, document["root"], "root")
        if node is document["root"] and path == "root" and "metadata" in document \
                and not isinstance(document["metadata"], dict):
            # metadata is a JSON object: hosts read it as a map.
            raise GateError("MalformedDocument")
        if node is document["root"] and path == "root" and "on" in document \
                and not isinstance(document["on"], dict):
            # Lifecycle bindings are a map of signal name to actions.
            raise GateError("MalformedDocument")
        if node is document["root"] and path == "root" and "watch" in document \
                and not isinstance(document["watch"], dict):
            # Watch bindings are a map of state key to actions.
            raise GateError("MalformedDocument")
        if not isinstance(node, dict) or not isinstance(node.get("type"), str):
            raise GateError("MalformedDocument", node=path)
        # An id, when present, is a non-empty string: an empty one would be
        # an empty reference in every report about the node.
        if "id" in node and (not isinstance(node["id"], str) or not node["id"]):
            raise GateError("MalformedDocument", node=path)
        if not isinstance(node.get("properties", {}), dict) \
                or not isinstance(node.get("children", []), list) \
                or not isinstance(node.get("on", {}), dict):
            raise GateError("MalformedDocument", node=path)
        for index, child in enumerate(node.get("children", [])):
            self.check_envelope(document, child, f"{path}/children[{index}]")

    def measure(self, node, depth):
        """A construct's branches are part of the document even though only
        one of them materializes, so the limits see them: a subtree hidden in
        a branch is still a subtree the gate has to walk and validate."""
        deepest, count = depth, 1
        branches = [node.get("then"), node.get("else"), node.get("default")]
        cases = node.get("cases")
        if isinstance(cases, dict):
            branches += list(cases.values())
        children = [child for child in node.get("children", [])
                    if isinstance(child, dict)]
        for branch in branches:
            if isinstance(branch, list):
                children += [child for child in branch if isinstance(child, dict)]
        for child in children:
            child_depth, child_count = self.measure(child, depth + 1)
            deepest = max(deepest, child_depth)
            count += child_count
        return deepest, count

    def reference(self, node, path):
        return node.get("id") or path

    def validate_node(self, node, path, checker, seen_ids=None):
        if seen_ids is None:
            seen_ids = set()
        ref = self.reference(node, path)
        # Per-node checks in document order, id uniqueness first: the walk
        # is one pass, so the first defect in document order wins.
        node_id = node.get("id")
        if node_id is not None:
            if node_id in seen_ids:
                raise GateError("SchemaViolation", rule="id-uniqueness",
                                node=node_id, found=node_id)
            seen_ids.add(node_id)
        # Constructs live in the $ namespace; contract 2.0 admits $repeat.
        if node["type"].startswith("$"):
            if node["type"] == "$repeat" and self.major >= 2:
                self.validate_repeat(node, path, ref, checker, seen_ids)
                return
            if node["type"] == "$switch" and self.major >= 2:
                since = CONSTRUCT_FEATURES["$switch"]
                if self.contract < since:
                    raise GateError("SchemaViolation", rule="contract-feature",
                                    node=ref, expected=contract_text(since),
                                    found="$switch")
                self.validate_switch(node, path, ref, checker, seen_ids)
                return
            if node["type"] == "$if" and self.major >= 2:
                since = CONSTRUCT_FEATURES["$if"]
                if self.contract < since:
                    raise GateError("SchemaViolation", rule="contract-feature",
                                    node=ref, expected=contract_text(since), found="$if")
                self.validate_conditional(node, path, ref, checker, seen_ids)
                return
            raise GateError("SchemaViolation", rule="construct", node=ref,
                            expected="component type", found=node["type"])
        declaration = self.vocabulary["components"].get(node["type"])
        if declaration is None:
            if self.policy == "fail":
                raise GateError("UnknownComponentType", node=ref,
                                unknownType=node["type"])
            kind = "unknownTypeSkipped" if self.policy == "skip" \
                else "unknownTypePlaceholder"
            self.occurrences.append({"kind": kind, "node": ref, "name": node["type"]})
            return  # Opaque subtree: validation stops here.

        declared = {name: parse_type(descriptor) for name, descriptor
                    in declaration.get("properties", {}).items()}
        for name, value in node.get("properties", {}).items():
            if name not in declared:
                if declaration.get("strict"):
                    raise GateError("SchemaViolation", rule="undeclared-property",
                                    node=ref, found=name)
                self.occurrences.append(
                    {"kind": "undeclaredProperty", "node": ref, "name": name})
                continue
            ty = declared[name]
            if isinstance(value, dict) and "$expr" in value:
                self.check_expression(value["$expr"], ty, ref, checker)
            elif ty.kind == "enum":
                if not (value in ty.members
                        or (value is None and ty.optional)):
                    raise GateError("SchemaViolation", rule="property-type",
                                    node=ref, expected="enum member",
                                    found=value)
            else:
                kind = json_kind(value)
                if not (kind == ty.kind or (kind == "int" and ty.kind == "double")
                        or (kind == "null" and ty.optional)):
                    raise GateError("SchemaViolation", rule="property-type",
                                    node=ref, expected=repr(ty).rstrip("?"),
                                    found=kind)

        if node.get("children") and not declaration.get("children"):
            raise GateError("SchemaViolation", rule="children", node=ref,
                            expected="no children", found="children")
        declared_events = declaration.get("events", {})
        for event, bound in node.get("on", {}).items():
            if event not in declared_events:
                raise GateError("SchemaViolation", rule="event-binding",
                                node=ref, expected="declared event", found=event)
            descriptor = declared_events[event]
            event_ty = parse_type(descriptor) if descriptor is not None else None
            self.validate_actions(bound, ref, event_ty)
        for index, child in enumerate(node.get("children", [])):
            self.validate_node(child, f"{path}/children[{index}]", checker,
                               seen_ids)

    RESERVED_ROOTS = {"state", "context", "event", "result", "failure"}

    def element_type(self, repeat, bindings):
        """The element type of a validated $repeat's items expression."""
        checker = Checker(self.state_decls, self.context_decls, bindings=bindings,
                          contract=self.contract,
                          functions=self.granted_functions, used=self.used_functions)
        return checker.check(Parser(tokenize(repeat["items"]["$expr"])).parse()).elem

    def validate_lifecycle(self, document):
        """The document's lifecycle bindings (document model spec, Lifecycle
        bindings), after the tree: contract 2.1 only, the two signal names,
        and each action list under the event rules with no event root."""
        lifecycle = document.get("on")
        if lifecycle is None:
            return
        if self.contract < (2, 1):
            raise GateError("SchemaViolation", rule="contract-feature",
                            expected="2.1", found="on")
        for signal, bound in lifecycle.items():
            if signal not in LIFECYCLE_SIGNALS:
                raise GateError("SchemaViolation", rule="event-binding",
                                expected="lifecycle event", found=signal)
            self.validate_actions(bound, None)

    def validate_watch(self, document):
        """The document's watch bindings (document model spec, Watch
        bindings), after the lifecycle section: contract 2.1 only, each key
        a declared state key, each action list under the lifecycle rules."""
        watch = document.get("watch")
        if watch is None:
            return
        if self.contract < SECTION_FEATURES["watch"]:
            raise GateError("SchemaViolation", rule="contract-feature",
                            expected=contract_text(SECTION_FEATURES["watch"]),
                            found="watch")
        for key, bound in watch.items():
            if key not in self.state_decls:
                raise GateError("SchemaViolation", rule="watch",
                                expected="declared state key", found=key)
            self.validate_actions(bound, None)

    def validate_array_action(self, action, name, ref, checker):
        """An array action's encoding (document model spec, Actions): the
        target a declared, non-optional array key (records for $update),
        no undeclared parameter, every parameter present, `at` an int,
        `field` a declared field, `value` typed as the element or the
        field. Each rule is an action-encoding violation."""
        key = action.get("key")
        declared_ty = self.state_decls.get(key)
        if declared_ty is None:
            raise GateError("SchemaViolation", rule="action-encoding", node=ref,
                            expected="declared state key", found=key)
        if declared_ty.kind != "array" or declared_ty.optional:
            raise GateError("SchemaViolation", rule="action-encoding", node=ref,
                            expected="array state key", found=key)
        element = declared_ty.elem
        if name == "$update" and (element.kind != "record" or element.optional):
            raise GateError("SchemaViolation", rule="action-encoding", node=ref,
                            expected="record element", found=key)
        allowed = ARRAY_ACTION_KEYS[name]
        for parameter in action:
            if parameter != "action" and parameter not in allowed:
                raise GateError("SchemaViolation", rule="action-encoding", node=ref,
                                expected="declared parameter", found=parameter)
        for parameter in allowed:
            if parameter not in action:
                raise GateError("SchemaViolation", rule="action-encoding", node=ref,
                                expected=parameter)
        if "at" in allowed:
            self.check_action_value(action["at"], Ty("int"), ref, checker)
        value_ty = element
        if name == "$update":
            field = action["field"]
            if not isinstance(field, str) or field not in element.fields:
                raise GateError("SchemaViolation", rule="action-encoding", node=ref,
                                expected="declared field",
                                found=field if isinstance(field, str) else json_kind(field))
            value_ty = element.fields[field]
        if "value" in allowed:
            self.check_action_value(action["value"], value_ty, ref, checker)

    def validate_switch(self, node, path, ref, checker, seen_ids):
        """The $switch construct (document model spec, Constructs): an enum
        subject and one branch per member, or a `default` for the rest. A
        member that no case and no default covers is the whole point: the
        gate says so rather than the view rendering nothing."""
        def violation(expected, found=None):
            raise GateError("SchemaViolation", rule="switch", node=ref,
                            expected=expected, found=found)

        if path == "root":
            violation("not the root")
        for key in ("properties", "on", "id"):
            if key in node:
                violation("no " + key)
        for key in node:
            if key not in ("type", "subject", "cases", "default"):
                violation("declared key", key)
        subject = node.get("subject")
        if not isinstance(subject, dict) or "$expr" not in subject:
            violation("subject expression", json_kind(subject))
        cases = node.get("cases")
        if not isinstance(cases, dict):
            violation("cases", json_kind(cases))
        if not cases:
            # The reason, not the kind: an empty object is an object.
            violation("cases", "empty")

        try:
            subject_type = checker.check(Parser(tokenize(subject["$expr"])).parse())
        except ExprError as error:
            raise GateError("SchemaViolation", rule="expression", node=ref,
                            expected="enum", found=str(error))
        if subject_type.kind != "enum" or subject_type.optional:
            violation("enum subject", str(subject_type))

        members = list(subject_type.members)
        branches = []
        for member, branch in cases.items():
            if member not in members:
                violation("declared member", member)
            if not isinstance(branch, list) or not branch:
                violation("case branch", "empty" if isinstance(branch, list)
                          else json_kind(branch))
            branches.append((f"cases[{member}]", branch))
        default = node.get("default")
        if "default" in node:
            if not isinstance(default, list) or not default:
                violation("default branch", "empty" if isinstance(default, list)
                          else json_kind(default))
            branches.append(("default", default))
        else:
            # Exhaustive without one: every member is covered, so no value
            # of the subject can reach a branch that is not there.
            missing = [m for m in members if m not in cases]
            if missing:
                violation("every member or a default", missing[0])

        for name, branch in branches:
            for index, child in enumerate(branch):
                self.validate_node(child, f"{path}/{name}[{index}]", checker, seen_ids)

    def validate_conditional(self, node, path, ref, checker, seen_ids):
        """The $if construct (document model spec, Constructs): never the
        root, no properties, bindings, or id, a bool expression as
        condition, and both branches validated, so a defect in the branch
        a build does not take still fails that build."""
        def violation(expected, found=None):
            raise GateError("SchemaViolation", rule="conditional", node=ref,
                            expected=expected, found=found)

        if path == "root":
            violation("not the root")
        for key in ("properties", "on", "id"):
            if key in node:
                violation("no " + key)
        for key in node:
            if key not in ("type", "condition", "then", "else"):
                violation("declared key", key)
        condition = node.get("condition")
        if not isinstance(condition, dict) or "$expr" not in condition:
            violation("condition expression", json_kind(condition))
        branches = [("then", node.get("then"))]
        if "else" in node:
            branches.append(("else", node["else"]))
        for name, branch in branches:
            if not isinstance(branch, list):
                violation(name + " branch", json_kind(branch))
            if not branch:
                # The reason, not the kind: an empty list is a list, and
                # "array" would say nothing about what is wrong with it.
                violation(name + " branch", "empty")

        try:
            condition_type = checker.check(
                Parser(tokenize(condition["$expr"])).parse(), Ty("bool"))
        except ExprError as error:
            raise GateError("SchemaViolation", rule="expression", node=ref,
                            expected="bool", found=str(error))
        if condition_type.kind != "bool" or condition_type.optional:
            violation("bool condition", str(condition_type))

        # Both branches are part of the document, so both are validated:
        # ids stay unique across them, which is also what keeps a report
        # about one branch unambiguous.
        for name, branch in branches:
            for index, child in enumerate(branch):
                self.validate_node(child, f"{path}/{name}[{index}]",
                                   checker, seen_ids)

    def validate_repeat(self, node, path, ref, checker, seen_ids):
        """The $repeat construct (document model spec, Constructs): never
        the root, no properties or bindings, an array expression as items,
        a fresh identifier as `as`, and a template validated with the
        element and its index in scope."""
        def violation(expected, found=None):
            return GateError("SchemaViolation", rule="repeat", node=ref,
                             expected=expected, found=found)
        if path == "root":
            raise violation("child position", "root")
        if node.get("properties"):
            raise violation("items, as, children", "properties")
        if node.get("on"):
            raise violation("items, as, children", "on")
        items = node.get("items")
        if not (isinstance(items, dict) and set(items) == {"$expr"}):
            raise violation("items expression",
                            json_kind(items) if items is not None else None)
        alias = node.get("as")
        if not isinstance(alias, str) or not _identifier(alias) \
                or alias in self.RESERVED_ROOTS:
            raise violation("binding identifier", alias)
        if alias in self.bindings or f"{alias}_index" in self.bindings:
            raise violation("distinct binding", alias)
        if not node.get("children"):
            raise violation("template", "no children")
        text = items["$expr"]
        if len(text) > self.limits["maxExpressionLength"]:
            raise GateError("LimitExceeded", limit="maxExpressionLength",
                            value=self.limits["maxExpressionLength"],
                            actual=len(text))
        try:
            ast = Parser(tokenize(text)).parse()
            items_ty = checker.check(ast)
        except ExprError:
            raise GateError("SchemaViolation", rule="expression", node=ref,
                            expected="array")
        if items_ty.kind != "array" or items_ty.optional:
            raise violation("array items", repr(items_ty))
        saved = self.bindings
        self.bindings = dict(saved)
        self.bindings[alias] = items_ty.elem
        self.bindings[f"{alias}_index"] = Ty("int")
        template_checker = Checker(self.state_decls, self.context_decls,
                                   bindings=self.bindings, contract=self.contract,
                                   functions=self.granted_functions, used=self.used_functions)
        try:
            self.validate_key(node, ref, template_checker, violation)
            for index, child in enumerate(node["children"]):
                self.validate_node(child, f"{path}/children[{index}]",
                                   template_checker, seen_ids)
        finally:
            self.bindings = saved

    def validate_key(self, node, ref, template_checker, violation):
        """A $repeat's key (contract 2.1): an expression over the template's
        roots whose type is a non-optional string, int, or enum. Checked
        after the items type and before the template's nodes."""
        key = node.get("key")
        if key is None:
            return
        if self.contract < (2, 1):
            raise GateError("SchemaViolation", rule="contract-feature", node=ref,
                            expected="2.1", found="key")
        if not (isinstance(key, dict) and set(key) == {"$expr"}):
            raise violation("key expression", json_kind(key))
        text = key["$expr"]
        if len(text) > self.limits["maxExpressionLength"]:
            raise GateError("LimitExceeded", limit="maxExpressionLength",
                            value=self.limits["maxExpressionLength"],
                            actual=len(text))
        try:
            key_ty = template_checker.check(Parser(tokenize(text)).parse())
        except FeatureError as feature:
            raise GateError("SchemaViolation", rule="contract-feature", node=ref,
                            expected=contract_text(feature.introduced),
                            found=feature.name)
        except ExprError:
            raise GateError("SchemaViolation", rule="expression", node=ref,
                            expected="string or int")
        if key_ty.optional or key_ty.kind not in ("string", "int", "enum"):
            raise violation("key type", repr(key_ty))

    def validate_actions(self, bound, ref, event_ty=None, result_ty=None,
                         failure_ty=None):
        """Custom action bindings must resolve against the surface's granted
        action set; built-in $ actions are always available. Expressions in
        action values are typed with the `event`, `result`, and `failure`
        roots in scope; `result` rebinds inside each custom action's
        onSuccess and `failure` inside its onFailure. `ref` is None for the
        document's lifecycle bindings, which anchor to no node."""
        actions = bound if isinstance(bound, list) else [bound]
        for action in actions:
            if not isinstance(action, dict):
                continue
            name = action.get("action")
            checker = Checker(self.state_decls, self.context_decls,
                              event=event_ty, result=result_ty,
                              bindings=self.bindings, failure=failure_ty,
                              contract=self.contract,
                          functions=self.granted_functions, used=self.used_functions)
            custom = isinstance(name, str) and not name.startswith("$")
            if name == "$set":
                key = action.get("key")
                declared_ty = self.state_decls.get(key)
                if declared_ty is None:
                    raise GateError("SchemaViolation", rule="action-encoding",
                                    node=ref, expected="declared state key",
                                    found=key)
                self.check_action_value(action.get("value"), declared_ty,
                                        ref, checker)
            elif name == "$when":
                self.check_action_value(action.get("condition"),
                                        parse_type("bool"), ref, checker)
            elif name in ARRAY_ACTION_KEYS:
                introduced = ACTION_FEATURES[name]
                if self.contract < introduced:
                    raise GateError("SchemaViolation", rule="contract-feature",
                                    node=ref, expected=contract_text(introduced),
                                    found=name)
                self.validate_array_action(action, name, ref, checker)
            elif custom:
                if name not in self.granted_actions:
                    raise GateError("SchemaViolation", rule="action-capability",
                                    node=ref, expected="granted action", found=name)
                declaration = self.granted_actions[name]
                self.uses_custom_actions = True
                declared = declaration.get("parameters", {})
                for parameter in action:
                    if parameter in ("action", "onSuccess", "onFailure"):
                        continue
                    if parameter not in declared:
                        raise GateError("SchemaViolation", rule="action-encoding",
                                        node=ref, expected="declared parameter",
                                        found=parameter)
                    self.check_action_value(action[parameter],
                                            parse_type(declared[parameter]),
                                            ref, checker)
                for parameter, descriptor in declared.items():
                    if parameter not in action and not parse_type(descriptor).optional:
                        raise GateError("SchemaViolation", rule="action-encoding",
                                        node=ref, expected=parameter)
            for nested in ("actions", "then", "else"):
                if nested in action:
                    self.validate_actions(action[nested], ref, event_ty, result_ty,
                                          failure_ty)
            if custom:
                declaration = self.granted_actions[name]
                scoped_types = {}
                for outcome in ("result", "failure"):
                    descriptor = declaration.get(outcome)
                    scoped_types[outcome] = parse_type(descriptor) \
                        if descriptor is not None else None
                for follow_up, scoped_result, scoped_failure in (
                        ("onSuccess", scoped_types["result"], None),
                        ("onFailure", None, scoped_types["failure"])):
                    if follow_up in action:
                        self.validate_actions(action[follow_up], ref, event_ty,
                                              scoped_result, scoped_failure)
            else:
                for nested in ("onSuccess", "onFailure"):
                    if nested in action:
                        self.validate_actions(action[nested], ref, event_ty,
                                              result_ty, failure_ty)

    def check_action_value(self, value, declared_ty, ref, checker):
        if isinstance(value, dict) and set(value) == {"$expr"}:
            self.check_expression(value["$expr"], declared_ty, ref, checker)
        else:
            validate_value(value, declared_ty, "action-encoding", node=ref)

    def check_expression(self, text, declared_ty, ref, checker):
        error = GateError("SchemaViolation", rule="expression", node=ref,
                          expected=repr(declared_ty))
        if len(text) > self.limits["maxExpressionLength"]:
            raise GateError("LimitExceeded", limit="maxExpressionLength",
                            value=self.limits["maxExpressionLength"],
                            actual=len(text))
        try:
            ast = Parser(tokenize(text)).parse()
            result = checker.check(ast, expecting=declared_ty)
        except FeatureError as feature:
            # A function or root from a later minor than the document
            # declares: the contract-feature rule, named after the feature.
            raise GateError("SchemaViolation", rule="contract-feature", node=ref,
                            expected=contract_text(feature.introduced),
                            found=feature.name)
        except ExprError:
            raise error
        # A non-optional T is accepted where optional T is expected; an
        # enum is accepted where a string is expected (widening).
        if result.kind == "null":
            if not declared_ty.optional:
                raise error
        elif not type_accepts(declared_ty, result) \
                or (result.optional and not declared_ty.optional):
            raise error
        return ast

    def check_supplied(self, supplied, declarations, rule):
        values = {}
        for name, ty in declarations.items():
            if name not in supplied:
                if ty.optional:
                    values[name] = None
                    continue
                # A missing context key is the key's absence; a missing state
                # value is the provider answering null (an omitted value is
                # null), so the shape is the type mismatch's.
                if rule == "context-declaration":
                    raise GateError("SchemaViolation", rule=rule, expected=name)
                supplied = {**supplied, name: None}
            values[name] = validate_value(supplied[name], ty, rule)
            # A value entering state or context fits the value size limit.
            size = value_size(values[name])
            if size > self.limits["maxValueSize"]:
                raise GateError("LimitExceeded", limit="maxValueSize",
                                value=self.limits["maxValueSize"], actual=size)
        return values  # Undeclared supplied keys are ignored.

    def evaluator(self, state, context, report, bindings):
        return Evaluator(state, context, report, bindings=bindings,
                         functions=self.granted_functions,
                         results=self.function_results)

    def resolve(self, node, path, state, context, bindings=None, suffix=""):
        """A resolved snapshot; a $repeat resolves to the list of its
        instances instead, each template node's reference suffixed with
        the instance's identity: the element index, or the rendering of
        the construct's key (document model spec, Constructs)."""
        bindings = bindings or {}
        if node["type"] == "$switch":
            construct_ref = self.reference(node, path) + suffix
            report = lambda kind, **detail: self.occurrences.append(
                {"kind": kind, "node": construct_ref, "name": "subject", **detail})
            ast = Parser(tokenize(node["subject"]["$expr"])).parse()
            member = self.evaluator(state, context, report, bindings).eval(ast)
            cases = node.get("cases", {})
            name = f"cases[{member}]" if member in cases else "default"
            branch = cases.get(member, node.get("default", []))
            chosen = []
            for index, child in enumerate(branch):
                resolved = self.resolve(child, f"{path}/{name}[{index}]", state,
                                        context, bindings, suffix)
                chosen.extend(resolved if isinstance(resolved, list) else [resolved])
            return chosen
        if node["type"] == "$if":
            construct_ref = self.reference(node, path) + suffix
            report = lambda kind, **detail: self.occurrences.append(
                {"kind": kind, "node": construct_ref, "name": "condition", **detail})
            ast = Parser(tokenize(node["condition"]["$expr"])).parse()
            taken = self.evaluator(state, context, report, bindings).eval(ast)
            name = "then" if taken else "else"
            chosen = []
            for index, child in enumerate(node.get(name, [])):
                resolved = self.resolve(child, f"{path}/{name}[{index}]", state,
                                        context, bindings, suffix)
                chosen.extend(resolved if isinstance(resolved, list) else [resolved])
            return chosen
        if node["type"] == "$repeat":
            alias = node["as"]
            construct_ref = self.reference(node, path) + suffix
            report = lambda kind, **detail: self.occurrences.append(
                {"kind": kind, "node": construct_ref, "name": "items", **detail})
            ast = Parser(tokenize(node["items"]["$expr"])).parse()
            elements = self.evaluator(state, context, report, bindings).eval(ast)
            key_ast = Parser(tokenize(node["key"]["$expr"])).parse() \
                if "key" in node else None
            instances, seen_keys = [], set()
            for index, element in enumerate(elements):
                bound = dict(bindings)
                bound[alias] = element
                bound[f"{alias}_index"] = index
                identity = str(index)
                if key_ast is not None:
                    key_report = lambda kind, **detail: self.occurrences.append(
                        {"kind": kind, "node": construct_ref, "name": "key", **detail})
                    identity = render_key(
                        self.evaluator(state, context, key_report, bound).eval(key_ast))
                    # Keys are distinct within one materialization: a
                    # repeat is a data defect at build.
                    if identity in seen_keys:
                        raise GateError("SchemaViolation", rule="repeat",
                                        node=construct_ref, expected="distinct key",
                                        found=identity)
                    seen_keys.add(identity)
                for child_index, child in enumerate(node["children"]):
                    resolved = self.resolve(
                        child, f"{path}/children[{child_index}]", state, context,
                        bound, f"{suffix}[{identity}]")
                    instances.extend(resolved if isinstance(resolved, list) else [resolved])
            return instances
        ref = self.reference(node, path) + suffix
        snapshot = {"type": node["type"], "reference": ref}
        if node["type"] not in self.vocabulary["components"]:
            if self.policy == "placeholder":
                snapshot["placeholder"] = True
            return snapshot  # Root-level skip keeps the bare node.

        declared = self.vocabulary["components"][node["type"]].get("properties", {})
        properties = {}
        for name, value in node.get("properties", {}).items():
            if name not in declared:
                continue
            ty = parse_type(declared[name])
            if isinstance(value, dict) and "$expr" in value:
                report = lambda kind, name=name, **detail: self.occurrences.append(
                    {"kind": kind, "node": ref, "name": name, **detail})
                evaluator = self.evaluator(state, context, report, bindings)
                ast = Parser(tokenize(value["$expr"])).parse()
                result = evaluator.eval(ast)
                # Canonicalize toward the declared type: an int expression
                # in a double position is promoted, as a literal would be.
                if ty.kind == "double" and isinstance(result, int) \
                        and not isinstance(result, bool):
                    result = float(result)
                properties[name] = result
            elif ty.kind == "double" and json_kind(value) == "int":
                properties[name] = float(value)
            else:
                properties[name] = value
        if properties:
            snapshot["properties"] = properties

        children = []
        for index, child in enumerate(node.get("children", [])):
            child_path = f"{path}/children[{index}]"
            if child["type"] not in self.vocabulary["components"] \
                    and self.policy == "skip" and child["type"] != "$repeat":
                continue  # Occurrence was already reported during validation.
            resolved = self.resolve(child, child_path, state, context,
                                    bindings, suffix)
            children.extend(resolved if isinstance(resolved, list) else [resolved])
        if children:
            snapshot["children"] = children
        return snapshot


# ---------------------------------------------------------------------------
# Static lint for step vectors, per spec 05. Steps are never executed; the
# lint verifies what can be known without running dispatch: the build, the
# action lists (spec 01's encoding, expression typing with the event root),
# the shape of each step, and that a deliberately invalid emission is matched
# by the occurrence the vector expects.
# ---------------------------------------------------------------------------


def render_key(value):
    """A key's rendering in an instance reference (document model spec,
    Constructs): a string verbatim, an int in decimal."""
    return value if isinstance(value, str) else str(value)


STEP_KINDS = {"event", "contextUpdate", "complete", "appear", "disappear",
              "replace", "teardown"}


class StepLinter:
    def __init__(self, vector, vocabulary):
        self.vector = vector
        self.vocabulary = vocabulary
        self.problems = []
        self.has_custom_action = False

    def problem(self, text):
        self.problems.append(text)

    def lint(self):
        vector, expect = self.vector, self.vector["expect"]
        if "error" in expect:
            self.problem("a step vector cannot expect a gate error: "
                         "steps run only after a successful build")
            return self.problems

        config = vector.get("config", {})
        policy = config.get("unknownTypePolicy", "fail")
        self.gate = ReferenceGate(self.vocabulary, policy, config.get("actions"),
                                  config.get("limits"), config)
        try:
            self.gate.build(vector)
        except GateError as error:
            self.problem(f"build failed before steps: {error.fields}")
            return self.problems
        except HostFunctionMiss as miss:
            self.problem(f"host function {miss.name} called with "
                         f"{miss.arguments!r}, no case in config.functions.results")
            return self.problems

        document = json.loads(vector["documentText"]) \
            if "documentText" in vector else vector["document"]
        self.state_decls = {k: parse_type(v)
                            for k, v in document.get("state", {}).items()}
        self.context_decls = {k: parse_type(v)
                              for k, v in document.get("context", {}).items()}
        self.collect_actions(vector)
        self.lint_document(document)
        self.lint_steps(vector["steps"])
        for entry in expect.get("dispatched", []):
            name = entry.get("action") if isinstance(entry, dict) else None
            if name not in self.action_decls:
                self.problem(f"expect.dispatched names undeclared "
                             f"action {name!r}")
        return self.problems

    def lint_document(self, document):
        """The document's nodes and its document-level action lists: the
        lifecycle and watch bindings follow the event rules with no event
        root, anchored to the document rather than a node."""
        self.nodes = {}
        self.repeated = set()
        self.bindings = {}
        self.lint_node(document["root"], "root")
        for section in ("on", "watch"):
            for bound in document.get(section, {}).values():
                self.lint_action_list(bound, "document", None)

    def collect_actions(self, vector):
        """The surface's granted action set: the vocabulary's declarations,
        overridden by builder declarations, narrowed by the allowlist.
        Documents never declare actions."""
        actions_config = vector.get("config", {}).get("actions", {})
        self.action_decls = dict(self.vocabulary.get("actions", {}))
        self.action_decls.update(actions_config.get("declare", {}))
        allow = actions_config.get("allow")
        if allow is not None:
            self.action_decls = {name: declaration
                                 for name, declaration in self.action_decls.items()
                                 if name in allow}
        for name, declaration in self.action_decls.items():
            if not isinstance(declaration, dict):
                self.problem(f"action declaration {name!r} must be an object")
                self.action_decls[name] = {}
                continue
            try:
                self.parameter_types(declaration)
                for outcome in ("result", "failure"):
                    if declaration.get(outcome) is not None:
                        parse_type(declaration[outcome])
            except (KeyError, TypeError, AttributeError):
                self.problem(f"action declaration {name!r} has an invalid "
                             f"type descriptor")
                self.action_decls[name] = {}

    def parameter_types(self, declaration):
        return {name: parse_type(descriptor) for name, descriptor
                in (declaration.get("parameters") or {}).items()}

    # -- document walk, mirroring the gate's unknown-type opacity ----------

    def lint_node(self, node, path):
        ref = node.get("id") or path
        self.nodes[ref] = node
        self.nodes[path] = node
        if node["type"] == "$repeat":
            # The template's nodes are addressed as instances: base
            # reference plus one index per enclosing repeat.
            saved = self.bindings
            self.bindings = dict(saved)
            self.bindings[node["as"]] = self.gate.element_type(node, self.bindings)
            self.bindings[f"{node['as']}_index"] = Ty("int")
            for index, child in enumerate(node.get("children", [])):
                self.lint_node(child, f"{path}/children[{index}]")
            self.bindings = saved
            return
        if self.bindings:
            self.repeated.add(ref)
            self.repeated.add(path)
        if node["type"] in ("$if", "$switch"):
            # A construct holds ordinary nodes in its branches, addressed by
            # the branch they sit in. The lint walks all of them, as the gate
            # validates all of them: a branch a run never takes still has
            # events to check.
            for branch in ("then", "else", "default"):
                for index, child in enumerate(node.get(branch, [])):
                    self.lint_node(child, f"{path}/{branch}[{index}]")
            for member, case in (node.get("cases") or {}).items():
                for index, child in enumerate(case):
                    self.lint_node(child, f"{path}/cases[{member}][{index}]")
            return
        declaration = self.vocabulary["components"].get(node["type"])
        if declaration is None:
            return  # Opaque subtree, same as validation.
        events = declaration.get("events") or {}
        for event_name, bound in node.get("on", {}).items():
            descriptor = events.get(event_name)
            event_ty = parse_type(descriptor) if descriptor is not None \
                else None
            self.lint_action_list(bound, ref, event_ty)
        for index, child in enumerate(node.get("children", [])):
            self.lint_node(child, f"{path}/children[{index}]")

    # -- action encoding, per spec 01 --------------------------------------

    def lint_action_list(self, actions, ref, event_ty, result_ty=None,
                         failure_ty=None):
        if isinstance(actions, dict):
            actions = [actions]
        if not isinstance(actions, list):
            self.problem(f"{ref}: an event binds one action or a list")
            return
        for action in actions:
            self.lint_action(action, ref, event_ty, result_ty, failure_ty)

    def lint_action(self, action, ref, event_ty, result_ty=None, failure_ty=None):
        if not isinstance(action, dict) \
                or not isinstance(action.get("action"), str):
            self.problem(f"{ref}: an action is an object with a "
                         f"string 'action' key")
            return
        name = action["action"]
        if name == "$set":
            self.expect_keys(action, ref, "$set", {"key", "value"})
            key = action.get("key")
            if key not in self.state_decls:
                self.problem(f"{ref}: $set targets undeclared "
                             f"state key {key!r}")
            elif "value" not in action:
                self.problem(f"{ref}: $set is missing 'value'")
            else:
                self.lint_value(action["value"], self.state_decls[key],
                                ref, event_ty, "$set value", result_ty, failure_ty)
        elif name == "$sequence":
            self.expect_keys(action, ref, "$sequence", {"actions"})
            self.lint_action_list(action.get("actions", []), ref,
                                  event_ty, result_ty, failure_ty)
        elif name == "$when":
            self.expect_keys(action, ref, "$when",
                             {"condition", "then", "else"})
            if "condition" not in action:
                self.problem(f"{ref}: $when is missing 'condition'")
            else:
                self.lint_value(action["condition"], Ty("bool"),
                                ref, event_ty, "$when condition", result_ty,
                                failure_ty)
            for branch in ("then", "else"):
                if branch in action:
                    self.lint_action_list(action[branch], ref,
                                          event_ty, result_ty, failure_ty)
        elif name in ARRAY_ACTION_KEYS:
            self.expect_keys(action, ref, name, set(ARRAY_ACTION_KEYS[name]))
            checker = Checker(self.state_decls, self.context_decls,
                              event=event_ty, result=result_ty,
                              bindings=self.bindings, failure=failure_ty,
                              contract=self.gate.contract,
                              functions=self.gate.granted_functions,
                              used=self.gate.used_functions)
            try:
                self.gate.validate_array_action(action, name, ref, checker)
            except GateError as error:
                self.problem(f"{ref}: {name} is ill-formed: {error.fields}")
        elif name.startswith("$"):
            self.problem(f"{ref}: unknown built-in action {name!r}")
        else:
            self.lint_custom(action, name, ref, event_ty, result_ty, failure_ty)

    def expect_keys(self, action, ref, name, allowed):
        for key in action:
            if key != "action" and key not in allowed:
                self.problem(f"{ref}: {name} does not take {key!r}")

    def lint_custom(self, action, name, ref, event_ty, result_ty=None,
                    failure_ty=None):
        self.has_custom_action = True
        declaration = self.action_decls.get(name)
        if declaration is None:
            self.problem(f"{ref}: custom action {name!r} is not declared")
        else:
            declared = self.parameter_types(declaration)
            supplied = {k: v for k, v in action.items()
                        if k not in ("action", "onSuccess", "onFailure")}
            for parameter, ty in declared.items():
                if parameter not in supplied:
                    if not ty.optional:
                        self.problem(f"{ref}: {name} is missing required "
                                     f"parameter {parameter!r}")
                    continue
                self.lint_value(supplied[parameter], ty, ref, event_ty,
                                f"{name}.{parameter}", result_ty, failure_ty)
            for parameter in supplied:
                if parameter not in declared:
                    self.problem(f"{ref}: {name} does not declare "
                                 f"parameter {parameter!r}")
        scoped = {}
        for outcome in ("result", "failure"):
            descriptor = (declaration or {}).get(outcome)
            scoped[outcome] = parse_type(descriptor) if descriptor is not None else None
        for follow_up, scoped_result, scoped_failure in (
                ("onSuccess", scoped["result"], None),
                ("onFailure", None, scoped["failure"])):
            if follow_up in action:
                self.lint_action_list(action[follow_up], ref,
                                      event_ty, scoped_result, scoped_failure)

    def lint_value(self, value, ty, ref, event_ty, what, result_ty=None,
                   failure_ty=None):
        if isinstance(value, dict) and "$expr" in value:
            checker = Checker(self.state_decls, self.context_decls,
                              event=event_ty, result=result_ty,
                              bindings=self.bindings, failure=failure_ty,
                              contract=self.gate.contract,
                              functions=self.gate.granted_functions,
                              used=self.gate.used_functions)
            try:
                self.gate.check_expression(value["$expr"], ty, ref, checker)
            except GateError:
                self.problem(f"{ref}: {what} expression "
                             f"{value['$expr']!r} does not produce {ty!r}")
            return
        try:
            validate_value(value, ty, what)
        except GateError:
            self.problem(f"{ref}: {what} literal {json.dumps(value)} "
                         f"does not match {ty!r}")

    # -- steps -------------------------------------------------------------

    def lint_steps(self, steps):
        expected_kinds = {occurrence.get("kind")
                          for occurrence in
                          self.vector["expect"].get("occurrences", [])
                          if isinstance(occurrence, dict)}
        torn_down = False
        for index, step in enumerate(steps):
            label = f"steps[{index}]"
            if not isinstance(step, dict) or len(step) != 1 \
                    or next(iter(step)) not in STEP_KINDS:
                self.problem(f"{label}: a step holds exactly one of "
                             f"event/contextUpdate/complete/appear/disappear/"
                             f"replace/teardown")
                continue
            kind, body = next(iter(step.items()))
            if kind == "teardown":
                if body is not True:
                    self.problem(f"{label}: teardown must be true")
                torn_down = True
            elif kind in ("appear", "disappear"):
                if body is not True:
                    self.problem(f"{label}: {kind} must be true")
            elif kind == "contextUpdate":
                if not isinstance(body, dict):
                    self.problem(f"{label}: contextUpdate holds an object "
                                 f"of values")
            elif kind == "complete":
                self.lint_complete(body, label)
            elif kind == "replace":
                self.lint_replace(body, label)
            else:
                self.lint_event(body, label, torn_down, expected_kinds)

    def lint_complete(self, body, label):
        if not isinstance(body, dict) \
                or not isinstance(body.get("dispatch"), int) \
                or isinstance(body.get("dispatch"), bool) \
                or body["dispatch"] < 0 \
                or body.get("outcome") not in ("success", "failure"):
            self.problem(f"{label}: complete takes a non-negative 'dispatch' "
                         f"index and an outcome of success or failure")
            return
        if not self.has_custom_action:
            self.problem(f"{label}: complete without any custom action "
                         f"in the document")

    def lint_replace(self, body, label):
        """A replacement is a build (state and actions spec, Document
        replacement): the new document must build under the vector's
        config, or fail exactly as the step's `error` states; afterwards
        the steps address the new document. The provider's values for the
        keys that do not carry over come from the step; carried keys are
        approximated by the vector's initial values, which have the same
        declared types by rule."""
        if not isinstance(body, dict) \
                or ("document" in body) == ("documentText" in body):
            self.problem(f"{label}: replace takes exactly one of document "
                         f"or documentText")
            return
        config = self.vector.get("config", {})
        gate = ReferenceGate(self.vocabulary, config.get("unknownTypePolicy", "fail"),
                             config.get("actions"), config.get("limits"), config)
        state = dict(self.vector.get("state", {}))
        state.update(body.get("state", {}))
        replacement = {key: body[key] for key in ("document", "documentText")
                       if key in body}
        replacement.update({"name": "replace",
                            "context": self.vector.get("context", {}),
                            "state": state})
        expected_error = body.get("error")
        try:
            gate.build(replacement)
        except GateError as error:
            if expected_error is None:
                self.problem(f"{label}: the replacement fails to build: "
                             f"{error.fields}")
            elif not subset_match(error.fields, expected_error):
                self.problem(f"{label}: replacement error mismatch: produced "
                             f"{error.fields}, expected {expected_error}")
            return
        except HostFunctionMiss as miss:
            self.problem(f"{label}: host function {miss.name} called with "
                         f"{miss.arguments!r}, no case in config.functions.results")
            return
        if expected_error is not None:
            self.problem(f"{label}: the replacement builds, but the step "
                         f"expects {expected_error}")
            return
        document = json.loads(body["documentText"]) \
            if "documentText" in body else body["document"]
        self.state_decls = {k: parse_type(v)
                            for k, v in document.get("state", {}).items()}
        self.context_decls = {k: parse_type(v)
                              for k, v in document.get("context", {}).items()}
        self.gate = gate
        self.lint_document(document)

    def lint_event(self, body, label, torn_down, expected_kinds):
        if not isinstance(body, dict) \
                or not isinstance(body.get("node"), str) \
                or not isinstance(body.get("name"), str):
            self.problem(f"{label}: event takes a string 'node' and 'name'")
            return
        node = self.nodes.get(body["node"])
        if node is None:
            # An instance reference: the template node's reference plus
            # bracketed identities (indices or keys), one per enclosing repeat.
            base = re.sub(r"(\[[^\[\]]*\])+$", "", body["node"])
            if base != body["node"] and base in self.repeated:
                node = self.nodes[base]
        if node is None:
            # A node the document does not have: invalid, like an
            # undeclared event, and the vector must say so.
            if not torn_down and "invalidEmission" not in expected_kinds:
                self.problem(f"{label}: event node {body['node']!r} does not "
                             f"exist in the document, but the vector does not "
                             f"expect an invalidEmission occurrence")
            return
        # After teardown any emission is silently ignored; nothing to check.
        if torn_down:
            return
        declaration = self.vocabulary["components"].get(node["type"])
        if declaration is None:
            return  # Unknown type: no event declarations to lint against.
        events = declaration.get("events") or {}
        if body["name"] not in events \
                or not self.payload_valid("payload" in body,
                                          body.get("payload"),
                                          events[body["name"]]):
            if "invalidEmission" not in expected_kinds:
                self.problem(f"{label}: emission {body['name']!r} on "
                             f"{body['node']!r} is invalid, but the vector "
                             f"does not expect an invalidEmission occurrence")
        elif body["name"] not in node.get("on", {}):
            if "droppedEvent" not in expected_kinds:
                self.problem(f"{label}: event {body['name']!r} on "
                             f"{body['node']!r} has no binding, but the "
                             f"vector does not expect a droppedEvent "
                             f"occurrence")

    def payload_valid(self, present, payload, descriptor):
        if descriptor is None:
            return not present
        ty = parse_type(descriptor)
        if not present:
            return ty.optional
        try:
            validate_value(payload, ty, "emission")
        except GateError:
            return False
        return True


# ---------------------------------------------------------------------------
# Comparison and runner.
# ---------------------------------------------------------------------------


def deep_equal(left, right):
    """Structural equality with bool/int/double kept distinct, except that
    NaN equals NaN so expectations can state NaN outcomes."""
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, float) and isinstance(right, float):
        return left == right or (math.isnan(left) and math.isnan(right))
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() \
            and all(deep_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) \
            and all(deep_equal(a, b) for a, b in zip(left, right))
    return left == right


def subset_match(produced, expected):
    return all(key in produced and deep_equal(produced[key], value)
               for key, value in expected.items())


def run_vector(vector, vocabulary):
    """Returns a list of mismatch strings, empty when the vector agrees."""
    config = vector.get("config", {})
    policy = config.get("unknownTypePolicy", "fail")
    gate = ReferenceGate(vocabulary, policy, config.get("actions"),
                         config.get("limits"), config)
    expect = vector["expect"]
    try:
        resolved, state = gate.build(vector)
    except HostFunctionMiss as miss:
        return [f"host function {miss.name} called with {miss.arguments!r}, "
                f"no case in config.functions.results"]
    except GateError as error:
        if "error" not in expect:
            return [f"unexpected gate error: {error.fields}"]
        if not subset_match(error.fields, expect["error"]):
            return [f"error mismatch: produced {error.fields}, "
                    f"expected {expect['error']}"]
        return []

    problems = []
    if "error" in expect:
        return [f"expected error {expect['error']}, build succeeded"]
    if "view" in expect and not deep_equal(resolved, expect["view"]):
        problems.append(f"view mismatch:\n  produced {json.dumps(resolved)}\n"
                        f"  expected {json.dumps(expect['view'])}")
    if "state" in expect and not deep_equal(state, expect["state"]):
        problems.append(f"state mismatch: produced {json.dumps(state)}, "
                        f"expected {json.dumps(expect['state'])}")
    if "occurrences" in expect:
        produced = gate.occurrences
        if len(produced) != len(expect["occurrences"]) or not all(
                subset_match(p, e)
                for p, e in zip(produced, expect["occurrences"])):
            problems.append(f"occurrences mismatch: produced {produced}, "
                            f"expected {expect['occurrences']}")
    return problems


def synthesized_values(declarations):
    """Zero-values per declaration, the shape a state data provider would
    supply. Exactly `zero_value` per key, so a synthesized value is the
    same value an invalid function result of that type would produce:
    one rule for the zero of a type, not two. Enums are why that matters,
    and this once had no enum branch at all, so an enum-declared key
    synthesized to an empty record the gate would refuse."""
    return {name: zero_value(parse_type(descriptor))
            for name, descriptor in declarations.items()}


TOP_LEVEL_KEYS = {"version", "vocabulary", "context", "state", "root", "on", "watch",
                  "metadata"}
VOCABULARY_KEYS = {"name", "min"}
ENVELOPE_KEYS = {"type", "id", "properties", "children", "on"}
REPEAT_KEYS = ENVELOPE_KEYS | {"items", "as", "key"}
# The $if construct carries none of a component's envelope keys: it has no
# id, no properties, no bindings, and its branches are not `children`.
CONDITIONAL_KEYS = {"type", "condition", "then", "else"}
SWITCH_KEYS = {"type", "subject", "cases", "default"}
DESCRIPTOR_KEYS = {"enum", "array", "record", "optional"}


def unknown_key_warnings(document):
    """Producer lint, non-normative: keys the contract does not define, in
    the objects it governs. The gate ignores them by the tolerance rule
    (Foundations), which is exactly why a typo there is silent."""
    warnings = []

    def descriptor(value, where):
        if not isinstance(value, dict):
            return
        for key in value:
            if key not in DESCRIPTOR_KEYS:
                warnings.append(f"{where}: unknown type descriptor key {key!r}")
        descriptor(value.get("array"), where)
        if isinstance(value.get("record"), dict):
            for name, field in value["record"].items():
                descriptor(field, f"{where}.{name}")

    def node(entry, path):
        if not isinstance(entry, dict):
            return
        # A $repeat carries its own keys; the gate rules on the rest.
        node_type = entry.get("type")
        if node_type == "$repeat":
            known = REPEAT_KEYS
        elif node_type == "$if":
            known = CONDITIONAL_KEYS
        elif node_type == "$switch":
            known = SWITCH_KEYS
        else:
            known = ENVELOPE_KEYS
        for key in entry:
            if key not in known:
                warnings.append(f"{path}: unknown envelope key {key!r}")
        for index, child in enumerate(entry.get("children") or []):
            node(child, f"{path}/children[{index}]")
        # A branch's nodes are linted like any others; they are just not
        # reached through `children`.
        for branch in ("then", "else", "default"):
            for index, child in enumerate(entry.get(branch) or []):
                node(child, f"{path}/{branch}[{index}]")
        if isinstance(entry.get("cases"), dict):
            for member, branch in entry["cases"].items():
                for index, child in enumerate(branch or []):
                    node(child, f"{path}/cases[{member}][{index}]")

    if not isinstance(document, dict):
        return warnings
    for key in document:
        if key not in TOP_LEVEL_KEYS:
            warnings.append(f"document: unknown top-level key {key!r}")
    if isinstance(document.get("vocabulary"), dict):
        for key in document["vocabulary"]:
            if key not in VOCABULARY_KEYS:
                warnings.append(f"vocabulary: unknown key {key!r}")
    for section in ("context", "state"):
        if isinstance(document.get(section), dict):
            for name, value in document[section].items():
                descriptor(value, f"{section}.{name}")
    node(document.get("root"), "root")
    return warnings


def validate_document(document_path, vocabulary_path, context_path, state_path):
    """Producer CLI: run one document through the full gate. Undeclared
    context and state values are synthesized as zero-values so validation
    is one command; supplied files override per key. Unknown keys in
    contract-governed objects are warnings on stderr: the gate ignores
    them by rule, and a producer wants to hear about the typo anyway."""
    vocabulary = json.loads(Path(vocabulary_path).read_text())
    document = json.loads(Path(document_path).read_text())
    for warning in unknown_key_warnings(document):
        print(f"{document_path}: warning: {warning}", file=sys.stderr)

    context = synthesized_values(document.get("context", {}))
    if context_path:
        context.update(json.loads(Path(context_path).read_text()))
    state = synthesized_values(document.get("state", {}))
    if state_path:
        state.update(json.loads(Path(state_path).read_text()))

    gate = ReferenceGate(vocabulary, "fail")
    # No host answers here: every function call evaluates to its zero value.
    gate.function_results = None
    try:
        gate.build({"name": "cli", "document": document,
                    "context": context, "state": state})
    except GateError as error:
        detail = " · ".join(f"{key}: {value}" for key, value in error.fields.items())
        print(f"{document_path}: REJECTED · {detail}")
        return 1
    occurrences = ", ".join(
        f"{entry['kind']}({entry.get('node', '-')})" for entry in gate.occurrences)
    suffix = f" · occurrences: {occurrences}" if occurrences else ""
    print(f"{document_path}: valid against "
          f"{vocabulary.get('name')}@{vocabulary.get('version')}{suffix}")
    return 0


def main():
    if "--document" in sys.argv:
        import argparse
        parser = argparse.ArgumentParser(
            description="Validate one document through the full gate.")
        parser.add_argument("--document", required=True)
        parser.add_argument("--vocabulary", required=True)
        parser.add_argument("--context", help="JSON file of context values; "
                            "unsupplied declared keys are synthesized")
        parser.add_argument("--state", help="JSON file of state values; "
                            "unsupplied declared keys are synthesized")
        args = parser.parse_args()
        sys.exit(validate_document(args.document, args.vocabulary,
                                   args.context, args.state))

    root = Path(__file__).resolve().parent.parent
    checked, linted, failures = 0, [], []
    for suite in sorted((root / "conformance").iterdir()):
        if not suite.is_dir():
            continue
        vocabulary = json.loads((suite / "vocabulary.json").read_text())
        for path in sorted(suite.glob("*.json")):
            if path.name == "vocabulary.json":
                continue
            vector = json.loads(path.read_text())
            if "steps" in vector:
                linted.append(vector["name"])
                for problem in StepLinter(vector, vocabulary).lint():
                    failures.append(f"{path.relative_to(root)}: {problem}")
                continue
            checked += 1
            for problem in run_vector(vector, vocabulary):
                failures.append(f"{path.relative_to(root)}: {problem}")

    print(f"reference check: {checked} vectors checked, "
          f"{len(linted)} step vectors linted "
          f"(step execution is engine territory)")
    for name in linted:
        print(f"  linted: {name}")
    if failures:
        print()
        print("\n".join(failures))
        sys.exit(1)


if __name__ == "__main__":
    main()
