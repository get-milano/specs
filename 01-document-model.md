---
title: "Document model"
nav_order: 2
---

# Milano Document Model

**Status:** Beta v0.1.0 · 2026-08-15

Defines the abstract document model and its canonical JSON encoding: the top-level structure, the node envelope, values and expressions, core constructs, identity, validation, the error taxonomy, and resource limits. Everything here operates within the guarantees fixed by [Foundations](00-foundations.html).

**Version 0.1 scope.** Per Foundations, v0.1 targets banners, interstitials, and simple document-defined forms.

## Document structure

A document is a single JSON object, encoded in UTF-8, with reserved top-level sections. Unknown core fields follow the contract tolerance rules from Foundations.

| Section | Required | Purpose |
|---|---|---|
| `version` | yes | The contract version the document targets (major.minor.patch) |
| `context` | no | Declaration of the context keys the document reads: name and type |
| `state` | no | Document-level state declarations: name and type |
| `actions` | no | Document-local custom action declarations, in the vocabulary schema's declaration format |
| `root` | yes | The single root node |
| `metadata` | no | Free-form producer data; validated as JSON, never interpreted by Milano, passed through to the host |

Documents separate structure from data. The `context` and `state` sections declare shapes only; no section of a document ever carries a variable data value, so a document is cacheable independently of the data it renders. Context values are supplied by the host's context source; every declared key is required, and values are validated at the gate and on every update. State initial values are supplied by the host's asynchronous state data provider, awaited during building and validated against the declarations. Provider failures propagate to the caller unchanged: they are host errors, not Milano errors.

## Type system

Every declaration (state, context, component properties, action parameters, event payloads) uses one type language:

- Primitives: `bool`, `int` (64-bit signed), `double` (IEEE 754 binary64), `string` (Unicode).
- `array` of any type.
- `record` with named, typed fields.
- Types are non-nullable by default. Any type may be marked optional; JSON `null` is valid only for optional types, and an omitted optional value is equivalent to `null`.

In JSON, a type descriptor takes one of three forms:

- A primitive is its name string, with a trailing `?` for optional: `"int"`, `"string?"`.
- An array is an object with an `array` key holding the element's type descriptor, plus `"optional": true` when the array itself is optional.
- A record is an object with a `record` key holding a map of field name to type descriptor, plus `"optional": true` when the record itself is optional.

Integer and floating-point behavior (ranges, overflow, coercion rules in expressions) is fixed by the expression language spec and conformance-tested; a JSON number with a fractional part never satisfies an `int` declaration.

Validation of data values (supplied context, provider state, literal properties and parameters) against declarations follows two further rules, identical in both runtimes:

- An `int` value satisfies a `double` declaration and is canonicalized to `double`, mirroring expression promotion. A `double` value never satisfies an `int` declaration.
- Record values are validated strictly against their declared shape: an undeclared field is a mismatch; a missing optional field canonicalizes to `null`; a missing non-optional field is a mismatch.

## Node envelope

Every node is a JSON object with reserved keys. The envelope belongs to the contract: additions arrive only through contract versions, and a runtime encountering an envelope key it does not know applies the contract tolerance rules from Foundations (ignored, since only semantics-preserving additions can be minor).

| Key | Required | Purpose |
|---|---|---|
| `type` | yes | Component type name from the vocabulary, or a core construct name |
| `id` | no | Document-unique identifier; uniqueness validated at the gate |
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
- References are namespaced by reserved roots: `state`, `context`, and `event` (only within `on` action bindings, giving access to the triggering event's payload).

## Actions

An action is a JSON object whose reserved `action` key names its type. Built-in actions live in the reserved `$` namespace; custom action types use consumer-defined names with typed parameters, declared either in the engine's vocabulary (global, shared by every document) or in the document's own `actions` section (local). Local declarations use the same format and are validated identically; a local name that collides with a vocabulary action is a `SchemaViolation`. Dispatch is identical for both: the host handler receives name and parameters as data either way. Parameters are sibling keys of `action`, and any parameter value may be a literal or an expression (including expressions over `event`).

Components have no local equivalent: a component type requires a registered renderer, which is code, so component types are global by nature.

| Action | Parameters | Purpose |
|---|---|---|
| `$set` | `key`: a declared top-level state key; `value`: the new value, literal or expression | Mutate document state; field-level targets inside records are not supported, the whole key is assigned |
| `$sequence` | `actions`: ordered list of actions | Run actions in order |
| `$when` | `condition`: bool expression; `then`: action list; `else`: optional action list | Conditional dispatch |
| custom | per its vocabulary declaration | Routed as data to the host's action handlers |

- A bare JSON array of actions is shorthand for `$sequence`.
- Custom actions may carry `onSuccess` and `onFailure` keys, each an action or action list, bound to the handler's asynchronous completion. Built-ins complete synchronously and do not take them.
- Dispatch semantics (ordering, concurrency, completion after view teardown, event payload rules) are fixed in the state and actions spec; this spec fixes only the encoding.

## Identity and paths

- `id` is optional and must be unique across the document.
- Every node also has a canonical structural path computed from its position: the root node's path is `root`, and each child appends `/children[i]` with its zero-based index (for example `root/children[2]/children[0]`).
- Observer reports and error details reference nodes by `id` when present, canonical path otherwise.

## Validation

The gate validates in a fixed, conformance-tested order, so identical documents fail identically on both platforms:

1. Parse: well-formed JSON, correct envelope shapes.
2. Version: declared major must be in the runtime's supported set.
3. Vocabulary: every `type` resolved against the schema; properties and events validated per component type; action objects validated (built-in parameters against this spec, custom actions against their vocabulary or document-local declarations); unknown types trigger the unknown-type policy; undeclared properties follow the strict-mode rules from Foundations.
4. Expressions: parse every expression, type-check results against declared property, state, and context types.
5. Cross-checks: `id` uniqueness, event bindings against declared events, context declarations versus supplied values, state declarations versus the values returned by the state data provider.

Steps 1 through 4 need only the document and the engine. Building is asynchronous overall: the gate then awaits the state data provider and completes the cross-checks. A provider failure propagates to the caller unchanged; values that do not match the declarations are a `SchemaViolation`.

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
| `SchemaViolation` | Vocabulary, expression typing, action encoding, event, id, or namespace rules are violated; supplied context or initial-state values do not match declarations | Node reference (id or path); the rule violated; expected; found |
| `UnknownComponentType` | A type not declared in the vocabulary is found and the effective policy is *fail* | Node reference; the unknown type name |
| `LimitExceeded` | Any resource limit is exceeded at the gate | The limit's name; its configured value; the actual value |

Runtime occurrences (rejected context updates, over-limit updates, dropped events, skipped or placeholder nodes) are not errors: they flow to the engine observer as defined in Foundations.

## Resource limits

Defaults, adjustable per engine.

| Limit | Default |
|---|---|
| Maximum tree depth | 32 |
| Maximum node count | 10,000 |
| Maximum document size | 1 MiB |
| Maximum expression length | 1,024 characters |

Gate limits bound the document; update-triggered evaluation is bounded at runtime, where an over-limit update is rejected atomically per Foundations.

## Notes

- An official schema, `schemas/document.schema.json` in this repository, validates the canonical encoding's structure (envelope shapes, type descriptors, expression wrappers, action encoding). Semantic rules stay with the gate: vocabulary resolution, expression typing, id uniqueness, and resource limits are not schema-checkable.
- `metadata` is host-only: it is never visible to expressions.
- The identifier grammar for state keys, context keys, and all vocabulary names is defined in the [vocabulary schema spec](02-vocabulary-schema.html).
- Custom action and event payload declarations are owned by the [vocabulary schema spec](02-vocabulary-schema.html). Expression grammar and semantics are owned by the [expression language spec](03-expression-language.html). Dispatch semantics are owned by the [state and actions spec](04-state-and-actions.html).
