---
title: "Runtime API"
nav_order: 7
---

# Milano Runtime API

**Status:** Beta v0.1.0 · 2026-08-15

Defines the public API surface of the two runtimes: the types a consumer or host touches, their responsibilities, and their behavior. Type names and semantics are normative and identical in role on both platforms; exact signatures are illustrative until this spec reaches Review. All public types are prefixed `Milano`.

## Value model

`MilanoValue` is the single representation for every value crossing a boundary: resolved properties into renderers, event payloads out of them, action parameters into handlers, context and state values in from the host. It models exactly the document type system: `bool`, `int`, `double`, `string`, `array`, `record`, `null`. Typed accessors return the expected type or `null`; because the gate type-checked everything, a declared property read with the declared type's accessor always succeeds. A JSON bridging utility is part of the public surface, so hosts can feed providers and context directly from API responses while preserving the int/double distinction.

## MilanoEngine

- Created with: the vocabulary artifact, the registry of renderers, the optional placeholder renderer, the default unknown-type policy, resource-limit overrides, and the observer.
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
| `children` | The node's materialized children, ready to place (present only when the type declares `children`) |
| `emit(event, payload)` | Emits a declared event into dispatch; invalid emissions are dropped and reported per Foundations |

The placeholder renderer is a distinct protocol: it receives the unknown node's raw subtree as data (never as live children) and returns platform UI.

## MilanoViewBuilder

Obtained from an engine for one document. Configured with what varies per view:

| Input | Required | Purpose |
|---|---|---|
| Document | yes | The UI document, as text or bytes |
| Context source | when the document declares context | Supplies and updates context values |
| State data provider | when the document declares state | Async source of initial state values |
| Action handler | when the document uses custom actions | Receives dispatched actions |
| Unknown-type policy | no | Per-view override of the engine default; overriding to *placeholder* with no placeholder renderer registered throws `IncompleteRegistry` at build |
| Dispatcher | no | The serialization seam (see below); defaults to the platform main thread |
| Label | no | Host-chosen name attached to this view's observability reports |

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
| `MilanoContextSource` | Current values plus a change stream | Milano validates each change atomically per Foundations. Milano ships a standard implementation (`MilanoContextHandle`): create with initial values, push updates from any thread |
| `MilanoStateDataProvider` | One async method: declared state shape in, values out | Awaited during build; its errors propagate to the build caller unchanged |
| `MilanoActionHandler` | One async method receiving a `MilanoAction` (name, typed parameters, view identity) | Normal return is success, throwing is failure; completion-exactly-once holds by construction. Invoked on the main thread; the handler may hop threads internally |
| `MilanoObserver` | One method receiving a `MilanoOccurrence` | Engine-scoped; every occurrence carries the view identity, the occurrence kind, and a node reference when one applies |
| `MilanoDispatcher` | One method executing a unit of work | The serialization seam: everything touching a view's state runs through its dispatcher, one item at a time. Each runtime ships a main-thread implementation as the default; the conformance harness injects a deterministic pump. Hosts rarely touch this |

`MilanoOccurrence` kinds are the closed union of everything the specs report: unknown-type skip or placeholder use, undeclared-property reports, dropped events, invalid emissions, duplicate completions, completions after teardown, rejected context updates, over-limit rejections, division by zero, and saturation.

## Threading

Per Foundations: renderer invocation, action handler invocation, observer callbacks, and follow-up action execution happen on the main thread. `build()` may be awaited from any thread; context updates may be posted from any thread and are applied on the main thread. Engines are thread-safe; builders are not (configure and build from one task).

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
| Change streams | AsyncSequence | Flow |
