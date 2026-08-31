---
title: "State and actions"
nav_order: 5
---

# Milano State and Actions

**Status:** Stable · contract 2.1 · repository release 2.1.0 · 2026-08-31

Defines the runtime semantics of state, events, lifecycle signals, watches, action dispatch, and document replacement: the exact order in which things happen, on every platform identically. Encodings live in the document model spec; this spec fixes behavior.

## The state store

- One store per MilanoView, holding the document-declared state values, typed per their declarations.
- Initial values come from the state data provider, validated at the gate.
- `$set` and the array actions (`$append`, `$remove`, `$update`; contract 2.1) are the only writers. Expressions are the only readers. Renderers and hosts never touch the store directly.
- All access happens on the main thread.

## Event dispatch

1. A renderer emits a declared event, with a payload matching the declared type. (Undeclared events and mis-typed payloads are dropped and reported before reaching dispatch, per Foundations.)
2. Events are processed in FIFO order on the main thread. One event's bound actions run to completion before the next event's begin.
3. The event's payload is bound to the `event` root for the duration of that event's dispatch.
4. An event with no bound actions is dropped and reported.
5. An emission from a `$repeat` instance names the instance (`card[2]`, or `card[abc]` under a `key`). Dispatch binds the construct's roots to the element of `items`, as evaluated at dispatch time, that the instance identifies: the element at that index, or the element whose key renders to that identity, with `<as>_index` its current position; outermost repeat first. An identity that no longer exists is an invalid emission (`expected` `repeat element`, `found` `index N` or `key K`), dropped and reported. Follow-up actions keep the binding captured at dispatch, as they keep `event`.

## Action execution

Actions bound to an event execute synchronously, in document order, on the main thread:

- **`$set`**: targets one declared top-level state key (never a field inside a record: the whole key is assigned). It evaluates its value expression at execution time and assigns it. The mutation is visible immediately: expressions evaluated by subsequent actions in the same dispatch see the new value, and dependent property re-evaluation completes before the next action executes. A property is dependent when its expression reads the key, directly or through a record field; a property that reads no changed key is not re-evaluated, so its arithmetic reports are not repeated, and a `$set` that leaves the value equal to what it was changes nothing and re-evaluates nothing. The assigned value must be within the value size limit, the tree it re-materializes within the node count limit, and every keyed `$repeat` it re-materializes must keep its keys distinct (document model spec): a `$set` that would violate any of the three assigns nothing, is reported as a rejected mutation naming the key, the requirement as `expected` (`maxValueSize`, `maxNodeCount`, or `distinct key`), and the size, count, or repeated key found, and ends the action list, so the remaining actions of that dispatch do not run; mutations the list already applied stay, since each was visible the moment it applied.
- **`$append`, `$remove`, `$update`** (contract 2.1): each targets one declared array-typed state key and applies exactly the rules of `$set` to the array it produces: visibility, dependent re-evaluation, the no-change rule, the three requirements (value size of the whole array, node count, distinct keys) with the same rejected-mutation report, and the end of the action list on rejection. What each produces:
  - `$append` evaluates `value` and produces the array with it as a new last element. It always changes the array.
  - `$remove` evaluates `at` and produces the array without the element at that index. An index below zero or at or past the array's length is a rejected mutation with `expected` `index in range` and `found` the index in decimal; nothing is assigned and the list ends, like any rejection.
  - `$update` evaluates `at`, then `value`, and produces the array whose element at `at` has the named field replaced by the value; every other field and element is unchanged. The index rule is `$remove`'s. An update that leaves the field equal to what it was changes nothing and re-evaluates nothing, like a `$set`.
  Inside a `$repeat` template, `<as>_index` is the element's position in the array at dispatch time (Event dispatch, above), so `{"action": "$remove", "key": "items", "at": {"$expr": "item_index"}}` removes the element the instance was bound to, keyed or not.
- **`$sequence`**: executes its actions in order. Nesting is allowed. A bare action array in `on` is identical to `$sequence`.
- **`$when`**: evaluates its condition at execution time, then executes the matching branch's actions in order.
- **Custom actions**: parameters are evaluated at execution time, including any `event` references, and the resulting values are captured. The action (name plus captured, typed parameters, plus its dispatch identity) is delivered to the host's action handler asynchronously, as immutable data; the invocation thread is unspecified. Dispatch does not wait: the sequence continues immediately with the next action. Anything that must happen after the handler finishes belongs in `onSuccess` or `onFailure`.
- **Dispatch identity.** Every custom action delivered to a handler carries two identifiers. `dispatch` is the dispatch's position among the view's custom action dispatches, an `int` counting from zero in delivery order, so the third custom action a view ever dispatches is `dispatch` 2 whatever event, lifecycle signal, or follow-up produced it; it is deterministic and the conformance suite pins it. `dispatchId` is a string unique among every dispatch of every view in the process, whatever the views' labels; its format is opaque and no two dispatches ever share one. Hosts use `dispatchId` as an idempotency key toward whatever the handler calls (a second delivery of the same key is the same dispatch, a fresh key is a new one) and both to correlate a dispatch with its completion in analytics, where the same numbers travel (User interaction records, below).
- **Handlers are the last capability check.** The gate guarantees an action was granted and its parameters match the declaration; it cannot judge the values. Handlers treat every document as untrusted: validate parameter values before acting (for example, scheme and host allowlists before opening a URL), switch on known action names, and never route action names generically into deep links, reflection, or evaluation machinery.

## Completion

- A custom action's handler completes exactly once, with success or failure. A second completion is ignored and reported.
- On completion, the matching `onSuccess` or `onFailure` actions execute on the main thread, under the same rules as any action list. `event` references inside them evaluate against the payload captured at dispatch time.
- Completions are processed in arrival order and interleave with new events in FIFO order; they never interrupt an action list mid-execution.
- If the MilanoView has been torn down when a completion arrives, its follow-up actions are dropped and the occurrence is reported. On platforms with deterministic lifetimes, deallocation of the view counts as teardown.
- If the view's document has been replaced since the dispatch (Document replacement, below), the completion belongs to a document that no longer exists: its follow-ups are dropped and `completionAfterReplace` is reported, named after the action. The dispatch still counts as completed, so a second completion is a duplicate as usual.
- An emission arriving after teardown is silently ignored: unlike a late completion, it represents no pending work, so there is nothing to report.
- Teardown observed while an action list is executing does not interrupt it. The list runs to completion under the rules above (state mutations apply, custom actions dispatch), and only work arriving afterwards is refused. Action lists are atomic, and teardown is one more update that never lands mid-list.
- A success completion for an action declaring a `result` type carries the handler's returned value. The runtime validates it against the declaration; the validated value binds the `result` expression root inside that action's `onSuccess` list, rebinding at each nesting per the vocabulary schema spec.
- A failure completion for an action declaring a `failure` type (contract 2.1) carries the value the handler failed with, under exactly the same rules: validated against the declaration, bound to the `failure` root inside that action's `onFailure` list, rebinding at each nesting.
- An **invalid completion** consumes the completion without running either branch, and the occurrence is reported. Four shapes are invalid: a success value that does not match the declared `result` type (a missing value counts as `null`, so it satisfies an optional declaration and violates a non-optional one), a success value for an action declaring no `result`, a failure value that does not match the declared `failure` type (a missing value counting as `null` the same way), and any value on a failure completion for an action declaring no `failure`.

## Context updates

- The host may post context updates from any thread; they are validated and applied on the main thread, serialized with dispatch: an update never lands mid-action-list.
- An update is atomic: all keys validate against the declarations and fit the value size limit, the tree it re-materializes fits the node count limit, and every keyed `$repeat` it re-materializes keeps its keys distinct (document model spec), or the whole update is rejected, reported with the requirement as `expected` (the limit's name, or `distinct key`) and the size, count, or repeated key as `found`, and the previous values stay. Keys are checked in lexicographic order, so the rejection reported is the first failing key in that order.
- After application, dependent expressions re-evaluate before anything else runs: those reading a key whose value changed, under the same rule as `$set`. An update that supplies the values already held changes nothing.

## Watch bindings

Contract 2.1. A `watch` list (document model spec, Watch bindings) runs when a mutation changes the value of its key: a `$set`, `$append`, `$remove`, or `$update` that is accepted and leaves the key's value different from before (compared by value, the same test as the no-change rule). A mutation the store accepts unchanged, a rejected mutation, the initial values at build, a context update, and a replacement (below) trigger no watch.

- The watch list runs **as part of the mutation**: after the new value is assigned and its dependent properties re-evaluate, and before the next action of the list that applied the mutation. Actions after it in that list see whatever the watch list assigned.
- It runs under the rules of a lifecycle list: synchronously, on the main thread, with no `event` root and no `$repeat` binding in scope; a custom action it dispatches is anchored to no node and numbered like any dispatch; its follow-ups run under the usual completion rules.
- **A watch never triggers a watch.** Mutations applied by actions in a watch list, and by the follow-ups of custom actions dispatched from it, do not run watch lists, whatever key they change. A watch is a reaction to the document's own event-driven mutations, not a dataflow graph: there is no cascade, no ordering problem, and no loop, by rule rather than by limit.
- A rejected mutation inside a watch list ends the watch list only; the list that triggered the watch continues with its next action. Mutations the watch list already applied stay.
- One mutation runs one watch list at most, once; a list that mutates the same key twice runs the watch twice, each time with the value then current.

## Document replacement

Contract 2.1. A host may replace the document a view is bound to (runtime API spec, MilanoView). The replacement is a build: the new document passes the gate whole, under the surface's configuration as it stands (the engine, the builder's grants and declarations, the unknown-type policy, the label, the action handler, the dispatcher, the context source), and either the view adopts it or nothing changes.

- **Context.** The values currently held are validated against the new document's context declarations exactly as supplied values are at build; a declaration the held values do not satisfy fails the replacement (`context-declaration`).
- **State.** A key the new document declares with exactly the type the old document declared it (optionality included) **carries over** with its current value. Every other declared key (new, or declared with a different type) is supplied by the state data provider, invoked once with the declarations of exactly those keys and validated as at build; a new document whose keys all carry over does not invoke the provider. A document declaring state that needs the provider when the surface configured none is the `state-declaration` violation, as at build. A provider failure propagates to the caller unchanged and the view is untouched.
- **Atomicity.** A replacement that fails, at the gate or in the provider, leaves the view exactly as it was: same document, same tree, same state and context, still serviceable. A replacement that succeeds swaps document, tree, state, and bindings in one step on the dispatcher, serialized with dispatch like a context update: it never lands mid-action-list, and the host is notified once, as after any re-resolution.
- **What persists.** The view's identity and label, its instance token and the `dispatch` numbering (the next dispatch continues the count), its appeared state (no lifecycle signal is synthesized: a replaced document's `appear` list runs on the next accepted `appear`, not on replacement), and its context subscription. Instance references are recomputed from the new document; an emission naming a node the new document lacks is an invalid emission like any other.
- **What does not.** Pending dispatches of the old document: their completions are dropped and reported as `completionAfterReplace` (Completion, above). Old watch and lifecycle bindings: the new document's apply from the swap onward, and the swap itself triggers no watch.
- Occurrences the gate detects while validating the replacement (skipped or placeholder nodes, undeclared properties) are reported only when the replacement succeeds, as at build. A `viewReplaced` interaction record is contributed on success, carrying the new document's `metadata` as `viewBuilt` does.
- A replacement requested after teardown is ignored silently, like a signal: the view no longer exists.

## Lifecycle signals

Contract 2.1. The host delivers two signals to a view over its lifetime, through the view's own API (runtime API spec): `appear` and `disappear`. The hosting container delivers them from the toolkit's own notion of presentation; a host managing a view itself delivers them explicitly. Milano never infers either.

- A view starts not appeared. An `appear` signal is accepted only while the view is not appeared, a `disappear` only while it is; a redundant signal (a second `appear` before any `disappear`, a `disappear` before any `appear`) is ignored silently, since it carries no work and is the binding's confusion, not the document's or the host's.
- An accepted signal is a dispatch: it queues on the dispatcher in FIFO order with events and completions, and runs the action list the document binds to it in its top-level `on` section, if any, under the rules above, with no `event` root and no `$repeat` binding in scope. A signal with no bound actions is accepted (the appeared state still flips) and reported to nobody: unlike an unbound event it is not a defect, since most documents bind nothing.
- Signals arriving after teardown are ignored silently, like emissions. Teardown does not synthesize a `disappear`: a document that needs to act on the view leaving the screen binds `disappear`, and the host delivers it before tearing down when that is what happened.
- The `appear` list may run more than once per view, once per acceptance: a screen the user leaves and returns to appears again.

## User interaction records

When the engine carries a user-interaction observer (runtime API spec), dispatch contributes records at fixed points, on the dispatcher: an `event` record after an emission's payload validates and before the binding lookup, so declared-but-unbound emissions reach analytics while `droppedEvent` keeps its defect meaning; a `viewAppeared` or `viewDisappeared` record when a lifecycle signal is accepted, before its bound actions run; a `viewReplaced` record when a replacement succeeds, with the new document's `metadata` as the value; an `actionDispatched` record when a custom action's parameters have been captured, anchored to the node whose binding dispatched it (none for a dispatch from a lifecycle or watch binding) and carrying the dispatch's `dispatch` number; and a `completionSucceeded` or `completionFailed` record when a completion settles validly, carrying the same `dispatch` number and, as its value, the validated result or failure payload (`null` when the action declares none or the completion carried none). Defective traffic (invalid emissions, invalid or duplicate completions, ignored signals) produces occurrences or nothing, never interaction records.

## Reported occurrences

This spec's contributions to the engine observer, all tagged with the originating view: dropped events (no binding), invalid emissions, invalid completions, duplicate completions, completions after teardown and after replacement, rejected context updates, rejected mutations (a mutation past the value size or node count limit, producing a repeated key, or addressing an index outside the array), and the reports from the expression spec (division by zero, saturation, invalid function results).
