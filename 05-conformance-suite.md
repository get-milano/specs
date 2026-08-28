---
title: "Conformance suite"
nav_order: 6
---

# Milano Conformance Suite

**Status:** Stable · contract 2.0 · repository release 2.0.0 · 2026-08-29

The conformance suite is the operational definition of mechanics parity: a language-neutral set of test vectors that every runtime must pass, maintained in this repository alongside the specs. A runtime that passes the suite conforms; there is no other definition.

## Suite layout

Vectors are organized into suites: one directory per vocabulary. A suite directory contains `vocabulary.json` (the artifact) and any number of vector files. The harness creates one engine per suite from its vocabulary and runs every vector in the directory against it.

Four suites ship today: `examples`, the handwritten scenarios; `generated-numeric`, produced by `tools/generate_numeric_vectors.py`, a seeded, deterministic sweep of numeric and formatting boundary compositions whose expectations come from the reference checker as oracle; and `generated-typing`, produced by `tools/generate_typing_vectors.py`, an exhaustive enumeration of the expression spec's typing rules (declared-position acceptance, `??`, `if`, `==`, arithmetic, function signatures, field access) over a small grammar, with every expression and target pair run through the reference gate to decide whether it is accepted or rejected; and `generated-order`, produced by `tools/generate_order_vectors.py`, every pair of gate violations composed into one document, with the reference gate deciding which error wins, so the validation order in the document model spec, and the rule that the first defect in document order wins, are pinned pair by pair. Rerunning a generator reproduces its suite byte for byte; regenerate only when the corresponding spec changes, and review the diff like any other suite change.

Nothing inside a vector or a document references the vocabulary. The binding is positional, mirroring the runtime: a document never names its vocabulary; it is simply built by an engine that holds one.

## Vectors

A vector is one JSON file describing a complete scenario and its expected outcome:

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | Stable identifier, unique across the suite |
| `description` | no | Human-readable summary of the scenario |
| `documentText` | see below | Raw string alternative to `document`: for text that does not parse, for a document the document schema would reject (so every embedded `document` object validates), and for a valid document whose exact bytes matter (the document size limit); exactly one of the two is present |
| `document` | yes, unless `documentText` | The document under test |
| `config` | no | Surface settings when they matter: unknown-type policy (absent means the contract default, *fail*), the builder's action grants (`actions.allow`, an allowlist of custom action names, and `actions.declare`, per-surface action declarations and overrides), `limits`, engine limit overrides by name (`maxTreeDepth`, `maxNodeCount`, `maxDocumentBytes`, `maxExpressionLength`, `maxValueSize`), so a limit is pinned at a small value rather than with a fixture the size of the default, and `stateDataProvider` and `actionHandler`, booleans that build the surface without the corresponding input when `false` (absent means present) |
| `context` | no | Context values supplied at build |
| `state` | no | Values returned by the state data provider; absent means the provider returns nothing, not that there is no provider (that is `config.stateDataProvider: false`) |
| `steps` | no | Ordered interactions after build. Four kinds: `event` (a renderer emission: node, name, optional payload), `contextUpdate` (values pushed through the context source), `complete` (an action completion: the dispatch index, `success` or `failure`, and an optional `payload` carrying the handler's returned value), and `teardown` (the view ceases to exist) |
| `expect` | yes | The expected outcome; `interactions`, the expected user-interaction records in order (kind, node, name, value), compared by engines carrying a collecting user-interaction observer |

An official schema, `schemas/vector.schema.json` in this repository, formalizes the envelope; CI validates every vector against it. Two conventions follow from it: vector names are lowercase kebab-case, and a structurally invalid document is always carried as `documentText`, so every embedded `document` object satisfies the document schema.

`expect` takes one of two forms:

- **Build failure**: the typed error, with the detail fields the error must carry (node reference, expected, found).
- **Build success**: any combination of the resolved tree (types, resolved property values, post-policy structure), the state store contents after the steps, the custom actions dispatched (names and captured parameters, in order), and the occurrences reported to the observer (kinds, node references, and, when the vector states them, the `name`, `expected`, and `found` detail, in order).

## Coverage

The suite must include vectors for every normative statement in specs 01 through 04. At minimum, per area:

- **Gate**: each typed error, each detail shape, the fixed validation order (documents constructed to fail two rules at once pin which error wins), each unknown-type policy. Every limit is pinned by a vector at a value set through `config.limits`, and the defaults by engine unit tests where a boundary fixture at the default would be megabyte-scale (node count, document size).
- **Types and data**: every descriptor form, optionality and null, context and provider values that match and mismatch, atomic rejection of partial context updates.
- **Expressions**: every operator at its type boundaries, promotion cases including precision edges, integer wrapping, division by zero, saturation, every function, `??` and `null` comparisons, short-circuit behavior.
- **Actions and state**: `$set` visibility ordering, nested `$sequence`, `$when` branches, parameter capture including `event`, no-await sequencing, completion interleaving, duplicate and post-teardown completions, FIFO across events.
- **Constructs**: every `repeat` rule, empty, nested, and context-driven instantiation, instance emissions and vanished indices, and the node count measured on the materialized tree at build and under `$set`.
- **Observability**: every reported occurrence kind.

## Harness

Each runtime ships a conformance driver that loads vectors, executes them against the real engine and gate (renderers stubbed mechanically), and compares outcomes structurally. Drivers are runtime-specific; vectors never are. A vector that cannot be expressed through a driver's public API indicates a spec or API defect, not a vector defect.

Some normative statements are about the surface's lifetime rather than its inputs (teardown observed while an action list runs; deallocation counting as teardown where lifetimes are deterministic), or about a default whose boundary fixture would be megabyte-scale. No vector expresses them, so they are **engine-pinned**: `conformance/engine-pinned.json` lists each such statement with a stable id, the spec and section it comes from, and the runtimes it applies to, and every applicable runtime carries a test that names the id. The registry is validated by `tools/validate_suite.py`, and the SDK's consistency check asserts every engine references every id, so a statement pinned in one engine and forgotten in another is a failing build rather than a quiet gap. A statement enters the registry only when no vector can express it; a `config` addition that makes it expressible retires the entry.

This repository also ships a reference checker, `tools/reference_check.py`: a minimal implementation of the gate and the expression language derived from specs 01 through 03. CI runs every step-free vector through it, so a vector whose expectation contradicts the spec's semantics fails at merge instead of surfacing later in an engine's suite. Vectors with `steps` are statically linted instead of executed: the build must succeed, action lists must be well-formed and type-correct (with the `event` and `result` roots bound to their declared types), each step must be structurally valid and reference existing nodes, and a deliberately invalid or unbound emission must be matched by the occurrence the vector expects. The checker is a linter, not a third runtime: the prose remains normative, step *execution* is covered only by the engines' drivers, and a disagreement between the checker and a vector signals a defect in one of them, resolved by a human editing whichever is wrong.

## Process

- Vectors, or an engine-pinned registry entry when no vector can express the statement, are added in the same change as the normative text they pin; a spec change without them is incomplete.
- Every runtime must pass the full suite before any spec moves from Review to Stable.
- A behavioral divergence discovered between runtimes always produces a new vector reproducing it, before the fix.
