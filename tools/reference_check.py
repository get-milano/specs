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
type-correct (with the event and result roots bound to their declared types), each
step must be structurally valid, and an invalid or unbound emission must be
matched by the occurrence the vector expects.

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
SUPPORTED_MAJORS = {1}
MAX_TREE_DEPTH = 32
MAX_NODE_COUNT = 10_000
MAX_EXPRESSION_LENGTH = 1_024
MAX_DOCUMENT_BYTES = 1_048_576

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


def parse_type(descriptor):
    if isinstance(descriptor, str):
        optional = descriptor.endswith("?")
        return Ty(descriptor.rstrip("?"), optional)
    if "enum" in descriptor:
        return Ty("enum", bool(descriptor.get("optional")),
                  members=list(descriptor["enum"]))
    if "array" in descriptor:
        return Ty("array", bool(descriptor.get("optional")),
                  elem=parse_type(descriptor["array"]))
    return Ty("record", bool(descriptor.get("optional")),
              fields={k: parse_type(v) for k, v in descriptor["record"].items()})


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


# ---------------------------------------------------------------------------
# Expression language: tokenizer, parser, type checker, evaluator.
# ---------------------------------------------------------------------------


class ExprError(Exception):
    pass


def _ascii_letter(c):
    """The grammar's letter: ASCII only, per the expression spec."""
    return "a" <= c <= "z" or "A" <= c <= "Z"


def _ascii_digit(c):
    return "0" <= c <= "9"


def tokenize(text):
    tokens = []
    i, n = 0, len(text)
    two = {"??", "||", "&&", "==", "!=", "<=", ">="}
    one = set("+-*/%<>!().,")
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
        while self.at_op("."):
            self.take()
            node = ("field", node, self.take("ident")[1])
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
                self.take()
                args = []
                if not self.at_op(")"):
                    args.append(self.coalesce())
                    while self.at_op(","):
                        self.take()
                        args.append(self.coalesce())
                self.take("op", ")")
                return ("call", value, args)
            return ("ref", value)
        if kind == "op" and value == "(":
            self.take()
            node = self.coalesce()
            self.take("op", ")")
            return node
        raise ExprError(f"unexpected token {token}")


class Checker:
    """Static typing per spec 03; raises ExprError on any violation.

    `event`, when given, is the Ty of the enclosing event binding's declared
    payload: within action expressions the bare `event` root has that type.
    """

    def __init__(self, state, context, event=None, result=None):
        self.roots = {"state": state, "context": context}
        self.scalar_roots = {"event": event, "result": result}

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
            scalar = self.scalar_roots.get(node[1])
            if scalar is not None:
                return scalar
            raise ExprError(f"bare identifier {node[1]!r} is not a reserved root")
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
                if not (left.optional or right.optional):
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
        raise ExprError(f"unknown function {name!r}")


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

    def __init__(self, state, context, report, event=None):
        self.roots = {"state": state, "context": context}
        if event is not None:
            self.roots["event"] = event
        self.report = report

    def eval(self, node):
        op = node[0]
        if op == "lit":
            return node[2]
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
            if node[1] == "if":
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
        raise AssertionError(f"unknown function {name}")


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
    def __init__(self, vocabulary, policy, actions_config=None):
        self.vocabulary = vocabulary
        self.policy = policy
        self.occurrences = []
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
            if len(raw) > MAX_DOCUMENT_BYTES:
                raise GateError("LimitExceeded", limit="maxDocumentBytes",
                                value=MAX_DOCUMENT_BYTES, actual=len(raw))
            try:
                document = json.loads(vector["documentText"])
            except ValueError:
                raise GateError("MalformedDocument")
            if not isinstance(document, dict):
                raise GateError("MalformedDocument")
        else:
            document = vector["document"]
        self.check_envelope(document)

        # 2. Version.
        version = document["version"]
        if int(version.split(".")[0]) not in SUPPORTED_MAJORS:
            raise GateError("UnsupportedVersion", declared=version,
                            supported=sorted(SUPPORTED_MAJORS))

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
        if depth > MAX_TREE_DEPTH:
            raise GateError("LimitExceeded", limit="maxTreeDepth",
                            value=MAX_TREE_DEPTH, actual=depth)
        if count > MAX_NODE_COUNT:
            raise GateError("LimitExceeded", limit="maxNodeCount",
                            value=MAX_NODE_COUNT, actual=count)

        # Declaration keys follow the identifier grammar (vocabulary
        # schema spec, Naming): a letter, then letters, digits, or
        # underscores; never a $ prefix.
        for section, rule in (("state", "state-declaration"),
                              ("context", "context-declaration")):
            for key in document.get(section, {}):
                if not _identifier(key):
                    raise GateError("SchemaViolation", rule=rule,
                                    expected="identifier", found=key)
        state_decls = {k: parse_type(v)
                       for k, v in document.get("state", {}).items()}
        context_decls = {k: parse_type(v)
                         for k, v in document.get("context", {}).items()}

        # 3-4. Vocabulary and expressions, walking in document order.
        # Unknown subtrees are opaque: no vocabulary or expression checks
        # inside, and no evaluation later.
        self.state_decls = state_decls
        self.context_decls = context_decls
        checker = Checker(state_decls, context_decls)
        self.validate_node(document["root"], "root", checker)

        # 6. Data checks.
        context_values = self.check_supplied(
            vector.get("context", {}), context_decls, "context-declaration")
        state_values = self.check_supplied(
            vector.get("state", {}), state_decls, "state-declaration")

        # Resolution.
        resolved = self.resolve(document["root"], "root",
                                state_values, context_values)
        return resolved, state_values

    def check_envelope(self, document, node=None, path="root"):
        if node is None:
            if not isinstance(document, dict) or "version" not in document \
                    or "root" not in document \
                    or not isinstance(document["version"], str):
                raise GateError("MalformedDocument")
            return self.check_envelope(document, document["root"], "root")
        if not isinstance(node, dict) or not isinstance(node.get("type"), str):
            raise GateError("MalformedDocument", node=path)
        if not isinstance(node.get("properties", {}), dict) \
                or not isinstance(node.get("children", []), list) \
                or not isinstance(node.get("on", {}), dict):
            raise GateError("MalformedDocument", node=path)
        for index, child in enumerate(node.get("children", [])):
            self.check_envelope(document, child, f"{path}/children[{index}]")

    def measure(self, node, depth):
        deepest, count = depth, 1
        for child in node.get("children", []):
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
        # v1 documents contain no construct nodes: the $ prefix is reserved.
        if node["type"].startswith("$"):
            raise GateError("SchemaViolation", rule="construct", node=ref,
                            expected="component type", found=node["type"])
        declaration = self.vocabulary["components"].get(node["type"])
        if declaration is None:
            if self.policy == "fail":
                raise GateError("UnknownComponentType", node=ref,
                                unknownType=node["type"])
            kind = "unknownTypeSkipped" if self.policy == "skip" \
                else "unknownTypePlaceholder"
            self.occurrences.append({"kind": kind, "node": ref})
            return  # Opaque subtree: validation stops here.

        declared = {name: parse_type(descriptor) for name, descriptor
                    in declaration.get("properties", {}).items()}
        for name, value in node.get("properties", {}).items():
            if name not in declared:
                if declaration.get("strict"):
                    raise GateError("SchemaViolation", rule="undeclared-property",
                                    node=ref, found=name)
                self.occurrences.append(
                    {"kind": "undeclaredProperty", "node": ref})
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
                                node=ref, expected=node["type"], found=event)
            descriptor = declared_events[event]
            event_ty = parse_type(descriptor) if descriptor is not None else None
            self.validate_actions(bound, ref, event_ty)
        for index, child in enumerate(node.get("children", [])):
            self.validate_node(child, f"{path}/children[{index}]", checker,
                               seen_ids)

    def validate_actions(self, bound, ref, event_ty=None, result_ty=None):
        """Custom action bindings must resolve against the surface's granted
        action set; built-in $ actions are always available. Expressions in
        action values are typed with the `event` and `result` roots in
        scope; `result` rebinds inside each custom action's onSuccess."""
        actions = bound if isinstance(bound, list) else [bound]
        for action in actions:
            if not isinstance(action, dict):
                continue
            name = action.get("action")
            checker = Checker(self.state_decls, self.context_decls,
                              event=event_ty, result=result_ty)
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
            elif custom:
                if name not in self.granted_actions:
                    raise GateError("SchemaViolation", rule="action-capability",
                                    node=ref, expected="granted action", found=name)
                declaration = self.granted_actions[name]
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
                    self.validate_actions(action[nested], ref, event_ty, result_ty)
            if custom:
                descriptor = self.granted_actions[name].get("result")
                success_ty = parse_type(descriptor) if descriptor is not None \
                    else None
                for follow_up, scoped in (("onSuccess", success_ty),
                                          ("onFailure", None)):
                    if follow_up in action:
                        self.validate_actions(action[follow_up], ref,
                                              event_ty, scoped)
            else:
                for nested in ("onSuccess", "onFailure"):
                    if nested in action:
                        self.validate_actions(action[nested], ref,
                                              event_ty, result_ty)

    def check_action_value(self, value, declared_ty, ref, checker):
        if isinstance(value, dict) and set(value) == {"$expr"}:
            self.check_expression(value["$expr"], declared_ty, ref, checker)
        else:
            validate_value(value, declared_ty, "action-encoding", node=ref)

    def check_expression(self, text, declared_ty, ref, checker):
        error = GateError("SchemaViolation", rule="expression", node=ref,
                          expected=repr(declared_ty))
        if len(text) > MAX_EXPRESSION_LENGTH:
            raise GateError("LimitExceeded", limit="maxExpressionLength",
                            value=MAX_EXPRESSION_LENGTH, actual=len(text))
        try:
            ast = Parser(tokenize(text)).parse()
            result = checker.check(ast, expecting=declared_ty)
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
                raise GateError("SchemaViolation", rule=rule, expected=name)
            values[name] = validate_value(supplied[name], ty, rule)
        return values  # Undeclared supplied keys are ignored.

    def resolve(self, node, path, state, context):
        ref = self.reference(node, path)
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
                report = lambda kind: self.occurrences.append(
                    {"kind": kind, "node": ref})
                evaluator = Evaluator(state, context, report)
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
                    and self.policy == "skip":
                continue  # Occurrence was already reported during validation.
            children.append(self.resolve(child, child_path, state, context))
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


STEP_KINDS = {"event", "contextUpdate", "complete", "teardown"}


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
        self.gate = ReferenceGate(self.vocabulary, policy, config.get("actions"))
        try:
            self.gate.build(vector)
        except GateError as error:
            self.problem(f"build failed before steps: {error.fields}")
            return self.problems

        document = json.loads(vector["documentText"]) \
            if "documentText" in vector else vector["document"]
        self.state_decls = {k: parse_type(v)
                            for k, v in document.get("state", {}).items()}
        self.context_decls = {k: parse_type(v)
                              for k, v in document.get("context", {}).items()}
        self.collect_actions(vector)
        self.nodes = {}
        self.lint_node(document["root"], "root")
        self.lint_steps(vector["steps"])
        for entry in expect.get("dispatched", []):
            name = entry.get("action") if isinstance(entry, dict) else None
            if name not in self.action_decls:
                self.problem(f"expect.dispatched names undeclared "
                             f"action {name!r}")
        return self.problems

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
                if declaration.get("result") is not None:
                    parse_type(declaration["result"])
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

    def lint_action_list(self, actions, ref, event_ty, result_ty=None):
        if isinstance(actions, dict):
            actions = [actions]
        if not isinstance(actions, list):
            self.problem(f"{ref}: an event binds one action or a list")
            return
        for action in actions:
            self.lint_action(action, ref, event_ty, result_ty)

    def lint_action(self, action, ref, event_ty, result_ty=None):
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
                                ref, event_ty, "$set value", result_ty)
        elif name == "$sequence":
            self.expect_keys(action, ref, "$sequence", {"actions"})
            self.lint_action_list(action.get("actions", []), ref,
                                  event_ty, result_ty)
        elif name == "$when":
            self.expect_keys(action, ref, "$when",
                             {"condition", "then", "else"})
            if "condition" not in action:
                self.problem(f"{ref}: $when is missing 'condition'")
            else:
                self.lint_value(action["condition"], Ty("bool"),
                                ref, event_ty, "$when condition", result_ty)
            for branch in ("then", "else"):
                if branch in action:
                    self.lint_action_list(action[branch], ref,
                                          event_ty, result_ty)
        elif name.startswith("$"):
            self.problem(f"{ref}: unknown built-in action {name!r}")
        else:
            self.lint_custom(action, name, ref, event_ty, result_ty)

    def expect_keys(self, action, ref, name, allowed):
        for key in action:
            if key != "action" and key not in allowed:
                self.problem(f"{ref}: {name} does not take {key!r}")

    def lint_custom(self, action, name, ref, event_ty, result_ty=None):
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
                                f"{name}.{parameter}", result_ty)
            for parameter in supplied:
                if parameter not in declared:
                    self.problem(f"{ref}: {name} does not declare "
                                 f"parameter {parameter!r}")
        descriptor = (declaration or {}).get("result")
        success_ty = parse_type(descriptor) if descriptor is not None else None
        for follow_up, scoped in (("onSuccess", success_ty),
                                  ("onFailure", None)):
            if follow_up in action:
                self.lint_action_list(action[follow_up], ref,
                                      event_ty, scoped)

    def lint_value(self, value, ty, ref, event_ty, what, result_ty=None):
        if isinstance(value, dict) and "$expr" in value:
            checker = Checker(self.state_decls, self.context_decls,
                              event=event_ty, result=result_ty)
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
                             f"event/contextUpdate/complete/teardown")
                continue
            kind, body = next(iter(step.items()))
            if kind == "teardown":
                if body is not True:
                    self.problem(f"{label}: teardown must be true")
                torn_down = True
            elif kind == "contextUpdate":
                if not isinstance(body, dict):
                    self.problem(f"{label}: contextUpdate holds an object "
                                 f"of values")
            elif kind == "complete":
                self.lint_complete(body, label)
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

    def lint_event(self, body, label, torn_down, expected_kinds):
        if not isinstance(body, dict) \
                or not isinstance(body.get("node"), str) \
                or not isinstance(body.get("name"), str):
            self.problem(f"{label}: event takes a string 'node' and 'name'")
            return
        node = self.nodes.get(body["node"])
        if node is None:
            self.problem(f"{label}: event node {body['node']!r} does not "
                         f"exist in the document")
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
    gate = ReferenceGate(vocabulary, policy, config.get("actions"))
    expect = vector["expect"]
    try:
        resolved, state = gate.build(vector)
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
    supply: false, 0, 0.0, empty string; null for optionals; recursing into
    arrays (empty) and records."""
    values = {}
    for name, descriptor in declarations.items():
        ty = parse_type(descriptor)
        if ty.optional:
            values[name] = None
        elif ty.kind == "bool":
            values[name] = False
        elif ty.kind == "int":
            values[name] = 0
        elif ty.kind == "double":
            values[name] = 0.0
        elif ty.kind == "string":
            values[name] = ""
        elif ty.kind == "array":
            values[name] = []
        else:
            values[name] = synthesized_values(descriptor.get("record", {}))
    return values


def validate_document(document_path, vocabulary_path, context_path, state_path):
    """Producer CLI: run one document through the full gate. Undeclared
    context and state values are synthesized as zero-values so validation
    is one command; supplied files override per key."""
    vocabulary = json.loads(Path(vocabulary_path).read_text())
    document = json.loads(Path(document_path).read_text())

    context = synthesized_values(document.get("context", {}))
    if context_path:
        context.update(json.loads(Path(context_path).read_text()))
    state = synthesized_values(document.get("state", {}))
    if state_path:
        state.update(json.loads(Path(state_path).read_text()))

    gate = ReferenceGate(vocabulary, "fail")
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
