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
arrays of primitives get native types; enum-typed properties, event
payloads, and action parameters get generated Swift/Kotlin enums (one
nominal type per declaration site); record-typed values and arrays of
non-primitives surface as raw MilanoValue.
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


def collect_enums(vocabulary, prefix):
    """Every enum declaration site, in deterministic order: one nominal
    generated type per site. Returns [(type_name, members, doc)] plus a
    lookup from site key to type name."""
    sites, lookup = [], {}

    def add(key, type_name, members, doc):
        entry_names = [capitalize(member) for member in sorted(members)]
        if len(set(entry_names)) != len(entry_names):
            raise SystemExit(f"enum at {key} has members that collide when"
                             f" capitalized; rename them")
        sites.append((type_name, sorted(members), doc))
        lookup[key] = type_name

    for component in sorted(vocabulary.get("components", {})):
        declaration = vocabulary["components"][component]
        for prop in sorted(declaration.get("properties", {}) or {}):
            descriptor = declaration["properties"][prop]
            if isinstance(descriptor, dict) and "enum" in descriptor:
                add(("property", component, prop),
                    enum_type_name(prefix, component, prop),
                    descriptor["enum"],
                    f"Members of the `{prop}` enum on `{component}`.")
        for event in sorted(declaration.get("events", {}) or {}):
            descriptor = declaration["events"][event]
            if isinstance(descriptor, dict) and "enum" in descriptor:
                add(("event", component, event),
                    enum_type_name(prefix, component, event, "payload"),
                    descriptor["enum"],
                    f"Members of the `{event}` payload enum on `{component}`.")
    for action in sorted(vocabulary.get("actions", {})):
        declaration = vocabulary["actions"][action]
        for parameter in sorted(declaration.get("parameters", {}) or {}):
            descriptor = declaration["parameters"][parameter]
            if isinstance(descriptor, dict) and "enum" in descriptor:
                add(("parameter", action, parameter),
                    enum_type_name(prefix, action, parameter),
                    descriptor["enum"],
                    f"Members of the `{parameter}` enum on action `{action}`.")
    return sites, lookup


# ---------------------------------------------------------------------------
# Swift
# ---------------------------------------------------------------------------


def swift_property(name, descriptor, enum_type=None):
    kind, optional, element = parse_descriptor(descriptor)
    declared = escape_swift(name)
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


def swift_emitter(event, payload_descriptor, enum_type=None):
    method = f"emit{capitalize(event)}"
    if payload_descriptor is None:
        return f"    public func {method}() {{ node.emit(\"{event}\") }}"
    kind, optional, _ = parse_descriptor(payload_descriptor)
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


def result_note(declaration):
    """A doc line for actions declaring a completion result."""
    descriptor = declaration.get("result")
    if descriptor is None:
        return None
    rendered = descriptor if isinstance(descriptor, str) \
        else json.dumps(descriptor, sort_keys=True)
    return (f"The handler completes it with a `{rendered}` result,"
            f" bound to `result` in onSuccess.")


def swift_action_case(name, declaration, enum_lookup):
    parameters = declaration.get("parameters", {})
    note = result_note(declaration)
    doc = f"    /// {note}\n" if note else ""
    declared = escape_swift(name)
    if not parameters:
        return (doc + f"    case {declared}",
                f"        case \"{name}\":\n            self = .{declared}")
    labels, extractors = [], []
    for parameter, descriptor in sorted(parameters.items()):
        kind, optional, _ = parse_descriptor(descriptor)
        label = escape_swift(parameter)
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
    enums, enum_lookup = collect_enums(vocabulary, prefix)
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
                enum_lookup.get(("property", component, prop))))
        for event in sorted(declaration.get("events", {})):
            lines.append(swift_emitter(
                event, declaration["events"][event],
                enum_lookup.get(("event", component, event))))
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


def kotlin_property(name, descriptor, enum_type=None):
    kind, optional, element = parse_descriptor(descriptor)
    declared = escape_kotlin(name)
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


def kotlin_emitter(event, payload_descriptor, enum_type=None):
    method = f"emit{capitalize(event)}"
    if payload_descriptor is None:
        return f"    fun {method}() = node.emit(\"{event}\")"
    kind, optional, _ = parse_descriptor(payload_descriptor)
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
    note = result_note(declaration)
    doc = f"    /** {note} */\n" if note else ""
    if not parameters:
        entry = doc + f"    data object {type_name} : {action_type}"
        decode = (f"                \"{name}\" -> {{\n"
                  f"                    {type_name}\n"
                  f"                }}")
        return entry, decode
    fields, extractors = [], []
    for parameter, descriptor in sorted(parameters.items()):
        field = escape_kotlin(parameter)
        kind, optional, _ = parse_descriptor(descriptor)
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
    enums, enum_lookup = collect_enums(vocabulary, prefix)
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
    for component in sorted(vocabulary.get("components", {})):
        declaration = vocabulary["components"][component]
        lines.append(f"/** Typed view of a resolved [{component}] node;"
                     " non-null accessors are gate-guaranteed. */")
        members = [kotlin_property(
                       prop, declaration["properties"][prop],
                       enum_lookup.get(("property", component, prop)))
                   for prop in sorted(declaration.get("properties", {}))]
        members += [kotlin_emitter(
                        event, declaration["events"][event],
                        enum_lookup.get(("event", component, event)))
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


def ts_property(name, descriptor, enum_type=None):
    """A getter. Non-optional reads are gate-guaranteed, so they assert the
    type rather than defaulting: a fallback would hide a contract break."""
    kind, optional, element = parse_descriptor(descriptor)
    read = f'this.node.property("{name}")'
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


def ts_emitter(event, payload_descriptor, enum_type=None):
    method = f"emit{capitalize(event)}"
    if payload_descriptor is None:
        return f'  {method}(): void {{ this.node.emit("{event}"); }}'
    kind, optional, _ = parse_descriptor(payload_descriptor)
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
    note = result_note(declaration)
    doc = f"  /** {note} */\n" if note else ""
    fields, reads = [], []
    for parameter, descriptor in sorted(parameters.items()):
        kind, optional, _ = parse_descriptor(descriptor)
        read = f'action.parameters["{parameter}"]'
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
        arm = doc + (f'  | {{ readonly kind: "{name}"; ' + "; ".join(fields) + " }")
        joined = ", ".join(reads)
        case = (f'    case "{name}":\n'
                f'      return {{ kind: "{name}", {joined} }};')
    else:
        arm = doc + f'  | {{ readonly kind: "{name}" }}'
        case = (f'    case "{name}":\n'
                f'      return {{ kind: "{name}" }};')
    return arm, case


def generate_ts(vocabulary, prefix, core_import):
    name, version = vocabulary["name"], vocabulary["version"]
    enums, enum_lookup = collect_enums(vocabulary, prefix)
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
                enum_lookup.get(("property", component, prop))))
        for event in sorted(declaration.get("events", {})):
            lines.append("")
            lines.append(ts_emitter(
                event, declaration["events"][event],
                enum_lookup.get(("event", component, event))))
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
