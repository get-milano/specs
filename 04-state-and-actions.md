---
title: "State and actions"
nav_order: 5
---

# Milano State and Actions

**Status:** Stable v1.0.0 · 2026-08-16

Defines the runtime semantics of state, events, and action dispatch: the exact order in which things happen, on every platform identically. Encodings live in the document model spec; this spec fixes behavior.

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

- **`$set`**: targets one declared top-level state key (never a field inside a record: the whole key is assigned). It evaluates its value expression at execution time and assigns it. The mutation is visible immediately: expressions evaluated by subsequent actions in the same dispatch see the new value, and dependent property re-evaluation completes before the next action executes. A property is dependent when its expression reads the key, directly or through a record field; a property that reads no changed key is not re-evaluated, so its arithmetic reports are not repeated, and a `$set` that leaves the value equal to what it was changes nothing and re-evaluates nothing. The assigned value must be within the value size limit (document model spec): a `$set` whose value exceeds it assigns nothing, is reported as a rejected mutation naming the key, the limit, and the size found, and ends the action list, so the remaining actions of that dispatch do not run; mutations the list already applied stay, since each was visible the moment it applied.
- **`$sequence`**: executes its actions in order. Nesting is allowed. A bare action array in `on` is identical to `$sequence`.
- **`$when`**: evaluates its condition at execution time, then executes the matching branch's actions in order.
- **Custom actions**: parameters are evaluated at execution time, including any `event` references, and the resulting values are captured. The action (name plus captured, typed parameters) is delivered to the host's action handler asynchronously, as immutable data; the invocation thread is unspecified. Dispatch does not wait: the sequence continues immediately with the next action. Anything that must happen after the handler finishes belongs in `onSuccess` or `onFailure`.
- **Handlers are the last capability check.** The gate guarantees an action was granted and its parameters match the declaration; it cannot judge the values. Handlers treat every document as untrusted: validate parameter values before acting (for example, scheme and host allowlists before opening a URL), switch on known action names, and never route action names generically into deep links, reflection, or evaluation machinery.

## Completion

- A custom action's handler completes exactly once, with success or failure. A second completion is ignored and reported.
- On completion, the matching `onSuccess` or `onFailure` actions execute on the main thread, under the same rules as any action list. `event` references inside them evaluate against the payload captured at dispatch time.
- Completions are processed in arrival order and interleave with new events in FIFO order; they never interrupt an action list mid-execution.
- If the MilanoView has been torn down when a completion arrives, its follow-up actions are dropped and the occurrence is reported. On platforms with deterministic lifetimes, deallocation of the view counts as teardown.
- An emission arriving after teardown is silently ignored: unlike a late completion, it represents no pending work, so there is nothing to report.
- Teardown observed while an action list is executing does not interrupt it. The list runs to completion under the rules above (state mutations apply, custom actions dispatch), and only work arriving afterwards is refused. Action lists are atomic, and teardown is one more update that never lands mid-list.
- A success completion for an action declaring a `result` type carries the handler's returned value. The runtime validates it against the declaration; the validated value binds the `result` expression root inside that action's `onSuccess` list, rebinding at each nesting per the vocabulary schema spec.
- An **invalid completion** consumes the completion without running either branch, and the occurrence is reported. Three shapes are invalid: a success value that does not match the declared `result` type (a missing value counts as `null`, so it satisfies an optional declaration and violates a non-optional one), a success value for an action declaring no `result`, and any value on a failure completion.

## Context updates

- The host may post context updates from any thread; they are validated and applied on the main thread, serialized with dispatch: an update never lands mid-action-list.
- An update is atomic: all keys validate against the declarations and fit the value size limit (document model spec), or the whole update is rejected, reported, and the previous values stay.
- After application, dependent expressions re-evaluate before anything else runs: those reading a key whose value changed, under the same rule as `$set`. An update that supplies the values already held changes nothing.

## User interaction records

When the engine carries a user-interaction observer (runtime API spec), dispatch contributes records at fixed points, on the dispatcher: an `event` record after an emission's payload validates and before the binding lookup, so declared-but-unbound emissions reach analytics while `droppedEvent` keeps its defect meaning; an `actionDispatched` record when a custom action's parameters have been captured, anchored to the node whose binding dispatched it; and a `completionSucceeded` or `completionFailed` record when a completion settles validly. Defective traffic (invalid emissions, invalid or duplicate completions) produces occurrences, never interaction records.

## Reported occurrences

This spec's contributions to the engine observer, all tagged with the originating view: dropped events (no binding), invalid emissions, invalid completions, duplicate completions, completions after teardown, rejected context updates, rejected mutations (a `$set` past the value size limit), and the arithmetic reports from the expression spec (division by zero, saturation).
