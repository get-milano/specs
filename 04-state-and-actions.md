---
title: "State and actions"
nav_order: 5
---

# Milano State and Actions

**Status:** Beta v0.1.0 · 2026-08-15

Defines the runtime semantics of state, events, and action dispatch: the exact order in which things happen, on both platforms identically. Encodings live in the document model spec; this spec fixes behavior.

## The state store

- One store per MilanoView, holding the document-declared state values, typed per their declarations.
- Initial values come from the state data provider, validated at the gate.
- `$set` is the only writer. Expressions are the only readers. Renderers and hosts never touch the store directly.
- All access happens on the main thread.

## Event dispatch

1. A renderer emits a declared event, with a payload matching the declared type. (Undeclared events and mis-typed payloads are dropped and reported before reaching dispatch, per Foundations.)
2. Events are processed in FIFO order on the main thread. One event's bound actions run to completion before the next event's begin.
3. The event's payload is bound to the `event` root for the duration of that event's dispatch.
4. An event with no bound actions is dropped and reported.

## Action execution

Actions bound to an event execute synchronously, in document order, on the main thread:

- **`$set`**: targets one declared top-level state key (never a field inside a record: the whole key is assigned). It evaluates its value expression at execution time and assigns it. The mutation is visible immediately: expressions evaluated by subsequent actions in the same dispatch see the new value, and dependent property re-evaluation completes before the next action executes.
- **`$sequence`**: executes its actions in order. Nesting is allowed. A bare action array in `on` is identical to `$sequence`.
- **`$when`**: evaluates its condition at execution time, then executes the matching branch's actions in order.
- **Custom actions**: parameters are evaluated at execution time, including any `event` references, and the resulting values are captured. The action (name plus captured, typed parameters) is delivered to the host's action handler on the main thread. Dispatch does not wait: the sequence continues immediately with the next action. Anything that must happen after the handler finishes belongs in `onSuccess` or `onFailure`.

## Completion

- A custom action's handler completes exactly once, with success or failure. A second completion is ignored and reported.
- On completion, the matching `onSuccess` or `onFailure` actions execute on the main thread, under the same rules as any action list. `event` references inside them evaluate against the payload captured at dispatch time.
- Completions are processed in arrival order and interleave with new events in FIFO order; they never interrupt an action list mid-execution.
- If the MilanoView no longer exists when a completion arrives, its follow-up actions are dropped and the occurrence is reported.
- An emission arriving after teardown is silently ignored: unlike a late completion, it represents no pending work, so there is nothing to report.
- Whether a completion carries data is out of v0.1 scope: success and failure are signals.

## Context updates

- The host may post context updates from any thread; they are validated and applied on the main thread, serialized with dispatch: an update never lands mid-action-list.
- An update is atomic: all keys validate against the declarations or the whole update is rejected, reported, and the previous values stay.
- After application, dependent expressions re-evaluate before anything else runs.

## Runtime limits

A state mutation or context update whose re-evaluation would exceed the engine's runtime limits is rejected atomically per Foundations: the store keeps its previous values, the presentation stays, the occurrence is reported.

## Reported occurrences

This spec's contributions to the engine observer, all tagged with the originating view: dropped events (no binding), invalid emissions, duplicate completions, completions after teardown, rejected context updates, over-limit rejections, and the arithmetic reports from the expression spec (division by zero, saturation).
