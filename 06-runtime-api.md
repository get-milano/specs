---
title: "Runtime API"
nav_order: 7
---

# Milano Runtime API

**Status:** Stable v1.0.0 · 2026-08-16

Defines the public API surface of the two runtimes: the types a consumer or host touches, their responsibilities, and their behavior. Type names and semantics are normative and identical in role on both platforms; exact signatures are illustrative; names, roles, and behavior are normative. All public types are prefixed `Milano`.

## Value model

`MilanoValue` is the single representation for every value crossing a boundary: resolved properties into renderers, event payloads out of them, action parameters into handlers, context and state values in from the host. It models exactly the document type system: `bool`, `int`, `double`, `string`, `array`, `record`, `null`; enum values travel as their member strings, so no separate case exists. Typed accessors return the expected type or `null`; because the gate type-checked everything, a declared property read with the declared type's accessor always succeeds. A JSON bridging utility is part of the public surface, so hosts can feed providers and context directly from API responses while preserving the int/double distinction.

## MilanoEngine

- Created with: the vocabulary artifact, the registry of renderers, the optional placeholder renderer, the default unknown-type policy, resource-limit overrides, the observer, and the user-interaction observer.
- Creation validates everything and fails fast with `InvalidVocabulary` or `IncompleteRegistry` per the vocabulary schema spec.
- An engine is immutable after creation and safe to share across threads. Apps may hold several engines.
- Its only factory: creating a MilanoViewBuilder for a document.

## MilanoRenderer

The consumer implements one renderer type per component type, conforming to the Milano renderer protocol, and registers instances by component type name.

A renderer receives a `MilanoNode` and returns platform UI (a SwiftUI view; a composable). `MilanoNode` exposes:

| Member | Purpose |
|---|---|
| `type` | The component type name |
| `reference` | The node's id, or canonical path when no id is declared |
| `property(name)` | The resolved value of a declared property, as `MilanoValue`, reactive: property changes drive recomposition/re-evaluation natively per platform |
| `children` | The node's materialized children, ready to place; always empty for types that do not declare `children` |
| `emit(event, payload)` | Emits a declared event into dispatch; invalid emissions are dropped and reported per Foundations |
| `metadata` on the hosting view | The document's `metadata` section, verbatim and untyped, so producer annotations (campaign tags, experiment ids) reach host code without a side channel |

The placeholder renderer is a distinct protocol: it receives the unknown node's raw subtree as data (never as live children) and returns platform UI.

## MilanoViewBuilder

Obtained from an engine for one document. Configured with what varies per view:

| Input | Required | Purpose |
|---|---|---|
| Document | yes | The UI document, as text or bytes |
| Context source | when the document declares context | Supplies and updates context values |
| State data provider | when the document declares state | Async source of initial state values |
| Action handler | when the document uses custom actions | Receives dispatched actions |
| Action allowlist | no | Grants only the listed custom actions to this surface; binding any other fails the build (`SchemaViolation`, rule `action-capability`) |
| Action declarations | no | Per-surface custom action declarations and signature overrides; joined with the vocabulary's actions to form the surface's granted set |
| Unknown-type policy | no | Per-view override of the engine default (which itself defaults to *fail*); overriding to *placeholder* with no placeholder renderer registered throws `IncompleteRegistry` at build, whose missing list then contains the literal sentinel `"(placeholder renderer)"` rather than a component type name |
| Dispatcher | no | The serialization seam (see below); defaults to the platform main thread |
| Label | no | Host-chosen name attached to this view's observability reports |

The hosting container additionally offers a quick overload taking raw document and vocabulary input plus a renderer map, constructing engine, registry, and builder internally with declared state synthesized as zero-values; engine and build failures both surface through the failure content. It is a convenience for first integrations and simple embeds, not a replacement for the shared-engine architecture.

`build()` is asynchronous and either returns a MilanoView or throws: the gate errors from the document model spec, or the state data provider's own error, propagated unchanged. Missing required inputs (a document declaring context built with no context source) are a `SchemaViolation` at the gate.

## MilanoView

The built, guaranteed-renderable view: a SwiftUI `View` value in the Swift runtime, a class exposing composable content in the Kotlin runtime. Bound to its document for its lifetime; presentation reacts to state and context per the state and actions spec. Carries a stable identity (plus the builder's label) used in all observability reports.

## MilanoHost

The hosting container, for hosts that want the swap managed for them:

- Takes: a MilanoViewBuilder, optional loading content, and error content (a closure receiving the typed error).
- Behavior: presents loading content immediately, awaits the build, replaces it with the MilanoView on success or the error content on failure. Building starts once per container lifetime; the host recreates the container to retry.
- Hosts that prefer full control simply await `build()` themselves and never use MilanoHost.

## Host-side protocols

| Protocol | Shape | Semantics |
|---|---|---|
| `MilanoContextSource` | Current values plus a subscription: `subscribe` registers a change callback and returns a cancellation, invoked by the runtime at teardown | Milano validates each change atomically per Foundations. Milano ships a standard implementation (`MilanoContextHandle`): create with initial values, push updates from any thread |
| `MilanoStateDataProvider` | One async method: declared state shape in, values out | Awaited during build; its errors propagate to the build caller unchanged |
| `MilanoActionHandler` | One async method receiving a `MilanoAction` (name, typed parameters, view identity) | Normal return is success and its returned optional `MilanoValue` is the completion result, validated against the action's declared `result` type; throwing is failure. Through this funnel, completion-exactly-once holds by construction; the runtime still guards the completion path defensively and reports duplicates. Invoked asynchronously off the dispatcher with immutable data; the handler may run and hop threads freely, and its completion is funneled back through the dispatcher |
| `MilanoObserver` | One method receiving a `MilanoOccurrence` | Engine-scoped and retained by the engine for its lifetime; every occurrence carries the view identity, the occurrence kind, and a node reference when one applies. Engine observability only: defects and diagnostics, never user interactions |
| `MilanoUserInteractionObserver` | One method receiving a `MilanoUserInteraction` | Engine-scoped and retained like the observer; the user-interaction analytics stream, described below |
| `MilanoDispatcher` | One method executing a unit of work | The serialization seam: everything touching a view's state runs through its dispatcher, one item at a time. Each runtime ships a main-thread implementation as the default; the conformance harness injects a deterministic pump. Hosts rarely touch this |

`MilanoOccurrence` kinds are the closed union of everything the specs report: unknown-type skip or placeholder use, undeclared-property reports, dropped events, invalid emissions, invalid completions, duplicate completions, completions after teardown, rejected context updates, division by zero, and saturation.

## User interaction analytics

A second, independent stream carries user interactions to the host for product analytics. It is optional from every direction: documents declare nothing for it, vocabularies declare nothing for it, and an engine created without a `MilanoUserInteractionObserver` pays nothing. Milano implements no tracker; it delivers structured records and the host decides what to do with them.

A `MilanoUserInteraction` carries the kind, the view identity, the node reference when the interaction is anchored to a node, the event or action name when one applies, and a value with the interaction's data. Records are not redacted: event payloads, action parameters, and document metadata pass through as-is, since the receiving host already owns the data.

The stream has two sources:

- **Runtime-captured**, requiring nothing from renderers: `viewBuilt` (the impression, with the document's `metadata` as the value), `viewTornDown`, `event` (every declared emission with a valid payload, bound or not, named after the event and carrying the payload), `actionDispatched` (named after the action, carrying the captured parameters, anchored to the node whose binding dispatched it), and `completionSucceeded` / `completionFailed` (named after the action, anchored to the same node).
- **Renderer-reported**, through one node method (`userInteraction(kind, value)`) that flows straight to the stream and never touches dispatch or state: `tap`, `doubleTap`, `longPress`, `focusGained`, `focusLost`, `textChanged`, `toggled`, `selectionChanged` (segmented controls, pickers, tabs), `valueChanged` (sliders, steppers), `appeared`, `disappeared`, and `scrolled`. Renderers use these for signals the document does not model as events; signals that are document events already arrive through `event`.

The kind set is the closed union of both lists. Interactions and occurrences never mix: a defective emission is an occurrence, a valid one is an interaction, and the streams reach different protocols.

## Threading

Per Foundations: renderer invocation, follow-up action execution, and runtime observer callbacks happen on the main thread. Action handlers are invoked asynchronously off the dispatcher (their parameters are immutable data; completions are funneled back through the dispatcher). `build()` may be awaited from any thread; occurrences reported during build arrive on the build caller's thread. Context updates may be posted from any thread and are applied on the main thread. Engines are thread-safe; builders are not (configure and build from one task).

## Platform mapping

Milano targets toolkits, not operating systems: each runtime is usable on every platform its toolkit supports (SwiftUI on iPhone, iPad, macOS, watchOS; Compose on Android and desktop).

| Concept | SwiftUI runtime | Compose runtime |
|---|---|---|
| Language / toolkit | Swift 6, SwiftUI | Kotlin 2.0+, Jetpack Compose |
| Protocols | `protocol` | `interface` |
| Async boundary | `async throws` | `suspend` (failure via exception) |
| `MilanoValue` | enum with associated values | sealed class |
| `MilanoView` | `View`-conforming struct | class with `@Composable` content |
| `MilanoHost` | SwiftUI view | `@Composable` function |
| Change subscriptions | Callback with returned cancellation | Callback with returned cancellation |
