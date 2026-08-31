---
title: "Vocabulary schema"
nav_order: 3
---

# Milano Vocabulary Schema

**Status:** Stable · contract 2.1 · repository release 2.1.0 · 2026-08-31

Defines the machine-readable artifact in which a consumer declares their vocabulary: component types, events, custom actions, and host functions. The engine consumes this artifact; the gate validates every document against it. It is the contract between document producers and the client, kept in sync by tooling, not discipline.

## Artifact structure

A vocabulary is a single JSON object, encoded in UTF-8, with reserved top-level fields. The artifact format is governed by the Milano contract and follows the same versioning and tolerance rules as documents.

| Field | Required | Purpose |
|---|---|---|
| `milano` | yes | The contract version the artifact targets (major.minor.patch) |
| `name` | yes | The vocabulary's name |
| `version` | yes | The vocabulary's own version, consumer-owned, in major.minor.patch form; the gate compares it against a document's declared `vocabulary.min` requirement, and the engine exposes it with the name (runtime API spec) for tooling and telemetry; reports do not carry it |
| `components` | yes | Map of component type name to component declaration |
| `actions` | no | Map of custom action name to action declaration |
| `functions` | no | Contract 2.1. Map of host function name to function declaration |

## Naming

One identifier grammar applies to the vocabulary's own `name`, component type names, property names, event names, action names, function names, enum members, record field names, and the state and context keys of documents: an ASCII letter followed by ASCII letters, digits, or underscores (`[A-Za-z][A-Za-z0-9_]*`). Unicode letters and digits are not letters and digits here, exactly as in the expression grammar. Case-sensitive. Names must not begin with `$`, which is reserved for the contract.

## Component declarations

Each entry in `components` declares one component type:

| Field | Required | Purpose |
|---|---|---|
| `properties` | no | Map of property name to a type descriptor (per the document model's type system) |
| `events` | no | Map of event name to a payload type descriptor, or `null` for payload-less events |
| `children` | no | Boolean, default `false`: whether nodes of this type accept `children` |
| `strict` | no | Boolean, default `false`: when `true`, undeclared properties on nodes of this type are a `SchemaViolation` instead of ignored-and-reported |

Optional properties (types marked optional: a trailing `?` on a primitive, `"optional": true` on the others) may be omitted in documents; the renderer receives `null`. There are no default values in v1.0: what a renderer does with `null` is the consumer's decision, made in the renderer.

## Action declarations

Each entry in `actions` declares one custom action type:

| Field | Required | Purpose |
|---|---|---|
| `parameters` | no | Map of parameter name to a type descriptor |
| `result` | no | A type descriptor for the value the handler returns on success |
| `failure` | no | Contract 2.1. A type descriptor for the value the handler fails with |

At dispatch, the runtime delivers the action name, its evaluated, typed parameters, and the dispatch identity (state and actions spec) to the host's action handlers as data. `onSuccess` and `onFailure` are part of the action encoding in the document model, not of the declaration.

Vocabulary actions are the global default set. The action names and parameter shapes a document may bind come only from consumer code; documents never declare actions. This makes the declarations a capability manifest: nothing reaches a handler that the consumer did not declare.

Each surface (a builder, per the runtime API spec) refines the global set into its **granted action set**:

- The builder may **allow** a subset of action names; when it does, binding any custom action outside that subset is a `SchemaViolation` with rule `action-capability` at the gate. Built-in `$` actions are contract, not capabilities, and are always available.
- The builder may **declare** actions for its surface, adding names absent from the vocabulary or overriding a vocabulary signature, in this same declaration format. This is how one action name carries different parameters on different surfaces.
- A builder that configures nothing grants the full vocabulary set with its global signatures.

Declarations type the payload; meaning is assigned per surface by the builder's handler. The evolution rule below ("a name never changes meaning") is about meaning across versions; per-surface interpretation across contexts is the handler's explicit job.

## Completion results

An action declared with a `result` type makes the `result` expression root available, with exactly that type, inside that action's `onSuccess` bindings. The handler supplies the value when it completes with success; the runtime validates it against the declared type before any follow-up runs. `result` is a `SchemaViolation` inside `onFailure` bindings and everywhere else.

`result` rebinds at each nesting: inside the `onSuccess` of a nested action, `result` is the nested action's result (or unavailable if it declares none). There is no fall-through to an outer action's result. An outer `result` may still flow inward as data, because a nested action's parameters are evaluated, and captured, while the outer binding is in scope.

## Failure payloads

Contract 2.1. An action declared with a `failure` type makes the `failure` expression root available, with exactly that type, inside that action's `onFailure` bindings, under the same rules as `result` in `onSuccess`: the handler supplies the value when it completes with failure, the runtime validates it against the declared type before any follow-up runs, and `failure` is a `SchemaViolation` inside `onSuccess` bindings and everywhere else. It rebinds at each nesting exactly as `result` does.

The two declarations are symmetric, missing value included: a failure completion with no value is a `null`, which satisfies an optional `failure` declaration and violates a non-optional one (state and actions spec, Completion). A consumer whose handlers may fail with an ordinary error, carrying nothing, declares `failure` optional, or maps every error to a value before completing; the gate cannot tell the two kinds of failure apart, so the declaration has to. An action declaring no `failure` keeps the 2.0 rule: a value on a failure completion is an invalid completion.

The typical declaration is an enum of reasons, so the document can branch on them with `$when` and enum comparison, or a record carrying a reason and a message.

## Function declarations

Contract 2.1. Each entry in `functions` declares one host function, callable from expressions by name (expression language spec, Host functions):

| Field | Required | Purpose |
|---|---|---|
| `arguments` | yes | An ordered list of type descriptors, one per argument, at least one |
| `returns` | yes | A type descriptor for the value the function produces |

```json
"functions": {
  "formatMoney": { "arguments": ["int", "string", "string"], "returns": "string" }
}
```

Rules, each an `InvalidVocabulary` at engine creation:

- The name follows the identifier grammar (rule `function-name`, `found` the name). Any identifier will do: built-in functions are called through the contract's `$` namespace (`$round`), so a vocabulary declaring `round` gets its own `$round(...)`, and no declaration can ever be shadowed by this spec's growth.
- `arguments` must list at least one type (rule `function-arguments`, `found` the name). A function of no arguments would be a constant, or would read something its arguments do not carry; both contradict the purity rule below.

A host function is **pure over its arguments**: for the same arguments it produces the same value, for as long as the engine lives. Everything it depends on arrives as an argument. A locale, a time zone, a unit preference, a currency: the host places them in context, the document passes them in, and a change is an ordinary context update that re-evaluates every call reading it. The runtime relies on this rule: it may evaluate a call whenever a dependency changes, more than once per update, and may cache a result by its arguments. A function that reads ambient state instead is not wrong at the gate; it is stale in the view, silently, which is why the rule is normative.

Like actions, the surface's builder may **declare** functions for its surface, adding names absent from the vocabulary or overriding a signature, in this same declaration format; there is no allowlist, since a function is a computation, not a capability. The engine's function handler (runtime API spec) resolves every declared function by name.

## Event payloads

An event declared with a payload type makes the `event` expression root available, with exactly that type, inside the `on` bindings for that event. An event declared with `null` has no payload, and referencing `event` in its bindings is a `SchemaViolation`. A renderer emission whose payload does not match the declared type is an invalid emission, dropped and reported per Foundations.

## Engine consumption

- A MilanoEngine is created with one vocabulary artifact and one registry.
- Engine creation validates both, and fails fast with a typed error on developer mistakes: `InvalidVocabulary` when the artifact violates this spec, `IncompleteRegistry` when a declared component type has no registered renderer. These errors arise before any document is processed: at engine creation, or, for the per-surface placeholder override with no placeholder renderer registered (runtime API spec), at build. They can never occur during rendering or later.
- The artifact's `milano` version follows the same rule as a document's `version` (Foundations, Versioning): an artifact targeting a contract version the engine does not implement, by major or by minor, is rejected at creation (`InvalidVocabulary`, rule `milano-version`, naming the supported ranges), never processed under mismatched rules. The declared version is a floor the artifact holds itself to, as for documents: an action declaring a `failure` type in an artifact declaring `milano` 2.0 or 1.x is rejected at creation (`InvalidVocabulary`, rule `contract-feature`, `expected` `2.1`, `found` `failure`), and a `functions` section in an artifact declaring `milano` below 2.1 likewise (`expected` `2.1`, `found` `functions`). Per-surface declarations made in code (runtime API spec) carry no version and always speak the engine's contract.
- A document's component type is *unknown* when it is not declared in the engine's vocabulary. Registry coverage of the vocabulary is total by construction, so unknown-at-gate and unrenderable are the same condition, handled by the unknown-type policy.

## Evolution

Within a vocabulary major version, changes are additive only:

- A release may add component types, properties, events, actions, action parameters, a `result` or a `failure` to an action that had none, functions, and may add members to an enum type. Adding a member is safe because the gate validates membership against the engine's held vocabulary: a document using the new member on an older engine fails the gate (declare `vocabulary.min` to say so), and a renderer never receives a member its own vocabulary version does not declare. Adding a `result` or `failure` is safe because no document could read the root before.
- A declared name is never removed, never changes type, and never changes meaning. Removing or renaming an enum member changes the type and requires a major bump; narrowing `string` to an enum, or an enum to fewer members, is likewise breaking. A semantic change ships under a new name; the old name keeps its old meaning until the next major. A property that changes unit, interpretation, or effect while keeping its name and type is a breaking change even though no validator can see it.
- Removing a declaration, changing a type (a `result`, a `failure`, a function's `arguments` or `returns` included), changing an event payload, marking a component `strict`, or revoking `children` acceptance requires a major bump. Optionality is part of the type, in both directions: making a required property optional is breaking too, because a renderer, or a binding generated from the declaration, reads a non-optional property as a promise that a value is present and would now receive `null`; making an optional property required breaks every document that omits it.

This rule governs consumer-owned vocabularies once they are depended on. Milano's own formats (this artifact format included) follow the same discipline: contract 2.0 is stable, and incompatible changes ship only under a new contract major.

This rule is what makes a document's minimum-version requirement sound: any vocabulary version at or above the minimum, within the same major, carries everything the document needs with unchanged meaning. `tools/vocabulary_diff.py` in this repository classifies the changes between two artifact versions and verifies that the version bump matches; producers run it in CI before publishing a vocabulary. What no tool can detect is semantic repurposing with unchanged shape; that is exactly what this section forbids.

## Tooling

The artifact is designed to be consumed by more than the engine: producers validate documents against it before shipping them, and `tools/generate_bindings.py` in this repository derives typed node wrappers, event emitters, action definitions, and one wrapper type per enum and record declaration site (results and failure payloads included) for Swift, Kotlin, and TypeScript from it. Tooling is not required for conformance; the artifact format is.

JSON Schema (2020-12) is the tooling bridge, not the artifact language:

- An official meta-schema, `schemas/vocabulary.schema.json` in this repository, validates vocabulary artifacts. Editors and CI get standard validation for free. Like the document schema, it is open on the objects the contract may grow (declarations and type descriptors), per the tolerance rule.
- A deterministic mapping from a vocabulary to a generated JSON Schema for its documents ships as `tools/generate_document_schema.py` in this repository, so producers can validate documents with standard validators, and get editor autocomplete for component types, properties, events, and enum members, before shipping them. The gate remains the source of truth: it checks what JSON Schema cannot (expression typing, event bindings, action semantics).

The runtimes never parse JSON Schema; they parse this artifact format. Milano semantics that JSON Schema has no words for (events, actions, children acceptance, strict mode) stay first-class here.
