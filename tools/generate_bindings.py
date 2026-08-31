#!/usr/bin/env python3
"""Generates typed Swift and Kotlin bindings from a vocabulary artifact.

The vocabulary's type information currently dies at the bridge boundary:
consumers read properties, emit events, and switch on actions by string.
This tool turns the artifact into compiler-checked API instead: node
wrappers with typed accessors (non-optional where the gate guarantees
presence), typed event emitters, an exhaustive action type with an
`unrecognized` case for forward compatibility, and a vocabulary identity
helper that refuses to run against a mismatched engine vocabulary.

    python3 tools/generate_bindings.py vocabulary.json \
        --swift-prefix Shop --swift-out Generated.swift \
        --kotlin-package com.acme.shop.milano --kotlin-out Generated.kt \
        --ts-prefix Shop --ts-out generated.ts

Output is deterministic: same artifact and flags, same bytes. Commit the
files; regenerate when the vocabulary changes and let the compiler list
every bridge site the change touches. Type coverage: primitives and
arrays get native types; enums get one nominal type per declaration site
(a Swift/Kotlin enum, a TypeScript string-literal union); records get one
wrapper type per declaration site with typed field accessors and a
memberwise constructor, nesting through record fields and array elements,
so a record-typed property, event payload, action parameter, result, or
failure payload is as typed as a scalar one.
"""

import argparse
import json
import sys

SWIFT_TYPES = {"bool": "Bool", "int": "Int64", "double": "Double", "string": "String"}
KOTLIN_TYPES = {"bool": "Boolean", "int": "Long", "double": "Double", "string": "String"}
SWIFT_ACCESSORS = {"bool": "boolValue", "int": "intValue",
                   "double": "doubleValue", "string": "stringValue"}
KOTLIN_ACCESSORS = {"bool": "boolOrNull", "int": "intOrNull",
                    "double": "doubleOrNull", "string": "stringOrNull"}
SWIFT_WRAP = {"bool": ".bool", "int": ".int", "double": ".double", "string": ".string"}
KOTLIN_WRAP = {"bool": "MilanoValue.BoolValue", "int": "MilanoValue.IntValue",
               "double": "MilanoValue.DoubleValue", "string": "MilanoValue.StringValue"}
TS_TYPES = {"bool": "boolean", "int": "bigint", "double": "number", "string": "string"}
TS_ACCESSORS = {"bool": "boolValue", "int": "intValue",
                "double": "doubleValue", "string": "stringValue"}
TS_WRAP = {"bool": "MilanoValue.bool", "int": "MilanoValue.int",
           "double": "MilanoValue.double", "string": "MilanoValue.string"}

# A Milano identifier is `[A-Za-z][A-Za-z0-9_]*`, which includes plenty of
# words the target languages reserve. Escaping is the language's own
# mechanism, and the wire name is untouched: only the declaration changes.
SWIFT_KEYWORDS = {
    "associatedtype", "class", "deinit", "enum", "extension", "fileprivate", "func",
    "import", "init", "inout", "internal", "let", "open", "operator", "private",
    "precedencegroup", "protocol", "public", "rethrows", "static", "struct", "subscript",
    "typealias", "var", "break", "case", "catch", "continue", "default", "defer", "do",
    "else", "fallthrough", "for", "guard", "if", "in", "repeat", "return", "switch",
    "throw", "throws", "try", "while", "as", "is", "nil", "self", "super", "true",
    "false", "where", "Any", "Self",
}
KOTLIN_KEYWORDS = {
    "as", "break", "class", "continue", "do", "else", "false", "for", "fun", "if", "in",
    "interface", "is", "null", "object", "package", "return", "super", "this", "throw",
    "true", "try", "typealias", "typeof", "val", "var", "when", "while",
}
# TypeScript needs no escaping here: reserved words are legal as property
# and method names, and every generated identifier sits in that position.


def escape_swift(name):
    return f"`{name}`" if name in SWIFT_KEYWORDS else name


def escape_kotlin(name):
    return f"`{name}`" if name in KOTLIN_KEYWORDS else name


def capitalize(name):
    return name[0].upper() + name[1:]


def parse_descriptor(descriptor):
    """Returns (kind, optional, element_kind) with kind 'record' opaque."""
    if isinstance(descriptor, str):
        optional = descriptor.endswith("?")
        return descriptor.rstrip("?"), optional, None
    if "enum" in descriptor:
        return "enum", bool(descriptor.get("optional")), None
    if "array" in descriptor:
        element = descriptor["array"]
        element_kind = element.rstrip("?") if isinstance(element, str) else "record"
        return "array", bool(descriptor.get("optional")), element_kind
    return "record", bool(descriptor.get("optional")), None


def enum_type_name(prefix, *parts):
    return prefix + "".join(capitalize(part) for part in parts)


class Shape:
    """A type descriptor, parsed: `kind` is bool/int/double/string/enum/
    array/record; `element` the array element's Shape; `fields` the
    record's name -> Shape, in declaration order; `members` the enum's."""

    def __init__(self, descriptor):
        if isinstance(descriptor, str):
            self.kind, self.optional = descriptor.rstrip("?"), descriptor.endswith("?")
            self.element, self.fields, self.members = None, None, None
        elif "enum" in descriptor:
            self.kind, self.optional = "enum", bool(descriptor.get("optional"))
            self.element, self.fields, self.members = None, None, list(descriptor["enum"])
        elif "array" in descriptor:
            self.kind, self.optional = "array", bool(descriptor.get("optional"))
            self.element, self.fields, self.members = Shape(descriptor["array"]), None, None
        else:
            self.kind, self.optional = "record", bool(descriptor.get("optional"))
            self.element, self.members = None, None
            self.fields = [(name, Shape(field))
                           for name, field in descriptor["record"].items()]


def collect_sites(vocabulary, prefix):
    """Every enum and record declaration site, in deterministic order,
    nesting through record fields and array elements: one nominal
    generated type per site. Returns (enums, records, lookup): enums as
    [(type_name, members, doc)], records as [(type_name, fields, doc, key)]
    with fields [(name, Shape)], and a lookup from site key to type name.
    A nested site's key extends its parent's with ("field", name) or
    ("item",), and its type name extends the parent's the same way."""
    enums, records, lookup = [], [], {}

    def visit(key, shape, type_name, where):
        if shape.kind == "enum":
            entry_names = [capitalize(member) for member in sorted(shape.members)]
            if len(set(entry_names)) != len(entry_names):
                raise SystemExit(f"enum at {key} has members that collide when"
                                 f" capitalized; rename them")
            enums.append((type_name, sorted(shape.members), f"Members of the {where}."))
            lookup[key] = type_name
        elif shape.kind == "record":
            records.append((type_name, shape.fields, f"Fields of the {where}.", key))
            lookup[key] = type_name
            for name, field in shape.fields:
                visit(key + ("field", name), field, type_name + capitalize(name),
                      f"`{name}` field of `{type_name}`")
        elif shape.kind == "array":
            visit(key + ("item",), shape.element, type_name + "Item",
                  f"element of the {where}")

    for component in sorted(vocabulary.get("components", {})):
        declaration = vocabulary["components"][component]
        for prop in sorted(declaration.get("properties", {}) or {}):
            visit(("property", component, prop), Shape(declaration["properties"][prop]),
                  enum_type_name(prefix, component, prop),
                  f"`{prop}` {Shape(declaration['properties'][prop]).kind} on `{component}`")
        for event in sorted(declaration.get("events", {}) or {}):
            descriptor = declaration["events"][event]
            if descriptor is None:
                continue
            visit(("event", component, event), Shape(descriptor),
                  enum_type_name(prefix, component, event, "payload"),
                  f"`{event}` payload {Shape(descriptor).kind} on `{component}`")
    for action in sorted(vocabulary.get("actions", {})):
        declaration = vocabulary["actions"][action]
        for parameter in sorted(declaration.get("parameters", {}) or {}):
            descriptor = declaration["parameters"][parameter]
            visit(("parameter", action, parameter), Shape(descriptor),
                  enum_type_name(prefix, action, parameter),
                  f"`{parameter}` {Shape(descriptor).kind} on action `{action}`")
        for outcome in ("result", "failure"):
            if declaration.get(outcome) is not None:
                visit((outcome, action), Shape(declaration[outcome]),
                      enum_type_name(prefix, action, outcome),
                      f"{outcome} {Shape(declaration[outcome]).kind} of action `{action}`")
    return enums, records, lookup


def collect_enums(vocabulary, prefix):
    """The enum sites and the lookup, for callers that need only those."""
    enums, _, lookup = collect_sites(vocabulary, prefix)
    return enums, lookup


# Element names for nested array lambdas, one per nesting depth, so an
# array of arrays never shadows its own element.
def element_name(depth):
    return f"item{depth}" if depth else "item"


def postfix(expr):
    """`expr` made safe to follow with `.accessor`: compound expressions
    get parentheses, plain ones stay readable."""
    return f"({expr})" if " " in expr else expr


# ---------------------------------------------------------------------------
# Swift
# ---------------------------------------------------------------------------


def swift_type(shape, key, lookup):
    base = {"bool": "Bool", "int": "Int64", "double": "Double", "string": "String"}.get(shape.kind)
    if shape.kind in ("enum", "record"):
        base = lookup[key]
    elif shape.kind == "array":
        base = "[" + swift_type(shape.element, key + ("item",), lookup) + "]"
    return base + ("?" if shape.optional else "")


def swift_read(shape, key, lookup, expr, depth=0):
    """An expression of `swift_type` reading the MilanoValue `expr`."""
    if shape.kind in SWIFT_ACCESSORS:
        return f"{postfix(expr)}.{SWIFT_ACCESSORS[shape.kind]}" + ("" if shape.optional else "!")
    if shape.kind == "enum":
        enum_type = lookup[key]
        if shape.optional:
            return f"{postfix(expr)}.stringValue.flatMap({enum_type}.init(rawValue:))"
        return f"{enum_type}(rawValue: {postfix(expr)}.stringValue!)!"
    if shape.kind == "record":
        record_type = lookup[key]
        if shape.optional:
            return f"{postfix(expr)}.isNull ? nil : {record_type}({expr})"
        return f"{record_type}({expr})"
    inner = swift_read(shape.element, key + ("item",), lookup, "$0", depth + 1)
    access = f"{postfix(expr)}.arrayValue" + ("?" if shape.optional else "!")
    return f"{access}.map {{ {inner} }}"


def swift_write(shape, key, lookup, expr):
    """A MilanoValue expression wrapping the typed `expr`."""
    if shape.kind in SWIFT_WRAP:
        if shape.optional:
            return f"{expr}.map {{ {SWIFT_WRAP[shape.kind]}($0) }} ?? .null"
        return f"{SWIFT_WRAP[shape.kind]}({expr})"
    if shape.kind == "enum":
        if shape.optional:
            return f"{expr}.map {{ .string($0.rawValue) }} ?? .null"
        return f".string({expr}.rawValue)"
    if shape.kind == "record":
        return f"{expr}?.value ?? .null" if shape.optional else f"{expr}.value"
    inner = swift_write(shape.element, key + ("item",), lookup, "$0")
    if shape.optional:
        return f"{expr}.map {{ .array($0.map {{ {inner} }}) }} ?? .null"
    return f".array({expr}.map {{ {inner} }})"


def swift_record(type_name, fields, doc, key, lookup):
    lines = [f"/// {doc} Non-optional accessors are gate-guaranteed.",
             f"public struct {type_name} {{",
             "    public let value: MilanoValue",
             "    public init(_ value: MilanoValue) { self.value = value }"]
    if fields:
        parameters = [f"{escape_swift(name)}: {swift_type(shape, key + ('field', name), lookup)}"
                      for name, shape in fields]
        signature = f"    public init({', '.join(parameters)}) {{"
        if len(signature) <= 100:
            lines.append(signature)
        else:
            lines.append("    public init(")
            lines.append(",\n".join(f"        {parameter}" for parameter in parameters))
            lines.append("    ) {")
        lines.append("        value = .record([")
        entries = [f"            \"{name}\": "
                   f"{swift_write(shape, key + ('field', name), lookup, escape_swift(name))}"
                   for name, shape in fields]
        lines.append(",\n".join(entries))
        lines.append("        ])")
        lines.append("    }")
    for name, shape in fields:
        read = swift_read(shape, key + ("field", name), lookup,
                          f"value.recordValue?[\"{name}\"] ?? .null")
        declared = (f"    public var {escape_swift(name)}: "
                    f"{swift_type(shape, key + ('field', name), lookup)}")
        if fits(f"{declared} {{ {read} }}"):
            lines.append(f"{declared} {{ {read} }}")
        else:
            lines.extend([f"{declared} {{", f"        {read}", "    }"])
    lines.append("}")
    return "\n".join(lines)


def swift_property(name, descriptor, enum_type=None, key=None, lookup=None):
    kind, optional, element = parse_descriptor(descriptor)
    declared = escape_swift(name)
    shape = Shape(descriptor)
    if kind == "record" or (kind == "array" and element not in SWIFT_TYPES):
        read = swift_read(shape, key, lookup, f"node.property(\"{name}\")")
        return (f"    public var {declared}: {swift_type(shape, key, lookup)} {{\n"
                f"        {read}\n"
                f"    }}")
    if kind == "enum":
        if optional:
            return (f"    public var {declared}: {enum_type}? {{\n"
                    f"        node.property(\"{name}\").stringValue"
                    f".flatMap({enum_type}.init(rawValue:))\n"
                    f"    }}")
        return (f"    public var {declared}: {enum_type} {{\n"
                f"        {enum_type}(rawValue: node.property(\"{name}\").stringValue!)!\n"
                f"    }}")
    if kind in SWIFT_TYPES:
        base, accessor = SWIFT_TYPES[kind], SWIFT_ACCESSORS[kind]
        if optional:
            return (f"    public var {declared}: {base}? "
                    f"{{ node.property(\"{name}\").{accessor} }}")
        return (f"    public var {declared}: {base} "
                f"{{ node.property(\"{name}\").{accessor}! }}")
    if kind == "array" and element in SWIFT_TYPES:
        base, accessor = SWIFT_TYPES[element], SWIFT_ACCESSORS[element]
        force = "" if optional else "!"
        suffix = "?" if optional else ""
        return (f"    public var {declared}: [{base}]{suffix} "
                f"{{ node.property(\"{name}\").arrayValue{force}"
                f".map {{ $0.{accessor}! }} }}")
    suffix = " raw MilanoValue: record-typed" if kind == "record" else ""
    return (f"    /// {name}:{suffix} read fields through MilanoValue accessors.\n"
            f"    public var {declared}: MilanoValue {{ node.property(\"{name}\") }}")


def swift_emitter(event, payload_descriptor, enum_type=None, key=None, lookup=None):
    method = f"emit{capitalize(event)}"
    if payload_descriptor is None:
        return f"    public func {method}() {{ node.emit(\"{event}\") }}"
    kind, optional, element = parse_descriptor(payload_descriptor)
    shape = Shape(payload_descriptor)
    if kind == "record" or (kind == "array" and element not in SWIFT_TYPES):
        return (f"    public func {method}(_ payload: {swift_type(shape, key, lookup)}) {{\n"
                f"        node.emit(\"{event}\", payload: {swift_write(shape, key, lookup, 'payload')})\n"
                f"    }}")
    if kind == "enum":
        if optional:
            return (f"    public func {method}(_ payload: {enum_type}?) {{\n"
                    f"        node.emit(\"{event}\","
                    f" payload: payload.map {{ .string($0.rawValue) }} ?? .null)\n"
                    f"    }}")
        return (f"    public func {method}(_ payload: {enum_type}) {{\n"
                f"        node.emit(\"{event}\", payload: .string(payload.rawValue))\n"
                f"    }}")
    base = SWIFT_TYPES.get(kind, "MilanoValue")
    if base == "MilanoValue":
        return (f"    public func {method}(_ payload: MilanoValue) "
                f"{{ node.emit(\"{event}\", payload: payload) }}")
    wrap = SWIFT_WRAP[kind]
    if optional:
        return (f"    public func {method}(_ payload: {base}?) "
                f"{{ node.emit(\"{event}\", payload: payload.map {{ {wrap}($0) }} ?? .null) }}")
    return (f"    public func {method}(_ payload: {base}) "
            f"{{ node.emit(\"{event}\", payload: {wrap}(payload)) }}")


def render_descriptor(descriptor):
    return descriptor if isinstance(descriptor, str) \
        else json.dumps(descriptor, sort_keys=True)


def result_note(declaration):
    """A doc line for actions declaring a completion result."""
    descriptor = declaration.get("result")
    if descriptor is None:
        return None
    return (f"The handler completes it with a `{render_descriptor(descriptor)}` result,"
            f" bound to `result` in onSuccess.")


def failure_note(declaration):
    """A doc line for actions declaring a failure payload (contract 2.1)."""
    descriptor = declaration.get("failure")
    if descriptor is None:
        return None
    return (f"The handler fails it with a `{render_descriptor(descriptor)}` payload"
            f" (a MilanoActionFailure), bound to `failure` in onFailure.")


def action_notes(declaration):
    """The doc lines an action's declaration earns, in a fixed order."""
    return [note for note in (result_note(declaration), failure_note(declaration))
            if note is not None]


# A doc line's text, before its comment prefix. Wide enough to read, narrow
# enough that every emitter's prefix keeps the line inside the strictest
# formatter limit the generated files meet (130 columns).
DOC_WIDTH = 100


def wrapped_note(text):
    """Greedy word wrap: a rendered type descriptor can be long, and an
    unwrapped doc comment trips the line-length rule of the very linters
    the generated files are checked by. Never breaks inside a word, so a
    single long token simply overflows rather than being mangled."""
    lines, current = [], ""
    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if current and len(candidate) > DOC_WIDTH:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


# Generated code, like the doc comments above, meets formatters with line
# limits (SwiftLint and ktlint both stop at 130 here, and nothing checks
# TypeScript). A declaration wider than this is re-emitted in a multi-line
# form that says exactly the same thing.
CODE_WIDTH = 120


def fits(text):
    """Whether a generated line stays inside the limit."""
    return len(text) <= CODE_WIDTH


def split_top_level(text, separators):
    """Splits an emitted expression at the separators that sit outside every
    bracket, so a long conditional or elvis can be broken across lines
    without understanding the expression."""
    parts, depth, last = [], 0, 0
    index = 0
    while index < len(text):
        character = text[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif depth == 0:
            for separator in separators:
                if text.startswith(separator, index):
                    parts.append(text[last:index])
                    last = index + len(separator)
                    parts.append(separator.strip())
                    index += len(separator) - 1
                    break
        index += 1
    parts.append(text[last:])
    return parts


def unwrapped(text):
    """The expression inside a single pair of enclosing parentheses."""
    if not (text.startswith("(") and text.endswith(")")):
        return None
    inner = text[1:-1]
    depth = 0
    for character in inner:
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
            if depth < 0:
                return None
    return inner if depth == 0 else None


def broken_expression(expression, indent, separators):
    """The expression over several lines, each continuation indented, or
    None when it holds no separator to break at."""
    inner = unwrapped(expression)
    parts = split_top_level(inner if inner is not None else expression, separators)
    if len(parts) < 3:
        return None
    lines = [parts[0].strip()]
    for at in range(1, len(parts) - 1, 2):
        lines.append(f"{parts[at]} {parts[at + 1].strip()}")
    body = [f"{indent}    {lines[0]}"] + [f"{indent}        {line}" for line in lines[1:]]
    if inner is not None:
        return ["("] + body + [f"{indent})"]
    return [lines[0]] + body[1:]


def doc_block(notes, indent, opener="/**", line=" * ", closer=" */"):
    """A block comment carrying the notes, one wrapped line each."""
    if not notes:
        return ""
    body = "".join(f"{indent}{line}{text}\n"
                   for note in notes for text in wrapped_note(note))
    return f"{indent}{opener}\n{body}{indent}{closer}\n"


def swift_action_case(name, declaration, enum_lookup):
    parameters = declaration.get("parameters", {})
    doc = "".join(f"    /// {text}\n"
                  for note in action_notes(declaration) for text in wrapped_note(note))
    declared = escape_swift(name)
    if not parameters:
        return (doc + f"    case {declared}",
                f"        case \"{name}\":\n            self = .{declared}")
    labels, extractors = [], []
    for parameter, descriptor in sorted(parameters.items()):
        kind, optional, element = parse_descriptor(descriptor)
        label = escape_swift(parameter)
        shape = Shape(descriptor)
        if kind == "record" or (kind == "array" and element not in SWIFT_TYPES):
            key = ("parameter", name, parameter)
            labels.append(f"{label}: {swift_type(shape, key, enum_lookup)}")
            source = f"action.parameters[\"{parameter}\"] ?? .null"
            extractors.append(f"{label}: {swift_read(shape, key, enum_lookup, source)}")
            continue
        if kind == "enum":
            enum_type = enum_lookup[("parameter", name, parameter)]
            if optional:
                labels.append(f"{label}: {enum_type}?")
                extractors.append(
                    f"{label}: action.parameters[\"{parameter}\"]?"
                    f".stringValue.flatMap({enum_type}.init(rawValue:))")
            else:
                labels.append(f"{label}: {enum_type}")
                extractors.append(
                    f"{label}: {enum_type}(rawValue:"
                    f" action.parameters[\"{parameter}\"]!.stringValue!)!")
            continue
        base = SWIFT_TYPES.get(kind, "MilanoValue")
        if base == "MilanoValue":
            labels.append(f"{label}: MilanoValue")
            extractors.append(f"{label}: action.parameters[\"{parameter}\"] ?? .null")
        elif optional:
            labels.append(f"{label}: {base}?")
            extractors.append(
                f"{label}: action.parameters[\"{parameter}\"]?.{SWIFT_ACCESSORS[kind]}")
        else:
            labels.append(f"{label}: {base}")
            extractors.append(
                f"{label}: action.parameters[\"{parameter}\"]!.{SWIFT_ACCESSORS[kind]}!")
    case_line = doc + f"    case {declared}({', '.join(labels)})"
    if len(extractors) == 1:
        init_line = (f"        case \"{name}\":\n"
                     f"            self = .{declared}({extractors[0]})")
    else:
        joined = ",\n                ".join(extractors)
        init_line = (f"        case \"{name}\":\n"
                     f"            self = .{declared}(\n"
                     f"                {joined})")
    return case_line, init_line


def generate_swift(vocabulary, prefix):
    name, version = vocabulary["name"], vocabulary["version"]
    enums, records, enum_lookup = collect_sites(vocabulary, prefix)
    lines = [
        f"// Generated from vocabulary \"{name}\" {version} by generate_bindings.py.",
        "// Do not edit; regenerate when the vocabulary changes.",
        "",
        "import MilanoSDK",
        "",
    ]
    for enum_type, enum_members, doc in enums:
        lines.append(f"/// {doc} Gate-guaranteed: decoding never fails.")
        lines.append(f"public enum {enum_type}: String {{")
        for member in enum_members:
            lines.append(f"    case {member}")
        lines.append("}")
        lines.append("")
    for record_type, fields, doc, key in records:
        lines.append(swift_record(record_type, fields, doc, key, enum_lookup))
        lines.append("")
    for component in sorted(vocabulary.get("components", {})):
        declaration = vocabulary["components"][component]
        lines.append(f"/// Typed view of a resolved `{component}` node."
                     " Non-optional accessors are gate-guaranteed.")
        lines.append(f"public struct {prefix}{component}Node {{")
        lines.append("    public let node: MilanoNode")
        lines.append("    public init(_ node: MilanoNode) { self.node = node }")
        for prop in sorted(declaration.get("properties", {})):
            lines.append(swift_property(
                prop, declaration["properties"][prop],
                enum_lookup.get(("property", component, prop)),
                ("property", component, prop), enum_lookup))
        for event in sorted(declaration.get("events", {})):
            lines.append(swift_emitter(
                event, declaration["events"][event],
                enum_lookup.get(("event", component, event)),
                ("event", component, event), enum_lookup))
        lines.append("}")
        lines.append("")

    cases, inits = [], []
    for action in sorted(vocabulary.get("actions", {})):
        case_line, init_line = swift_action_case(
            action, vocabulary["actions"][action], enum_lookup)
        cases.append(case_line)
        inits.append(init_line)
    lines.append("/// Every custom action this vocabulary declares, decoded from dispatch.")
    lines.append(f"public enum {prefix}Action {{")
    lines.extend(cases)
    lines.append("    /// An action outside this vocabulary's declarations"
                 " (builder-declared, or a newer vocabulary).")
    lines.append("    case unrecognized(MilanoAction)")
    lines.append("")
    lines.append("    public init(_ action: MilanoAction) {")
    lines.append("        switch action.name {")
    lines.extend(inits)
    lines.append("        default:")
    lines.append("            self = .unrecognized(action)")
    lines.append("        }")
    lines.append("    }")
    lines.append("}")
    lines.append("")
    lines.append("/// The vocabulary these bindings were generated from.")
    lines.append(f"public enum {prefix}Vocabulary {{")
    lines.append(f"    public static let name = \"{name}\"")
    lines.append(f"    public static let version = \"{version}\"")
    lines.append("")
    lines.append("    /// Refuses to run against an engine holding a different vocabulary.")
    lines.append("    public static func assertMatches(_ engine: MilanoEngine) {")
    lines.append("        precondition(")
    lines.append("            engine.vocabularyName == name"
                 " && engine.vocabularyVersion == version,")
    lines.append("            \"bindings generated from \\(name)@\\(version), engine holds\"")
    lines.append("                + \" \\(engine.vocabularyName)@\\(engine.vocabularyVersion)\")")
    lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Kotlin
# ---------------------------------------------------------------------------


def kotlin_type(shape, key, lookup):
    base = {"bool": "Boolean", "int": "Long", "double": "Double", "string": "String"}.get(shape.kind)
    if shape.kind in ("enum", "record"):
        base = lookup[key]
    elif shape.kind == "array":
        base = "List<" + kotlin_type(shape.element, key + ("item",), lookup) + ">"
    return base + ("?" if shape.optional else "")


def kotlin_read(shape, key, lookup, expr, depth=0):
    """An expression of `kotlin_type` reading the MilanoValue `expr`."""
    if shape.kind in KOTLIN_ACCESSORS:
        return f"{postfix(expr)}.{KOTLIN_ACCESSORS[shape.kind]}" + ("" if shape.optional else "!!")
    if shape.kind == "enum":
        enum_type = lookup[key]
        if shape.optional:
            return f"{postfix(expr)}.stringOrNull?.let {{ {enum_type}.from(it) }}"
        return f"{enum_type}.from({postfix(expr)}.stringOrNull!!)"
    if shape.kind == "record":
        record_type = lookup[key]
        if shape.optional:
            return f"{postfix(expr)}.takeUnless {{ it.isNull }}?.let {{ {record_type}(it) }}"
        return f"{record_type}({expr})"
    item = element_name(depth)
    inner = kotlin_read(shape.element, key + ("item",), lookup, item, depth + 1)
    access = f"{postfix(expr)}.arrayOrNull" + ("?" if shape.optional else "!!")
    return f"{access}.map {{ {item} -> {inner} }}"


def kotlin_write(shape, key, lookup, expr, depth=0):
    """A MilanoValue expression wrapping the typed `expr`."""
    if shape.kind in KOTLIN_WRAP:
        if shape.optional:
            return f"{expr}?.let {{ {KOTLIN_WRAP[shape.kind]}(it) }} ?: MilanoValue.Null"
        return f"{KOTLIN_WRAP[shape.kind]}({expr})"
    if shape.kind == "enum":
        if shape.optional:
            return f"{expr}?.let {{ MilanoValue.StringValue(it.value) }} ?: MilanoValue.Null"
        return f"MilanoValue.StringValue({expr}.value)"
    if shape.kind == "record":
        return f"{expr}?.value ?: MilanoValue.Null" if shape.optional else f"{expr}.value"
    item = element_name(depth)
    inner = kotlin_write(shape.element, key + ("item",), lookup, item, depth + 1)
    if shape.optional:
        return f"{expr}?.let {{ MilanoValue.ArrayValue(it.map {{ {item} -> {inner} }}) }} ?: MilanoValue.Null"
    return f"MilanoValue.ArrayValue({expr}.map {{ {item} -> {inner} }})"


def kotlin_record(type_name, fields, doc, key, lookup):
    lines = [f"/** {doc} Non-null accessors are gate-guaranteed. */",
             f"class {type_name}(",
             "    val value: MilanoValue,",
             ") {"]
    for name, shape in fields:
        read = kotlin_read(shape, key + ("field", name), lookup,
                           f"value.recordOrNull?.get(\"{name}\") ?: MilanoValue.Null")
        declared = f"    val {escape_kotlin(name)}: {kotlin_type(shape, key + ('field', name), lookup)}"
        if fits(f"{declared} get() = {read}"):
            lines.append(f"{declared} get() = {read}")
        else:
            lines.extend([declared, f"        get() = {read}"])
    if fields:
        lines.append("")
        lines.append("    companion object {")
        parameters = [f"{escape_kotlin(name)}: {kotlin_type(shape, key + ('field', name), lookup)}"
                      for name, shape in fields]
        inline = f"        fun of({', '.join(parameters)}): {type_name} ="
        if len(parameters) <= 1 and fits(inline):
            lines.append(inline)
        else:
            lines.append("        fun of(")
            lines.extend(f"            {parameter}," for parameter in parameters)
            lines.append(f"        ): {type_name} =")
        lines.append(f"            {type_name}(")
        lines.append("                MilanoValue.RecordValue(")
        lines.append("                    mapOf(")
        for name, shape in fields:
            write = kotlin_write(shape, key + ("field", name), lookup, escape_kotlin(name))
            entry = f"                        \"{name}\" to ({write}),"
            if fits(entry):
                lines.append(entry)
                continue
            indent = " " * 24
            broken = broken_expression(f"({write})", indent, [" ?: "])
            if broken is None:
                lines.extend([f"{indent}\"{name}\" to",
                              f"{indent}    ({write}),"])
                continue
            lines.append(f"{indent}\"{name}\" to {broken[0]}")
            lines.extend(broken[1:-1])
            lines.append(f"{broken[-1]},")
        lines.append("                    ),")
        lines.append("                ),")
        lines.append("            )")
        lines.append("    }")
    lines.append("}")
    return "\n".join(lines)


def kotlin_property(name, descriptor, enum_type=None, key=None, lookup=None):
    kind, optional, element = parse_descriptor(descriptor)
    declared = escape_kotlin(name)
    shape = Shape(descriptor)
    if kind == "record" or (kind == "array" and element not in KOTLIN_TYPES):
        read = kotlin_read(shape, key, lookup, f"node.property(\"{name}\")")
        return (f"    val {declared}: {kotlin_type(shape, key, lookup)} get() =\n"
                f"        {read}")
    if kind == "enum":
        if optional:
            return (f"    val {declared}: {enum_type}? get() =\n"
                    f"        node.property(\"{name}\").stringOrNull?.let {{\n"
                    f"            {enum_type}.from(it)\n"
                    f"        }}")
        return (f"    val {declared}: {enum_type} get() =\n"
                f"        {enum_type}.from(node.property(\"{name}\").stringOrNull!!)")
    if kind in KOTLIN_TYPES:
        base, accessor = KOTLIN_TYPES[kind], KOTLIN_ACCESSORS[kind]
        if optional:
            return (f"    val {declared}: {base}? "
                    f"get() = node.property(\"{name}\").{accessor}")
        return (f"    val {declared}: {base} "
                f"get() = node.property(\"{name}\").{accessor}!!")
    if kind == "array" and element in KOTLIN_TYPES:
        base, accessor = KOTLIN_TYPES[element], KOTLIN_ACCESSORS[element]
        if optional:
            return (f"    val {declared}: List<{base}>? "
                    f"get() = node.property(\"{name}\").arrayOrNull"
                    f"?.map {{ it.{accessor}!! }}")
        return (f"    val {declared}: List<{base}> "
                f"get() = node.property(\"{name}\").arrayOrNull!!"
                f".map {{ it.{accessor}!! }}")
    return (f"    /** {name}: record-typed, read fields through MilanoValue. */\n"
            f"    val {declared}: MilanoValue get() = node.property(\"{name}\")")


def kotlin_emitter(event, payload_descriptor, enum_type=None, key=None, lookup=None):
    method = f"emit{capitalize(event)}"
    if payload_descriptor is None:
        return f"    fun {method}() = node.emit(\"{event}\")"
    kind, optional, element = parse_descriptor(payload_descriptor)
    shape = Shape(payload_descriptor)
    if kind == "record" or (kind == "array" and element not in KOTLIN_TYPES):
        return (f"    fun {method}(payload: {kotlin_type(shape, key, lookup)}) ="
                f" node.emit(\"{event}\", {kotlin_write(shape, key, lookup, 'payload')})")
    if kind == "enum":
        if optional:
            return (f"    fun {method}(payload: {enum_type}?) ="
                    f" node.emit(\"{event}\","
                    f" payload?.let {{ MilanoValue.StringValue(it.value) }}"
                    f" ?: MilanoValue.Null)")
        return (f"    fun {method}(payload: {enum_type}) ="
                f" node.emit(\"{event}\", MilanoValue.StringValue(payload.value))")
    base = KOTLIN_TYPES.get(kind, "MilanoValue")
    if base == "MilanoValue":
        return f"    fun {method}(payload: MilanoValue) = node.emit(\"{event}\", payload)"
    wrap = KOTLIN_WRAP[kind]
    if optional:
        return (f"    fun {method}(payload: {base}?) = node.emit(\"{event}\","
                f" payload?.let {{ {wrap}(it) }} ?: MilanoValue.Null)")
    return f"    fun {method}(payload: {base}) = node.emit(\"{event}\", {wrap}(payload))"


def kotlin_action_entry(name, declaration, action_type, enum_lookup):
    type_name = capitalize(name)
    parameters = declaration.get("parameters", {})
    # One KDoc per declaration: ktlint refuses consecutive ones.
    notes = action_notes(declaration)
    doc = doc_block(notes, "    ")
    if not parameters:
        entry = doc + f"    data object {type_name} : {action_type}"
        decode = (f"                \"{name}\" -> {{\n"
                  f"                    {type_name}\n"
                  f"                }}")
        return entry, decode
    fields, extractors = [], []
    for parameter, descriptor in sorted(parameters.items()):
        field = escape_kotlin(parameter)
        kind, optional, element = parse_descriptor(descriptor)
        shape = Shape(descriptor)
        if kind == "record" or (kind == "array" and element not in KOTLIN_TYPES):
            key = ("parameter", name, parameter)
            fields.append(f"val {field}: {kotlin_type(shape, key, enum_lookup)}")
            source = f"action.parameters[\"{parameter}\"] ?: MilanoValue.Null"
            extractors.append(f"{field} = {kotlin_read(shape, key, enum_lookup, source)}")
            continue
        if kind == "enum":
            enum_type = enum_lookup[("parameter", name, parameter)]
            if optional:
                fields.append(f"val {field}: {enum_type}?")
                extractors.append(
                    f"{field} = action.parameters[\"{parameter}\"]"
                    f"?.stringOrNull?.let {{ {enum_type}.from(it) }}")
            else:
                fields.append(f"val {field}: {enum_type}")
                extractors.append(
                    f"{field} = {enum_type}.from("
                    f"action.parameters[\"{parameter}\"]!!.stringOrNull!!)")
            continue
        base = KOTLIN_TYPES.get(kind, "MilanoValue")
        if base == "MilanoValue":
            fields.append(f"val {field}: MilanoValue")
            extractors.append(
                f"{field} = action.parameters[\"{parameter}\"] ?: MilanoValue.Null")
        elif optional:
            fields.append(f"val {field}: {base}?")
            extractors.append(
                f"{field} = action.parameters[\"{parameter}\"]"
                f"?.{KOTLIN_ACCESSORS[kind]}")
        else:
            fields.append(f"val {field}: {base}")
            extractors.append(
                f"{field} = action.parameters[\"{parameter}\"]!!"
                f".{KOTLIN_ACCESSORS[kind]}!!")
    entry = (doc
             + f"    data class {type_name}(\n        "
             + ",\n        ".join(fields)
             + f",\n    ) : {action_type}")
    decode = (f"                \"{name}\" -> {{\n"
              f"                    {type_name}(\n"
              + "".join(f"                        {extractor},\n" for extractor in extractors)
              + "                    )\n"
              + "                }")
    return entry, decode


def generate_kotlin(vocabulary, package, prefix):
    name, version = vocabulary["name"], vocabulary["version"]
    action_type = f"{prefix or capitalize(name)}Action"
    helper_type = f"{prefix or capitalize(name)}Vocabulary"
    lines = [
        f"// Generated from vocabulary \"{name}\" {version} by generate_bindings.py.",
        "// Do not edit; regenerate when the vocabulary changes.",
        f"package {package}",
        "",
        "import dev.getmilano.MilanoAction",
        "import dev.getmilano.MilanoEngine",
        "import dev.getmilano.MilanoNode",
        "import dev.getmilano.MilanoValue",
        "",
    ]
    enums, records, enum_lookup = collect_sites(vocabulary, prefix)
    for enum_type, enum_members, doc in enums:
        lines.append(f"/** {doc} Gate-guaranteed: decoding never fails. */")
        lines.append(f"enum class {enum_type}(")
        lines.append("    val value: String,")
        lines.append(") {")
        for member in enum_members:
            lines.append(f"    {capitalize(member)}(\"{member}\"),")
        lines.append("    ;")
        lines.append("")
        lines.append("    companion object {")
        lines.append(f"        fun from(value: String): {enum_type} ="
                     " entries.first { it.value == value }")
        lines.append("    }")
        lines.append("}")
        lines.append("")
    for record_type, fields, doc, key in records:
        lines.append(kotlin_record(record_type, fields, doc, key, enum_lookup))
        lines.append("")
    for component in sorted(vocabulary.get("components", {})):
        declaration = vocabulary["components"][component]
        lines.append(f"/** Typed view of a resolved [{component}] node;"
                     " non-null accessors are gate-guaranteed. */")
        members = [kotlin_property(
                       prop, declaration["properties"][prop],
                       enum_lookup.get(("property", component, prop)),
                       ("property", component, prop), enum_lookup)
                   for prop in sorted(declaration.get("properties", {}))]
        members += [kotlin_emitter(
                        event, declaration["events"][event],
                        enum_lookup.get(("event", component, event)),
                        ("event", component, event), enum_lookup)
                    for event in sorted(declaration.get("events", {}))]
        lines.append(f"class {prefix}{component}Node(")
        lines.append("    val node: MilanoNode,")
        if members:
            lines.append(") {")
            lines.append("\n\n".join(members))
            lines.append("}")
        else:
            lines.append(")")
        lines.append("")

    entries, decodes = [], []
    for action in sorted(vocabulary.get("actions", {})):
        entry, decode = kotlin_action_entry(
            action, vocabulary["actions"][action], action_type, enum_lookup)
        entries.append(entry)
        decodes.append(decode)
    lines.append("/** Every custom action this vocabulary declares, decoded from dispatch. */")
    lines.append(f"sealed interface {action_type} {{")
    lines.append("\n\n".join(entries))
    lines.append("")
    lines.append("    /** An action outside this vocabulary's declarations. */")
    lines.append("    data class Unrecognized(")
    lines.append("        val action: MilanoAction,")
    lines.append(f"    ) : {action_type}")
    lines.append("")
    lines.append("    companion object {")
    lines.append(f"        fun from(action: MilanoAction): {action_type} =")
    lines.append("            when (action.name) {")
    lines.append("\n\n".join(decodes + ["                else -> {\n"
                                        "                    Unrecognized(action)\n"
                                        "                }"]))
    lines.append("            }")
    lines.append("    }")
    lines.append("}")
    lines.append("")
    lines.append("/** The vocabulary these bindings were generated from. */")
    lines.append(f"object {helper_type} {{")
    lines.append(f"    const val NAME: String = \"{name}\"")
    lines.append(f"    const val VERSION: String = \"{version}\"")
    lines.append("")
    lines.append("    /** Refuses to run against an engine holding a different vocabulary. */")
    lines.append("    fun assertMatches(engine: MilanoEngine) {")
    lines.append("        check(engine.vocabularyName == NAME"
                 " && engine.vocabularyVersion == VERSION) {")
    lines.append("            \"bindings generated from $NAME@$VERSION, engine holds\" +")
    lines.append("                \" ${engine.vocabularyName}@${engine.vocabularyVersion}\"")
    lines.append("        }")
    lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------


def lower_first(name):
    return name[0].lower() + name[1:]


def ts_type(shape, key, lookup):
    base = {"bool": "boolean", "int": "bigint", "double": "number", "string": "string"}.get(shape.kind)
    if shape.kind in ("enum", "record"):
        base = lookup[key]
    elif shape.kind == "array":
        base = "readonly " + ts_type(shape.element, key + ("item",), lookup) + "[]"
        if shape.element.optional or shape.element.kind == "array":
            base = "readonly (" + ts_type(shape.element, key + ("item",), lookup) + ")[]"
    return base + (" | null" if shape.optional else "")


def ts_read(shape, key, lookup, expr, depth=0):
    """An expression of `ts_type` reading the MilanoValue `expr`."""
    if shape.kind in TS_ACCESSORS:
        if shape.optional:
            return f"{postfix(expr)}.{TS_ACCESSORS[shape.kind]}"
        return f"({postfix(expr)}.{TS_ACCESSORS[shape.kind]} as {TS_TYPES[shape.kind]})"
    if shape.kind == "enum":
        return f"({postfix(expr)}.stringValue as {ts_type(shape, key, lookup)})"
    if shape.kind == "record":
        record_type = lookup[key]
        if shape.optional:
            return f"({postfix(expr)}.isNull ? null : new {record_type}({expr}))"
        return f"new {record_type}({expr})"
    item = element_name(depth)
    inner = ts_read(shape.element, key + ("item",), lookup, item, depth + 1)
    if shape.optional:
        return f"({postfix(expr)}.arrayValue?.map(({item}) => {inner}) ?? null)"
    return f"({postfix(expr)}.arrayValue as readonly MilanoValue[]).map(({item}) => {inner})"


def ts_write(shape, key, lookup, expr, depth=0):
    """A MilanoValue expression wrapping the typed `expr`."""
    if shape.kind in TS_WRAP:
        if shape.optional:
            return f"{expr} === null ? MilanoValue.null : {TS_WRAP[shape.kind]}({expr})"
        return f"{TS_WRAP[shape.kind]}({expr})"
    if shape.kind == "enum":
        if shape.optional:
            return f"{expr} === null ? MilanoValue.null : MilanoValue.string({expr})"
        return f"MilanoValue.string({expr})"
    if shape.kind == "record":
        return f"{expr} === null ? MilanoValue.null : {expr}.value" if shape.optional else f"{expr}.value"
    item = element_name(depth)
    inner = ts_write(shape.element, key + ("item",), lookup, item, depth + 1)
    if shape.optional:
        return f"{expr} === null ? MilanoValue.null : MilanoValue.array({expr}.map(({item}) => {inner}))"
    return f"MilanoValue.array({expr}.map(({item}) => {inner}))"


def ts_record(type_name, fields, doc, key, lookup):
    lines = [f"/** {doc} Non-optional accessors are gate-guaranteed. */",
             f"export class {type_name} {{",
             "  readonly value: MilanoValue;",
             "",
             "  constructor(value: MilanoValue) {",
             "    this.value = value;",
             "  }"]
    if fields:
        parameters = [f"readonly {name}: {ts_type(shape, key + ('field', name), lookup)}"
                      for name, shape in fields]
        signature = f"  static of(fields: {{ {'; '.join(parameters)} }}): {type_name} {{"
        lines.append("")
        if len(signature) <= 100:
            lines.append(signature)
        else:
            lines.append("  static of(fields: {")
            for parameter in parameters:
                lines.append(f"    {parameter};")
            lines.append(f"  }}): {type_name} {{")
        lines.append(f"    return new {type_name}(MilanoValue.record({{")
        for name, shape in fields:
            written = ts_write(shape, key + ('field', name), lookup, f'fields.{name}')
            if fits(f"      {name}: {written},"):
                lines.append(f"      {name}: {written},")
            else:
                lines.extend([f"      {name}:", f"        {written},"])
        lines.append("    }));")
        lines.append("  }")
    for name, shape in fields:
        lines.append("")
        read = ts_read(shape, key + ("field", name), lookup, f'this.field("{name}")')
        declared = f"  get {name}(): {ts_type(shape, key + ('field', name), lookup)}"
        if fits(f"{declared} {{ return {read}; }}"):
            lines.append(f"{declared} {{ return {read}; }}")
        else:
            lines.extend([f"{declared} {{", f"    return {read};", "  }"])
    lines.append("")
    lines.append("  private field(name: string): MilanoValue {")
    lines.append("    return this.value.recordValue?.[name] ?? MilanoValue.null;")
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines)


def ts_property(name, descriptor, enum_type=None, key=None, lookup=None):
    """A getter. Non-optional reads are gate-guaranteed, so they assert the
    type rather than defaulting: a fallback would hide a contract break."""
    kind, optional, element = parse_descriptor(descriptor)
    read = f'this.node.property("{name}")'
    shape = Shape(descriptor)
    if kind == "record" or (kind == "array" and element not in TS_TYPES):
        return (f"  get {name}(): {ts_type(shape, key, lookup)} {{\n"
                f"    return {ts_read(shape, key, lookup, read)};\n"
                f"  }}")
    if kind == "enum":
        suffix = " | null" if optional else ""
        return (f"  get {name}(): {enum_type}{suffix} {{\n"
                f"    return {read}.stringValue as {enum_type}{suffix};\n"
                f"  }}")
    if kind in TS_TYPES:
        base, accessor = TS_TYPES[kind], TS_ACCESSORS[kind]
        if optional:
            return f"  get {name}(): {base} | null {{ return {read}.{accessor}; }}"
        return f"  get {name}(): {base} {{ return {read}.{accessor} as {base}; }}"
    if kind == "array" and element in TS_TYPES:
        base, accessor = TS_TYPES[element], TS_ACCESSORS[element]
        suffix = " | null" if optional else ""
        cast = f"readonly MilanoValue[]{suffix}"
        mapped = (f"{read}.arrayValue as {cast}")
        if optional:
            return (f"  get {name}(): readonly {base}[] | null {{\n"
                    f"    const items = {mapped};\n"
                    f"    return items === null ? null"
                    f" : items.map((item) => item.{accessor} as {base});\n"
                    f"  }}")
        return (f"  get {name}(): readonly {base}[] {{\n"
                f"    return ({mapped}).map((item) => item.{accessor} as {base});\n"
                f"  }}")
    note = " record-typed:" if kind == "record" else ""
    return (f"  /** The raw value;{note} read fields through MilanoValue accessors. */\n"
            f"  get {name}(): MilanoValue {{ return {read}; }}")


def ts_emitter(event, payload_descriptor, enum_type=None, key=None, lookup=None):
    method = f"emit{capitalize(event)}"
    if payload_descriptor is None:
        return f'  {method}(): void {{ this.node.emit("{event}"); }}'
    kind, optional, element = parse_descriptor(payload_descriptor)
    shape = Shape(payload_descriptor)
    if kind == "record" or (kind == "array" and element not in TS_TYPES):
        return (f"  {method}(payload: {ts_type(shape, key, lookup)}): void {{\n"
                f'    this.node.emit("{event}", {ts_write(shape, key, lookup, "payload")});\n'
                f"  }}")
    if kind == "enum":
        suffix = " | null" if optional else ""
        wrapped = (f"payload === null ? MilanoValue.null : MilanoValue.string(payload)"
                   if optional else "MilanoValue.string(payload)")
        return (f"  {method}(payload: {enum_type}{suffix}): void {{\n"
                f'    this.node.emit("{event}", {wrapped});\n'
                f"  }}")
    if kind not in TS_TYPES:
        return (f"  {method}(payload: MilanoValue): void "
                f'{{ this.node.emit("{event}", payload); }}')
    base, wrap = TS_TYPES[kind], TS_WRAP[kind]
    if optional:
        return (f"  {method}(payload: {base} | null): void {{\n"
                f'    this.node.emit("{event}",'
                f" payload === null ? MilanoValue.null : {wrap}(payload));\n"
                f"  }}")
    return (f"  {method}(payload: {base}): void "
            f'{{ this.node.emit("{event}", {wrap}(payload)); }}')


def ts_action_member(name, declaration, enum_lookup):
    """One arm of the action union, plus the case that decodes it."""
    parameters = declaration.get("parameters", {})
    notes = action_notes(declaration)
    doc = doc_block(notes, "  ")
    fields, reads = [], []
    for parameter, descriptor in sorted(parameters.items()):
        kind, optional, element = parse_descriptor(descriptor)
        read = f'action.parameters["{parameter}"]'
        shape = Shape(descriptor)
        if kind == "record" or (kind == "array" and element not in TS_TYPES):
            key = ("parameter", name, parameter)
            fields.append(f"readonly {parameter}: {ts_type(shape, key, enum_lookup)}")
            reads.append(f"{parameter}: {ts_read(shape, key, enum_lookup, f'{read} ?? MilanoValue.null')}")
            continue
        if kind == "enum":
            enum_type = enum_lookup[("parameter", name, parameter)]
            suffix = " | null" if optional else ""
            fields.append(f"readonly {parameter}: {enum_type}{suffix}")
            reads.append(f"{parameter}: {read}?.stringValue as {enum_type}{suffix}")
            continue
        if kind not in TS_TYPES:
            fields.append(f"readonly {parameter}: MilanoValue")
            reads.append(f"{parameter}: {read} ?? MilanoValue.null")
            continue
        base, accessor = TS_TYPES[kind], TS_ACCESSORS[kind]
        suffix = " | null" if optional else ""
        fields.append(f"readonly {parameter}: {base}{suffix}")
        reads.append(f"{parameter}: {read}?.{accessor} as {base}{suffix}")
    if fields:
        one_line = f'  | {{ readonly kind: "{name}"; ' + "; ".join(fields) + " }"
        if fits(one_line):
            arm = doc + one_line
        else:
            members = "".join(f"      readonly {field[len('readonly '):]};\n"
                              if field.startswith("readonly ") else f"      {field};\n"
                              for field in fields)
            arm = doc + (f'  | {{\n      readonly kind: "{name}";\n{members}    }}')
        joined = ", ".join(reads)
        returned = f'      return {{ kind: "{name}", {joined} }};'
        if not fits(returned):
            entries = ""
            for read in reads:
                if fits(f"        {read},"):
                    entries += f"        {read},\n"
                    continue
                label, _, expression = read.partition(": ")
                broken = broken_expression(expression, "        ", [" ? ", " : "])
                if broken is None:
                    entries += f"        {read},\n"
                    continue
                entries += f"        {label}: {broken[0]}\n"
                entries += "".join(f"{line}\n" for line in broken[1:-1])
                entries += f"        {broken[-1]},\n"
            returned = (f'      return {{\n        kind: "{name}",\n{entries}      }};')
        case = (f'    case "{name}":\n' + returned)
    else:
        arm = doc + f'  | {{ readonly kind: "{name}" }}'
        case = (f'    case "{name}":\n'
                f'      return {{ kind: "{name}" }};')
    return arm, case


def generate_ts(vocabulary, prefix, core_import):
    name, version = vocabulary["name"], vocabulary["version"]
    enums, records, enum_lookup = collect_sites(vocabulary, prefix)
    lines = [
        f'// Generated from vocabulary "{name}" {version} by generate_bindings.py.',
        "// Do not edit; regenerate when the vocabulary changes.",
        "",
        f'import {{ MilanoValue }} from "{core_import}";',
        f'import type {{ MilanoAction }} from "{core_import}";',
        "",
        "/**",
        " * What these wrappers need from a resolved node. The React binding's",
        " * `MilanoNode` satisfies it, and so does any other host wrapper, so",
        " * the generated file never depends on a UI toolkit.",
        " */",
        "export interface MilanoNodeLike {",
        "  property(name: string): MilanoValue;",
        "  emit(event: string, payload?: MilanoValue | null): void;",
        "}",
        "",
    ]
    for enum_type, enum_members, doc in enums:
        lines.append(f"/** {doc} Gate-guaranteed: the value is always a member. */")
        members = " | ".join(f'"{member}"' for member in enum_members)
        lines.append(f"export type {enum_type} = {members};")
        lines.append("")
    for record_type, fields, doc, key in records:
        lines.append(ts_record(record_type, fields, doc, key, enum_lookup))
        lines.append("")

    for component in sorted(vocabulary.get("components", {})):
        declaration = vocabulary["components"][component]
        lines.append(f"/** Typed view of a resolved `{component}` node."
                     " Non-optional accessors are gate-guaranteed. */")
        lines.append(f"export class {prefix}{component}Node {{")
        lines.append("  readonly node: MilanoNodeLike;")
        lines.append("")
        lines.append("  constructor(node: MilanoNodeLike) {")
        lines.append("    this.node = node;")
        lines.append("  }")
        for prop in sorted(declaration.get("properties", {})):
            lines.append("")
            lines.append(ts_property(
                prop, declaration["properties"][prop],
                enum_lookup.get(("property", component, prop)),
                ("property", component, prop), enum_lookup))
        for event in sorted(declaration.get("events", {})):
            lines.append("")
            lines.append(ts_emitter(
                event, declaration["events"][event],
                enum_lookup.get(("event", component, event)),
                ("event", component, event), enum_lookup))
        lines.append("}")
        lines.append("")

    arms, cases = [], []
    for action in sorted(vocabulary.get("actions", {})):
        arm, case = ts_action_member(action, vocabulary["actions"][action], enum_lookup)
        arms.append(arm)
        cases.append(case)
    lines.append("/** Every custom action this vocabulary declares, decoded from dispatch. */")
    lines.append(f"export type {prefix}Action =")
    lines.extend(arms)
    lines.append("  /** An action outside this vocabulary's declarations"
                 " (builder-declared, or a newer vocabulary). */")
    lines.append('  | { readonly kind: "unrecognized"; readonly action: MilanoAction };')
    lines.append("")
    lines.append("/** Decodes a dispatched action; the switch over `kind` is exhaustive. */")
    lines.append(f"export function {lower_first(prefix)}Action"
                 f"(action: MilanoAction): {prefix}Action {{")
    lines.append("  switch (action.name) {")
    lines.extend(cases)
    lines.append("    default:")
    lines.append('      return { kind: "unrecognized", action };')
    lines.append("  }")
    lines.append("}")
    lines.append("")
    lines.append("/** The vocabulary these bindings were generated from. */")
    lines.append(f"export const {prefix}Vocabulary = {{")
    lines.append(f'  name: "{name}",')
    lines.append(f'  version: "{version}",')
    lines.append("")
    lines.append("  /** Throws if the engine holds a different vocabulary. */")
    lines.append("  assertMatches(engine: {"
                 " readonly vocabulary: { readonly name: string;"
                 " readonly version: string } }): void {")
    lines.append("    const held = engine.vocabulary;")
    lines.append(f'    if (held.name !== "{name}" || held.version !== "{version}") {{')
    lines.append("      throw new Error(")
    lines.append(f'        `bindings generated from {name}@{version}, engine holds'
                 ' ${held.name}@${held.version}`,')
    lines.append("      );")
    lines.append("    }")
    lines.append("  },")
    lines.append("} as const;")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vocabulary", help="path to the vocabulary artifact")
    parser.add_argument("--swift-prefix", default=None,
                        help="type prefix for Swift (default: capitalized vocabulary name)")
    parser.add_argument("--swift-out", help="Swift output file")
    parser.add_argument("--kotlin-package", help="Kotlin package for the generated file")
    parser.add_argument("--kotlin-prefix", default="",
                        help="optional type prefix for Kotlin (default: none)")
    parser.add_argument("--kotlin-out", help="Kotlin output file")
    parser.add_argument("--ts-prefix", default=None,
                        help="type prefix for TypeScript (default: capitalized vocabulary name)")
    parser.add_argument("--ts-out", help="TypeScript output file")
    parser.add_argument("--ts-core-import", default="@get-milano/core",
                        help="module the generated TypeScript imports MilanoValue from")
    args = parser.parse_args()

    vocabulary = json.load(open(args.vocabulary))
    wrote = []
    if args.swift_out:
        prefix = args.swift_prefix or capitalize(vocabulary["name"])
        with open(args.swift_out, "w") as handle:
            handle.write(generate_swift(vocabulary, prefix))
        wrote.append(args.swift_out)
    if args.kotlin_out:
        if not args.kotlin_package:
            print("--kotlin-out requires --kotlin-package", file=sys.stderr)
            return 2
        with open(args.kotlin_out, "w") as handle:
            handle.write(generate_kotlin(vocabulary, args.kotlin_package, args.kotlin_prefix))
        wrote.append(args.kotlin_out)
    if args.ts_out:
        prefix = args.ts_prefix or capitalize(vocabulary["name"])
        with open(args.ts_out, "w") as handle:
            handle.write(generate_ts(vocabulary, prefix, args.ts_core_import))
        wrote.append(args.ts_out)
    if not wrote:
        print("nothing to do: pass --swift-out, --kotlin-out and/or --ts-out",
              file=sys.stderr)
        return 2
    for path in wrote:
        print(f"generated {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
