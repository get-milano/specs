---
title: "Document model"
nav_order: 2
---

# Milano Document Model

**Status:** Stable v1.0.0 · 2026-08-16

Defines the abstract document model and its canonical JSON encoding: the top-level structure, the node envelope, values and expressions, core constructs, identity, validation, the error taxonomy, and resource limits. Everything here operates within the guarantees fixed by [Foundations](00-foundations.html).

**Version 1.0 scope.** Per Foundations, v1.0 targets banners, interstitials, and simple document-defined forms.

## Document structure

A document is a single JSON object, encoded in UTF-8, with reserved top-level sections. Unknown core fields follow the contract tolerance rules from Foundations.

| Section | Required | Purpose |
|---|---|---|
| `version` | yes | The contract version the document targets (major.minor.patch) |
| `vocabulary` | no | The vocabulary the document requires: a `name` and an optional `min` version (major.minor.patch) |
| `context` | no | Declaration of the context keys the document reads: name and type |
| `state` | no | Document-level state declarations: name and type |
| `root` | yes | The single root node |
| `metadata` | no | Free-form producer data as a JSON object (any other shape is `MalformedDocument`); never interpreted by Milano, passed through to the host |

Documents separate structure from data. The `context` and `state` sections declare shapes only; no section of a document ever carries a variable data value, so a document is cacheable independently of the data it renders. Context values are supplied by the host's context source; every declared key is required, and values are validated at the gate and on every update. State initial values are supplied by the host's asynchronous state data provider, awaited during building and validated against the declarations. Provider failures propagate to the caller unchanged: they are host errors, not Milano errors.

## Type system

Every declaration (state, context, component properties, action parameters, event payloads) uses one type language:

- Primitives: `bool`, `int` (64-bit signed), `double` (IEEE 754 binary64), `string` (Unicode).
- `enum`: a closed set of named string values. Members follow the identifier grammar and must be unique; the set must be non-empty. At runtime an enum value is its member string; only the static type knows the set.
- `array` of any type.
- `record` with named, typed fields.
- Types are non-nullable by default. Any type may be marked optional; JSON `null` is valid only for optional types, and an omitted optional value is equivalent to `null`.

In JSON, a type descriptor takes one of four forms:

- A primitive is its name string, with a trailing `?` for optional: `"int"`, `"string?"`.
- An enum is an object with an `enum` key holding the member list, plus `"optional": true` when optional: `{"enum": ["info", "warning", "danger"]}`.
- An array is an object with an `array` key holding the element's type descriptor, plus `"optional": true` when the array itself is optional.
- A record is an object with a `record` key holding a map of field name to type descriptor, plus `"optional": true` when the record itself is optional.

Two enum types are the same exactly when their member sets are equal: enum identity is structural, like records.

Integer and floating-point behavior (ranges, overflow, coercion rules in expressions) is fixed by the expression language spec and conformance-tested; a JSON number with a fractional part never satisfies an `int` declaration.

Validation of data values (supplied context, provider state, literal properties and parameters) against declarations follows two further rules, identical in every runtime:

- An `int` value satisfies a `double` declaration and is canonicalized to `double`, mirroring expression promotion. A `double` value never satisfies an `int` declaration.
- Record values are validated strictly against their declared shape: an undeclared field is a mismatch; a missing optional field canonicalizes to `null`; a missing non-optional field is a mismatch.
- An `enum` declaration is satisfied only by one of its member strings. A non-member string is a mismatch at every boundary this rule reaches: literal properties and parameters at the gate, supplied state and context at build, context updates, event emissions, and completion results at runtime.

## Node envelope

Every node is a JSON object with reserved keys. The envelope belongs to the contract: additions arrive only through contract versions, and a runtime encountering an envelope key it does not know applies the contract tolerance rules from Foundations (ignored, since only semantics-preserving additions can be minor).

| Key | Required | Purpose |
|---|---|---|
| `type` | yes | Component type name from the vocabulary, or a core construct name |
| `id` | no | Document-unique identifier: a non-empty string, else `MalformedDocument`; uniqueness validated at the gate |
| `properties` | no | Map of property name to value (literal or expression) |
| `children` | no | Ordered list of child nodes |
| `on` | no | Map of event name to one action or an ordered list of actions |

There is no envelope key for data: nodes reference state and context through expressions, never carry values for them.

The `$` prefix in `type` names is reserved for the contract; vocabulary component types must not begin with it. Whether a component type accepts `children` is declared by the vocabulary schema per component type; the gate enforces the declaration.

## Values and expressions

Every property value is either a literal of the declared type or an expression.

- An expression is written as a reserved single-key wrapper object; its key is the expression marker `$expr`, its value is an expression string in the grammar of the expression language spec. No other form of a value is ever dynamic: literal strings are always literal, no delimiters, no escaping rules.
- Any declared property may be dynamic. The gate type-checks each expression's result type against the property's declared type.
- Expressions read document state and host context.
- References are namespaced by reserved roots: `state`, `context`, `event` (only within `on` action bindings, giving access to the triggering event's payload), and `result` (only within the `onSuccess` bindings of an action declaring a result type, giving access to the handler's returned value; see the vocabulary schema spec).

## Actions

An action is a JSON object whose reserved `action` key names its type. Built-in actions live in the reserved `$` namespace and are always available. Custom action types use consumer-defined names with typed parameters, declared only by consumer code: globally in the engine's vocabulary, and per surface by the builder, which may grant a subset of the vocabulary's actions and declare or override signatures for its surface (see the vocabulary schema spec). Documents never declare actions. Binding a custom action outside the surface's granted set is a `SchemaViolation` with rule `action-capability`. Parameters are sibling keys of `action`, and any parameter value may be a literal or an expression (including expressions over `event`); the gate validates parameters against the granted declaration.

Like component types, action types require host code (a handler that interprets them), so declarations live with that code, never in documents. Declarations type the payload; meaning is assigned per surface by the builder's handler, so one action name may carry different behavior, and via builder overrides a different signature, on different surfaces.

| Action | Parameters | Purpose |
|---|---|---|
| `$set` | `key`: a declared top-level state key; `value`: the new value, literal or expression | Mutate document state; field-level targets inside records are not supported, the whole key is assigned |
| `$sequence` | `actions`: ordered list of actions | Run actions in order |
| `$when` | `condition`: bool expression; `then`: optional action list; `else`: optional action list | Conditional dispatch |
| custom | per its granted declaration | Routed as data to the host's action handlers |

- A bare JSON array of actions is shorthand for `$sequence`.
- Custom actions may carry `onSuccess` and `onFailure` keys, each an action or action list, bound to the handler's asynchronous completion. Built-ins complete synchronously and do not take them.
- Dispatch semantics (ordering, concurrency, completion after view teardown, event payload rules) are fixed in the state and actions spec; this spec fixes only the encoding.

## Identity and paths

- `id` is optional; when present it is a non-empty string, unique across the document. An empty `id` is an envelope violation (`MalformedDocument`), since it would be an empty reference in every report about the node.
- Every node also has a canonical structural path computed from its position: the root node's path is `root`, and each child appends `/children[i]` with its zero-based index (for example `root/children[2]/children[0]`).
- Observer reports and error details reference nodes by `id` when present, canonical path otherwise.

## Validation

The gate validates in a fixed, conformance-tested order, so identical documents fail identically on every platform:

1. Parse: well-formed JSON, correct envelope shapes.
2. Version: declared major must be in the runtime's supported set.
3. Vocabulary requirement: when the document declares one, the engine's vocabulary must carry the same `name`, and when `min` is present its `version` must be at least `min` (numeric comparison of major, minor, patch). A mismatch is a `SchemaViolation` with rule `vocabulary-requirement`, `expected` the document's demand, `found` what the engine holds. A document with no `vocabulary` section performs no check: binding stays positional, and the requirement is the producer's opt-in guard for staggered rollouts. The minimum-only form is sound because vocabulary evolution is additive within a major (see the vocabulary schema spec): any version at or above the minimum carries everything the document needs.
4. Resource limits: document size (checked on the raw bytes before parsing, alongside step 1), tree depth, and node count against the limits below; expression length is checked per expression in step 5.
5. Vocabulary walk: one pass over the tree, in document order. At each node, in order: `id` uniqueness, the reserved `$` type prefix, type resolution against the schema (unknown types trigger the unknown-type policy), properties (undeclared ones per the strict-mode rules from Foundations; declared ones type-checked, with expressions parsed and statically typed as they are encountered), children acceptance, then event bindings against the declared events and their action lists (built-in parameters against this spec, custom actions against the surface's granted action set: the vocabulary's declarations, narrowed and overridden by the builder). Because the walk is one pass, the first defect wins when a document violates several rules: document order among nodes and array elements, and the member order below within one object.
6. Data checks: context declarations versus supplied values, state declarations versus the values returned by the state data provider; every value also within the value size limit below.

Wherever a step visits the members of a JSON object (a node's `properties` and `on` bindings, an action's parameters, the `context` and `state` declarations and the values supplied for them, a vocabulary's declared parameters), it visits them in lexicographic order of the key by Unicode scalar value, never in document order. JSON defines no order for object members, and a serializer that reorders keys must not change which defect is reported first or in which order a node's expressions report; document order applies to arrays, which JSON does order: children and action lists. Identifiers are ASCII, so every platform's default string ordering agrees.

Steps 1 through 5 need only the document and the engine. Building is asynchronous overall: the gate then awaits the state data provider and completes the cross-checks. A provider failure propagates to the caller unchanged; values that do not match the declarations are a `SchemaViolation`.

Three rules complete the gate's behavior:

- Supplied context and provider values may contain keys the document does not declare; they are ignored. The document reads only what it declares, which lets one context source serve many views.
- Occurrences detected during the gate (skipped or placeholder nodes, undeclared properties) are reported to the observer only when building succeeds; a failed build reports nothing.
- When the root node itself is an unknown type under the *skip* policy, the result is a valid, empty view: there are no siblings to keep.

## Error taxonomy

The closed set of typed errors the gate can throw, with the structured detail each carries. Every error also carries a non-normative diagnostic message.

| Error | Raised when | Detail fields |
|---|---|---|
| `MalformedDocument` | Input is not well-formed JSON or violates envelope structure | Location of the defect (path when determinable) |
| `UnsupportedVersion` | Declared major is outside the runtime's supported set | Declared version; the runtime's supported majors |
| `SchemaViolation` | Vocabulary, expression typing, action encoding, event, id, or namespace rules are violated; supplied context or initial-state values do not match declarations | The rule violated; expected; found; and the node reference (id or path) when the violation is anchored to a node (document-level violations, such as a data value not matching its declaration, carry none) |
| `UnknownComponentType` | A type not declared in the vocabulary is found and the effective policy is *fail* | Node reference; the unknown type name |
| `LimitExceeded` | Any resource limit is exceeded at the gate | The limit's name; its configured value; the actual value |

The `rule` strings a `SchemaViolation` may carry are contract, pinned by the conformance suite, and so is the detail each carries (an absent cell is `null`):

| Rule | Violation | `node` | `expected` | `found` |
|---|---|---|---|---|
| `construct` | A node `type` begins with the reserved `$` prefix | the node | `component type` | the type name |
| `id-uniqueness` | A node `id` appears more than once in the document | the repeated id | | the id |
| `children` | A node carries `children` but its component type does not accept them | the node | `no children` | `children` |
| `undeclared-property` | An undeclared property on a `strict` component type | the node | | the property name |
| `property-type` | A literal property value does not match the declared type | the node | the declared type, or `enum member` | the literal's kind, or the non-member string |
| `event-binding` | An `on` entry names an event the component type does not declare | the node | `declared event` | the event name |
| `expression` | An expression fails to parse or type-check against the expected type | the node | the type the position expects | |
| `action-encoding` | A built-in or custom action violates its encoding: unknown or missing parameters, ill-typed values, an undeclared `$set` target | the node | `declared state key`, `declared parameter`, or the name of the missing required parameter | the undeclared key or parameter; none for a missing one |
| `action-capability` | A custom action outside the surface's granted set | the node | `granted action` | the action name |
| `vocabulary-requirement` | The document's declared vocabulary requirement is not met by the engine's vocabulary | | the required name, or `>=` the required minimum | the held name or version |
| `context-declaration` | A context declaration is malformed (non-identifier key, invalid descriptor) or a supplied context value does not match it | | `identifier`, the missing key, or the declared type | the malformed key, or the value's kind |
| `state-declaration` | A state declaration is malformed (non-identifier key, invalid descriptor), a provided state value does not match it, or the document declares state and the surface configured no state data provider | | `identifier`, the declared type, or `state data provider` | the malformed key, or the value's kind (`null` when the provider omitted a required value) |
| `action-handler` | The document binds custom actions and the surface configured no action handler (raised by the builder at build, before dispatch exists) | | `action handler` | |

Occurrences (rejected context updates and dropped events at runtime, skipped or placeholder nodes at the gate) are not errors: they flow to the engine observer as defined in Foundations.

## Resource limits

Defaults, adjustable per engine.

| Limit | Default |
|---|---|
| Maximum tree depth | 32 |
| Maximum node count | 10,000 |
| Maximum document size | 1 MiB |
| Maximum expression length | 1,024 Unicode scalars |
| Maximum value size | 65,536 |

The first four are gate limits: the tree, its expressions, and their lengths are fixed at the gate, and no update can grow them. Values are not fixed at the gate, so the value size limit applies wherever a value enters state or context: at the gate, to the supplied context values and the initial state values (step 6, a `LimitExceeded` with limit `maxValueSize`), and at runtime, to every context update and every `$set`, where a value past the limit rejects the update or the mutation whole and reports it (state and actions spec). Event payloads and completion results are not bounded: they live for one dispatch, and whatever a document keeps from them passes through `$set`.

The size of a value counts one for a bool, an int, a double, or null; one per Unicode scalar for a string; and, for an array or a record, one plus the sizes of its elements or fields. Record shapes and nesting are fixed by declarations, so one number bounds every value.

Limits are denial-of-service bounds for untrusted input, not performance budgets: a document within every limit can still be a poor fit for an interactive surface. Measured guidance lives in the runtime documentation.

## Notes

- An official schema, `schemas/document.schema.json` in this repository, validates the canonical encoding's structure (envelope shapes, type descriptors, expression wrappers, action encoding). Semantic rules stay with the gate: vocabulary resolution, expression typing, id uniqueness, and resource limits are not schema-checkable.
- The schemas are open wherever the contract may grow (the top level, the node envelope, the `vocabulary` section, type descriptors), because the tolerance rule in Foundations makes unknown keys there ignorable rather than invalid; the `$expr` wrapper is the one closed object, since this model defines it as exactly single-key. Strictness against typos in those objects is producer tooling's job, not the contract's: the reference checker's `--document` mode warns about unknown keys in contract-governed objects, and the vocabulary-specialized document schema is strict about component properties, which are vocabulary-governed and therefore fixed.
- `metadata` is host-only: it is never visible to expressions.
- The identifier grammar for state keys, context keys, and all vocabulary names is defined in the [vocabulary schema spec](02-vocabulary-schema.html).
- Custom action and event payload declarations are owned by the [vocabulary schema spec](02-vocabulary-schema.html). Expression grammar and semantics are owned by the [expression language spec](03-expression-language.html). Dispatch semantics are owned by the [state and actions spec](04-state-and-actions.html).
