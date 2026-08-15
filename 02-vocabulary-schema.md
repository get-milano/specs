---
title: "Vocabulary schema"
nav_order: 3
---

# Milano Vocabulary Schema

**Status:** Beta v0.1.0 · 2026-08-15

Defines the machine-readable artifact in which a consumer declares their vocabulary: component types, events, and custom actions. The engine consumes this artifact; the gate validates every document against it. It is the contract between document producers and the client, kept in sync by tooling, not discipline.

## Artifact structure

A vocabulary is a single JSON object, encoded in UTF-8, with reserved top-level fields. The artifact format is governed by the Milano contract and follows the same versioning and tolerance rules as documents.

| Field | Required | Purpose |
|---|---|---|
| `milano` | yes | The contract version the artifact targets (major.minor.patch) |
| `name` | yes | The vocabulary's name |
| `version` | yes | The vocabulary's own version, consumer-owned; Milano never interprets it, but surfaces it in observability reports |
| `components` | yes | Map of component type name to component declaration |
| `actions` | no | Map of custom action name to action declaration |

## Naming

One identifier grammar applies to component type names, property names, event names, action names, and the state and context keys of documents: a letter followed by letters, digits, or underscores. Case-sensitive. Names must not begin with `$`, which is reserved for the contract.

## Component declarations

Each entry in `components` declares one component type:

| Field | Required | Purpose |
|---|---|---|
| `properties` | no | Map of property name to a type descriptor (per the document model's type system) |
| `events` | no | Map of event name to a payload type descriptor, or `null` for payload-less events |
| `children` | no | Boolean, default `false`: whether nodes of this type accept `children` |
| `strict` | no | Boolean, default `false`: when `true`, undeclared properties on nodes of this type are a `SchemaViolation` instead of ignored-and-reported |

Optional properties (types marked `?`) may be omitted in documents; the renderer receives `null`. There are no default values in v0.1: what a renderer does with `null` is the consumer's decision, made in the renderer.

## Action declarations

Each entry in `actions` declares one custom action type:

| Field | Required | Purpose |
|---|---|---|
| `parameters` | no | Map of parameter name to a type descriptor |

At dispatch, the runtime delivers the action name and its evaluated, typed parameters to the host's action handlers as data. `onSuccess` and `onFailure` are part of the action encoding in the document model, not of the declaration.

Vocabulary actions are the global set, shared by every document the engine builds. A document may additionally declare its own local actions, per the document model spec, in this same declaration format; a local name must not collide with a global one. Components have no local equivalent: they require registered renderers, which are code.

## Event payloads

An event declared with a payload type makes the `event` expression root available, with exactly that type, inside the `on` bindings for that event. An event declared with `null` has no payload, and referencing `event` in its bindings is a `SchemaViolation`. A renderer emission whose payload does not match the declared type is an invalid emission, dropped and reported per Foundations.

## Engine consumption

- A MilanoEngine is created with one vocabulary artifact and one registry.
- Engine creation validates both, and fails fast with a typed error on developer mistakes: `InvalidVocabulary` when the artifact violates this spec, `IncompleteRegistry` when a declared component type has no registered renderer. These errors arise at engine creation only; they can never occur at the gate or later.
- A document's component type is *unknown* when it is not declared in the engine's vocabulary. Registry coverage of the vocabulary is total by construction, so unknown-at-gate and unrenderable are the same condition, handled by the unknown-type policy.

## Tooling

The artifact is designed to be consumed by more than the engine: producers validate documents against it before shipping them, and code generators can derive typed renderer interfaces and typed action definitions for both platforms from it. Tooling is not required for conformance; the artifact format is.

JSON Schema (2020-12) is the tooling bridge, not the artifact language:

- An official meta-schema, `schemas/vocabulary.schema.json` in this repository, validates vocabulary artifacts. Editors and CI get standard validation for free.
- A deterministic mapping from a vocabulary to a generated JSON Schema for its documents is planned, so producers can validate documents with standard validators before shipping them. The gate remains the source of truth: it checks what JSON Schema cannot (expression typing, event bindings, action semantics).

The runtimes never parse JSON Schema; they parse this artifact format. Milano semantics that JSON Schema has no words for (events, actions, children acceptance, strict mode) stay first-class here.
