---
title: "Conformance suite"
nav_order: 6
---

# Milano Conformance Suite

**Status:** Stable v1.0.0 · 2026-08-16

The conformance suite is the operational definition of mechanics parity: a language-neutral set of test vectors that both runtimes must pass, maintained in this repository alongside the specs. A runtime that passes the suite conforms; there is no other definition.

## Suite layout

Vectors are organized into suites: one directory per vocabulary. A suite directory contains `vocabulary.json` (the artifact) and any number of vector files. The harness creates one engine per suite from its vocabulary and runs every vector in the directory against it.

Two suites ship today: `examples`, the handwritten scenarios, and `generated-numeric`, produced by `tools/generate_numeric_vectors.py`: a seeded, deterministic sweep of numeric and formatting boundary compositions whose expectations come from the reference checker as oracle. Rerunning the generator reproduces the suite byte for byte; regenerate only when the numeric spec changes, and review the diff like any other suite change.

Nothing inside a vector or a document references the vocabulary. The binding is positional, mirroring the runtime: a document never names its vocabulary; it is simply built by an engine that holds one.

## Vectors

A vector is one JSON file describing a complete scenario and its expected outcome:

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | Stable identifier, unique across the suite |
| `description` | no | Human-readable summary of the scenario |
| `documentText` | see below | Raw string alternative to `document`, for vectors exercising parse failures; exactly one of the two is present |
| `document` | yes, unless `documentText` | The document under test |
| `config` | no | Surface settings when they matter: unknown-type policy (absent means the contract default, *fail*) and the builder's action grants (`actions.allow`, an allowlist of custom action names, and `actions.declare`, per-surface action declarations and overrides) |
| `context` | no | Context values supplied at build |
| `state` | no | Values returned by the state data provider |
| `steps` | no | Ordered interactions after build. Four kinds: `event` (a renderer emission: node, name, optional payload), `contextUpdate` (values pushed through the context source), `complete` (an action completion: the dispatch index, `success` or `failure`, and an optional `payload` carrying the handler's returned value), and `teardown` (the view ceases to exist) |
| `expect` | yes | The expected outcome; `interactions`, the expected user-interaction records in order (kind, node, name, value), compared by engines carrying a collecting user-interaction observer |

An official schema, `schemas/vector.schema.json` in this repository, formalizes the envelope; CI validates every vector against it. Two conventions follow from it: vector names are lowercase kebab-case, and a structurally invalid document is always carried as `documentText`, so every embedded `document` object satisfies the document schema.

`expect` takes one of two forms:

- **Build failure**: the typed error, with the detail fields the error must carry (node reference, expected, found).
- **Build success**: any combination of the resolved tree (types, resolved property values, post-policy structure), the state store contents after the steps, the custom actions dispatched (names and captured parameters, in order), and the occurrences reported to the observer (kinds and node references, in order).

## Coverage

The suite must include vectors for every normative statement in specs 01 through 04. At minimum, per area:

- **Gate**: each typed error, each detail shape, the fixed validation order (documents constructed to fail two rules at once pin which error wins), each unknown-type policy. Tree depth and expression length are pinned at their exact boundaries by vectors; node count and document size, whose boundary vectors would be megabyte-scale, are pinned by engine unit tests.
- **Types and data**: every descriptor form, optionality and null, context and provider values that match and mismatch, atomic rejection of partial context updates.
- **Expressions**: every operator at its type boundaries, promotion cases including precision edges, integer wrapping, division by zero, saturation, every function, `??` and `null` comparisons, short-circuit behavior.
- **Actions and state**: `$set` visibility ordering, nested `$sequence`, `$when` branches, parameter capture including `event`, no-await sequencing, completion interleaving, duplicate and post-teardown completions, FIFO across events.
- **Observability**: every reported occurrence kind, with view identity.

## Harness

Each runtime ships a conformance driver that loads vectors, executes them against the real engine and gate (renderers stubbed mechanically), and compares outcomes structurally. Drivers are runtime-specific; vectors never are. A vector that cannot be expressed through a driver's public API indicates a spec or API defect, not a vector defect.

This repository also ships a reference checker, `tools/reference_check.py`: a minimal implementation of the gate and the expression language derived from specs 01 through 03. CI runs every step-free vector through it, so a vector whose expectation contradicts the spec's semantics fails at merge instead of surfacing later in an engine's suite. Vectors with `steps` are statically linted instead of executed: the build must succeed, action lists must be well-formed and type-correct (with the `event` and `result` roots bound to their declared types), each step must be structurally valid and reference existing nodes, and a deliberately invalid or unbound emission must be matched by the occurrence the vector expects. The checker is a linter, not a third runtime: the prose remains normative, step *execution* is covered only by the engines' drivers, and a disagreement between the checker and a vector signals a defect in one of them, resolved by a human editing whichever is wrong.

## Process

- Vectors are added in the same change as the normative text they pin; a spec change without its vectors is incomplete.
- Both runtimes must pass the full suite before any spec moves from Review to Stable.
- A behavioral divergence discovered between runtimes always produces a new vector reproducing it, before the fix.
