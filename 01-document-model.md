---
title: "Document model"
nav_order: 2
---

# Milano Document Model

**Status:** Stable · contract 2.1 · repository release 2.1.0 · 2026-08-31

Defines the abstract document model and its canonical JSON encoding: the top-level structure, the node envelope, values and expressions, core constructs, lifecycle bindings, identity, validation, the error taxonomy, and resource limits. Everything here operates within the guarantees fixed by [Foundations](00-foundations.html).

## Document structure

A document is a single JSON object, encoded in UTF-8, with reserved top-level sections. Unknown core fields follow the contract tolerance rules from Foundations.

| Section | Required | Purpose |
|---|---|---|
| `version` | yes | The contract version the document targets (major.minor.patch) |
| `vocabulary` | no | The vocabulary the document requires: a `name` and an optional `min` version (major.minor.patch) |
| `context` | no | Declaration of the context keys the document reads: name and type |
| `state` | no | Document-level state declarations: name and type |
| `root` | yes | The single root node |
| `on` | no | Lifecycle bindings (contract 2.1): a map from a lifecycle signal name (`appear`, `disappear`) to one action or an ordered list of actions; any other shape is `MalformedDocument`. See Lifecycle bindings |
| `watch` | no | Watch bindings (contract 2.1): a map from a declared state key to one action or an ordered list of actions; any other shape is `MalformedDocument`. See Watch bindings |
| `metadata` | no | Free-form producer data as a JSON object (any other shape is `MalformedDocument`); never interpreted by Milano, passed through to the host |

Documents separate structure from data. The `context` and `state` sections declare shapes only; no section of a document ever carries a variable data value, so a document is cacheable independently of the data it renders. Context values are supplied by the host's context source; every declared key is required, and values are validated at the gate and on every update. State initial values are supplied by the host's asynchronous state data provider, awaited during building and validated against the declarations. Provider failures propagate to the caller unchanged: they are host errors, not Milano errors.

## Type system

Every declaration (state, context, component properties, action parameters, event payloads) uses one type language:

- Primitives: `bool`, `int` (64-bit signed), `double` (IEEE 754 binary64), `string` (Unicode).
- `enum`: a closed set of named string values. Members follow the identifier grammar and must be unique; the set must be non-empty. At runtime an enum value is its member string; only the static type knows the set.
- `array` of any type.
- `record` with named, typed fields.
- Types are non-nullable by default. Any type may be marked optional; JSON `null` is valid only for optional types, and an omitted optional value is equivalent to `null`.

In JSON, a type descriptor takes one of four forms:

- A primitive is its name string, with a trailing `?` for optional: `"int"`, `"string?"`.
- An enum is an object with an `enum` key holding the member list, plus `"optional": true` when optional: `{"enum": ["info", "warning", "danger"]}`.
- An array is an object with an `array` key holding the element's type descriptor, plus `"optional": true` when the array itself is optional.
- A record is an object with a `record` key holding a map of field name to type descriptor, plus `"optional": true` when the record itself is optional.

Two enum types are the same exactly when their member sets are equal: enum identity is structural, like records. Declaration order is not part of that identity, but it is what the zero value reads (expression language spec, Host functions), so a runtime keeps the declared order beside the member set rather than in it: a representation that stores members as an unordered set alone cannot answer for the zero.

Integer and floating-point behavior (ranges, overflow, coercion rules in expressions) is fixed by the expression language spec and conformance-tested; a JSON number with a fractional part never satisfies an `int` declaration.

Validation of data values (supplied context, provider state, literal properties and parameters) against declarations follows two further rules, identical in every runtime:

- An `int` value satisfies a `double` declaration and is canonicalized to `double`, mirroring expression promotion. A `double` value never satisfies an `int` declaration.
- Record values are validated strictly against their declared shape: an undeclared field is a mismatch; a missing optional field canonicalizes to `null`; a missing non-optional field is a mismatch.
- An `enum` declaration is satisfied only by one of its member strings. A non-member string is a mismatch at every boundary this rule reaches: literal properties and parameters at the gate, supplied state and context at build, context updates, event emissions, and completion results at runtime.

## Node envelope

Every node is a JSON object with reserved keys. The envelope belongs to the contract: additions arrive only through contract versions, and a runtime encountering an envelope key it does not know applies the contract tolerance rules from Foundations (ignored, since only semantics-preserving additions can be minor).

| Key | Required | Purpose |
|---|---|---|
| `type` | yes | Component type name from the vocabulary, or a core construct name |
| `id` | no | Document-unique identifier: a non-empty string, else `MalformedDocument`; uniqueness validated at the gate |
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
- References are namespaced by reserved roots: `state`, `context`, `event` (only within a node's `on` action bindings, giving access to the triggering event's payload; lifecycle bindings have no payload), `result` (only within the `onSuccess` bindings of an action declaring a result type, giving access to the handler's returned value), and `failure` (contract 2.1; only within the `onFailure` bindings of an action declaring a failure type, giving access to the value the handler failed with; see the vocabulary schema spec).

## Actions

An action is a JSON object whose reserved `action` key names its type. Built-in actions live in the reserved `$` namespace and are always available. Custom action types use consumer-defined names with typed parameters, declared only by consumer code: globally in the engine's vocabulary, and per surface by the builder, which may grant a subset of the vocabulary's actions and declare or override signatures for its surface (see the vocabulary schema spec). Documents never declare actions. Binding a custom action outside the surface's granted set is a `SchemaViolation` with rule `action-capability`. Parameters are sibling keys of `action`, and any parameter value may be a literal or an expression (including expressions over `event`); the gate validates parameters against the granted declaration.

Like component types, action types require host code (a handler that interprets them), so declarations live with that code, never in documents. Declarations type the payload; meaning is assigned per surface by the builder's handler, so one action name may carry different behavior, and via builder overrides a different signature, on different surfaces.

| Action | Parameters | Purpose |
|---|---|---|
| `$set` | `key`: a declared top-level state key; `value`: the new value, literal or expression | Mutate document state; field-level targets inside records are not supported, the whole key is assigned |
| `$append` | `key`: a declared state key of a non-optional array type; `value`: the element to add, literal or expression, typed as the array's element type | Contract 2.1. Append one element at the end of the array |
| `$remove` | `key`: as `$append`; `at`: the zero-based index of the element to remove, an `int` literal or expression | Contract 2.1. Remove one element; an index outside the array is a rejected mutation at runtime (state and actions spec) |
| `$update` | `key`: a declared state key of a non-optional array type whose elements are non-optional records; `at`: as `$remove`; `field`: the name of a declared field of the element record, a literal string; `value`: the field's new value, literal or expression, typed as the field | Contract 2.1. Replace one field of one element; the rest of the element and the array are unchanged |
| `$sequence` | `actions`: ordered list of actions | Run actions in order |
| `$when` | `condition`: bool expression; `then`: optional action list; `else`: optional action list | Conditional dispatch |
| custom | per its granted declaration | Routed as data to the host's action handlers |

- A bare JSON array of actions is shorthand for `$sequence`.
- The three array actions are the only element-level writers: a document that keeps a collection in state (rows the user edits, a cart, a list of toggles) changes it one element at a time, and a `$repeat` template binds them with `<as>_index` as `at` (state and actions spec, Event dispatch: the index is the element's position at dispatch time, keyed instances included). Every declared position in them (`value`, `at`) accepts what a `$set` value accepts: promotion of `int` to `double`, a non-optional value where an optional is declared, a member literal in an enum position (expression language spec). The encoding rules, each an `action-encoding` violation: `key` must name a declared state key (`declared state key`) of a non-optional array type (`array state key`); `$update` needs record elements (`record element`) and a declared field (`declared field`); a missing `at`, `value`, or `field` is reported by the parameter's name as `expected`; any other key on the action is `declared parameter` with the key as `found`. A document declaring a contract before 2.1 may not carry them: there they are the `contract-feature` violation (Validation, below).
- Custom actions may carry `onSuccess` and `onFailure` keys, each an action or action list, bound to the handler's asynchronous completion. Built-ins complete synchronously and do not take them.
- Dispatch semantics (ordering, concurrency, dispatch identity, completion after view teardown, event payload rules) are fixed in the state and actions spec; this spec fixes only the encoding.

## Constructs

A construct is a node whose `type` is in the reserved `$` namespace. Constructs belong to the contract, not to the vocabulary: no renderer is registered for them and renderers never see them. Contract 2.0 defines one.

### `$repeat`

Repeats a template once per element of an array. The construct is transparent: its instances take its place in the parent's children, in order, so a vocabulary declares nothing for it and a parent that accepts children may hold one.

| Key | Required | Purpose |
|---|---|---|
| `type` | yes | `$repeat` |
| `id` | no | As for any node; the base of every instance's reference |
| `items` | yes | An expression (never a literal, since documents carry no data) of a non-optional `array` type, evaluated at resolution |
| `as` | yes | An identifier naming the element: it binds two expression roots in the template, `<as>` (the element, typed as the array's element type) and `<as>_index` (an `int`, zero-based) |
| `key` | no | Contract 2.1. An expression (never a literal) of a non-optional `string` or `int` type, evaluated per element with the template's roots in scope, that identifies the instance: its rendering replaces the element index in the instance's reference, so identity follows the element when the array is reordered, grown, or shrunk |
| `children` | yes | The template: one or more nodes, instantiated together per element |

Rules, all checked at the gate under rule `repeat` (detail `expected` names the requirement), in this order: position, then the absence of `properties` and `on`, then `items` present as an expression, then `as`, then the template's presence, then the `items` type, then `key`, then the template's nodes:

- A `$repeat` is never the root and carries neither `properties` nor `on`.
- `as` is an identifier that is not `state`, `context`, `event`, `result`, or `failure`, and nested repeats bind distinct names; an inner template may read an outer element.
- `items` must type-check to a non-optional array; the element type is what `<as>` has.
- `key`, when present, is an expression (`expected` `key expression`, `found` the literal's kind) whose type is a non-optional `string`, `int`, or enum (`expected` `key type`, `found` the type). A document declaring contract 2.0 may not carry it: there it is the `contract-feature` violation (Validation, below).
- A document declaring contract 1.x may not use the construct at all: there it is the `construct` violation, as any `$` type.

An instance's reference is the template node's reference followed by the instance's identity in brackets, for every enclosing repeat from the outermost in: `card[2]`, and `line[2][0]` for a template node inside a repeat inside another. Without `key` the identity is the element's zero-based index; with `key` it is the key's rendering, a string verbatim (an enum by its member string) and an int in decimal: `card[abc]`, `line[abc][7]`. References are never parsed, only compared, so a key may contain any character. Renderers emit with the instance reference, and every report about an instance uses it. Ids inside a template are document-unique as ever; the suffix is what tells instances apart.

Keys are distinct within one materialization of a repeat: two elements rendering the same key are a data defect. At build it is a `SchemaViolation` under rule `repeat` anchored to the construct (`expected` `distinct key`, `found` the repeated rendering); at runtime, a state mutation or context update that would produce one is rejected whole and reported with the same detail (state and actions spec).

The materialized tree, instances included, counts against the node count limit: at build, past the limit is `LimitExceeded` for `maxNodeCount` with the materialized count as `actual`; at runtime, an update that would grow past it is rejected whole (state and actions spec). Resolution re-materializes a repeat whenever `items`, or anything an instance reads, changes; with `key`, an instance whose key is still present keeps its reference through the change.

### `$if`

Contract 2.1. Materializes one of two node lists, chosen by a condition. The construct is transparent, like `$repeat`: the chosen branch's nodes take its place in the parent's children, in order, so a vocabulary declares nothing for it and a parent that accepts children may hold one.

It is the tree-level counterpart of the `$if` function, which chooses between two values, and of the `$when` action, which chooses between two action lists: the same question asked of a subtree. Two things named `$if` do not collide, because node types, action names, and function names are separate namespaces.

| Key | Required | Purpose |
|---|---|---|
| `type` | yes | `$if` |
| `condition` | yes | An expression (never a literal) of a non-optional `bool` type, evaluated at resolution |
| `then` | yes | The nodes to materialize when the condition holds: one or more |
| `else` | no | The nodes to materialize when it does not; absent means nothing is materialized |

Rules, all checked at the gate under rule `conditional` (detail `expected` names the requirement), in this order: position, then the absence of `properties`, `on`, and `id`, then undeclared keys, then `condition` present as an expression, then each branch's shape, then the `condition` type, then the branches' nodes:

- An `$if` is never the root, and carries neither `properties`, `on`, nor `id`. It takes no `id` because it is never referenced: it renders nothing itself, and its branches' nodes carry their own.
- `condition` must type-check to a non-optional `bool`.
- Each branch present is a list of one or more nodes. An `$if` with no `else` materializes nothing when its condition is false, which is how a document says "only when".
- **Both branches are validated**, whichever one a given build takes: a defect in the untaken branch fails the build, so a condition flipping at runtime can never reveal a document the gate never saw. Ids are document-unique across both branches for the same reason.
- A document declaring contract 2.0 may not carry it: there it is the `contract-feature` violation naming `$if`. A document declaring contract 1.x may not use the construct at all: there it is the `construct` violation, as any `$` type.

Only the taken branch is resolved, as only the taken branch of the `$if` function is evaluated: the untaken branch produces no arithmetic or invalid-result reports. A node inside a branch has the construct's path followed by the branch and the node's index within it, `root/children[2]/then[0]`, so a report names which branch it came from; a node carrying an `id` is referenced by that id as ever.

The node count and tree depth limits see the whole document, both branches included, for the same reason both are validated: a subtree hidden in an untaken branch is still one the gate walks, and a limit a branch could slip past would not be a limit. The materialized count, charged separately against the same `maxNodeCount`, sees only the branch that was taken. Resolution re-materializes the construct whenever the condition, or anything the chosen branch reads, changes; a condition that flips replaces the subtree, which is what choosing a different branch means.

### `$switch`

Contract 2.1. Materializes one of several node lists, chosen by an enum. `$if` asks a yes-or-no question of a subtree; `$switch` asks which of a closed set, and is transparent the same way: the chosen branch's nodes take its place in the parent's children.

| Key | Required | Purpose |
|---|---|---|
| `type` | yes | `$switch` |
| `subject` | yes | An expression (never a literal) of a non-optional `enum` type, evaluated at resolution |
| `cases` | yes | A map from member name to the nodes that member materializes: at least one, each a non-empty node list |
| `default` | no | The nodes every member without a case materializes |

Rules, all checked at the gate under rule `switch` (detail `expected` names the requirement), in this order: position, then the absence of `properties`, `on`, and `id`, then undeclared keys, then `subject` present as an expression, then `cases` present, then the `subject` type, then each case, then coverage, then the branches' nodes:

- A `$switch` is never the root, and carries neither `properties`, `on`, nor `id`, for the reasons `$if` does not.
- `subject` must type-check to a non-optional `enum`.
- Every key of `cases` names a member of that enum, and every branch is a list of one or more nodes.
- **Every member is covered, by a case or by `default`.** A member that neither covers is the violation `every member or a default`, naming the first uncovered member. This is the construct's reason to exist: a member added to the enum later fails the build rather than rendering nothing, which is what a chain of `$if`s would do.
- Both, and every, branch is validated, whichever one a given build takes, and ids are document-unique across all of them, exactly as for `$if`.
- A document declaring contract 2.0 may not carry it: there it is the `contract-feature` violation naming `$switch`. A document declaring contract 1.x may not use the construct at all: there it is the `construct` violation.

Only the chosen branch is resolved. A node inside one has the construct's path followed by the branch and its index, `root/children[2]/cases[late][0]` or `root/children[2]/default[0]`, so a report names the member it came from. The node count and tree depth limits see every branch, as they do for `$if`, while the materialized count sees only the chosen one. Resolution re-materializes the construct whenever the subject, or anything the chosen branch reads, changes.

## Lifecycle bindings

Contract 2.1. The top-level `on` section binds action lists to the two lifecycle signals a host delivers to a view (runtime API spec): `appear`, the view has come on screen, and `disappear`, it has left it.

| Signal | Bound actions run when |
|---|---|
| `appear` | The host signals that the view is on screen: on first presentation, and again each time it returns after a `disappear` |
| `disappear` | The host signals that the view has left the screen |

The section is a JSON object whose keys are signal names and whose values are one action or an ordered list of actions, exactly as a node's `on` encodes event bindings. Rules:

- A key that is not `appear` or `disappear` is a `SchemaViolation` under rule `event-binding` with no node, `expected` `lifecycle event`, `found` the key.
- Lifecycle signals carry no payload: `event` is not a root inside these bindings, and referencing it is a `SchemaViolation` under rule `expression`. `result` and `failure` bind inside custom actions' follow-ups exactly as elsewhere. No `$repeat` binding is in scope.
- Custom actions bound here count as the document binding custom actions: the surface needs an action handler (rule `action-handler`).
- A document declaring contract 2.0 may not carry the section: there it is the `contract-feature` violation (Validation, below).

How signals are accepted, ordered with events, and reported is fixed in the state and actions spec.

## Watch bindings

Contract 2.1. The top-level `watch` section binds action lists to changes of state keys: the document reacts to its own data, so a derived value can be recomputed, a quote refreshed through a custom action, or a draft autosaved, without a host side channel.

```json
"watch": {
  "amount": [ { "action": "$set", "key": "fee", "value": { "$expr": "$round(state.amount * 0.015 * 100.0) / 100.0" } } ]
}
```

The section is a JSON object whose keys are declared state keys and whose values are one action or an ordered list of actions, exactly as a node's `on` encodes event bindings. Rules:

- A key that the document's `state` section does not declare is a `SchemaViolation` under rule `watch` with no node, `expected` `declared state key`, `found` the key.
- Watch lists carry no payload: `event` is not a root inside them, and referencing it is a `SchemaViolation` under rule `expression`; no `$repeat` binding is in scope. `result` and `failure` bind inside custom actions' follow-ups exactly as elsewhere. The new value is read where every value is read: `state.<key>`.
- Custom actions bound here count as the document binding custom actions: the surface needs an action handler (rule `action-handler`).
- A document declaring a contract before 2.1 may not carry the section: there it is the `contract-feature` violation (Validation, below).

When a watch list runs, how it is ordered with the list that changed the key, and why it can never trigger another watch are fixed in the state and actions spec (Watch bindings).

## Identity and paths

- `id` is optional; when present it is a non-empty string, unique across the document. An empty `id` is an envelope violation (`MalformedDocument`), since it would be an empty reference in every report about the node.
- Every node also has a canonical structural path computed from its position: the root node's path is `root`, and each child appends `/children[i]` with its zero-based index (for example `root/children[2]/children[0]`).
- Observer reports and error details reference nodes by `id` when present, canonical path otherwise.

## Validation

The gate validates in a fixed, conformance-tested order, so identical documents fail identically on every platform:

1. Parse: well-formed JSON, correct envelope shapes.
2. Version: the declared major must be one the runtime implements and the declared minor at most the highest minor it implements for that major (Foundations, Versioning); the patch is ignored.
3. Vocabulary requirement: when the document declares one, the engine's vocabulary must carry the same `name`, and when `min` is present its `version` must be at least `min` (numeric comparison of major, minor, patch). A mismatch is a `SchemaViolation` with rule `vocabulary-requirement`, `expected` the document's demand, `found` what the engine holds. A document with no `vocabulary` section performs no check: binding stays positional, and the requirement is the producer's opt-in guard for staggered rollouts. The minimum-only form is sound because vocabulary evolution is additive within a major (see the vocabulary schema spec): any version at or above the minimum carries everything the document needs.
4. Resource limits: document size (checked on the raw bytes before parsing, alongside step 1), tree depth, and node count against the limits below; expression length is checked per expression in step 5.
5. Vocabulary walk: one pass over the tree, in document order. At each node, in order: `id` uniqueness, the reserved `$` type prefix, type resolution against the schema (unknown types trigger the unknown-type policy), properties (undeclared ones per the strict-mode rules from Foundations; declared ones type-checked, with expressions parsed and statically typed as they are encountered), children acceptance, then event bindings against the declared events and their action lists (built-in parameters against this spec, custom actions against the surface's granted action set: the vocabulary's declarations, narrowed and overridden by the builder). After the tree, the lifecycle bindings (contract 2.1): signal names, then each bound action list under the same rules with no `event` root; then the watch bindings (contract 2.1): each key against the state declarations, then its action list under the same rules. Because the walk is one pass, the first defect wins when a document violates several rules: document order among nodes and array elements, and the member order below within one object.
6. Data checks: context declarations versus supplied values, state declarations versus the values returned by the state data provider; every value also within the value size limit below.

The walk applies the rules of the contract version the document declares. A feature that a later minor of the same major introduced is a `SchemaViolation` under rule `contract-feature` where the walk meets it, with `expected` the `major.minor` that introduced the feature and `found` the feature's name; so a document declaring 2.0 fails identically on a 2.0 and a 2.1 runtime instead of being silently misread by one of them. The features contract 2.1 introduced, by the name the detail carries: the `key` of a `$repeat` (`key`), the top-level lifecycle section (`on`), the top-level watch section (`watch`), the `failure` expression root (`failure`), the numeric functions `$abs`, `$min`, `$max`, `$floor`, `$ceil`, and `$round` (each by its name, `$` included), every host function the surface declares (by the function's name; under 2.0 a call to one is this violation, not the `expression` violation an unknown function raises), and the array actions (`$append`, `$remove`, `$update`, each by its name, `$` included). The `$repeat` construct itself in a 1.x document stays the `construct` violation, since 1.x has no constructs at all.

Wherever a step visits the members of a JSON object (a node's `properties` and `on` bindings, an action's parameters, the `context` and `state` declarations and the values supplied for them, a vocabulary's declared parameters), it visits them in lexicographic order of the key by Unicode scalar value, never in document order. JSON defines no order for object members, and a serializer that reorders keys must not change which defect is reported first or in which order a node's expressions report; document order applies to arrays, which JSON does order: children and action lists. Identifiers are ASCII, so every platform's default string ordering agrees.

Steps 1 through 5 need only the document and the engine. Building is asynchronous overall: the gate then awaits the state data provider and completes the cross-checks. A provider failure propagates to the caller unchanged; values that do not match the declarations are a `SchemaViolation`.

Three rules complete the gate's behavior:

- Supplied context and provider values may contain keys the document does not declare; they are ignored. The document reads only what it declares, which lets one context source serve many views.
- Occurrences detected during the gate (skipped or placeholder nodes, undeclared properties) are reported to the observer only when building succeeds; a failed build reports nothing.
- When the root node itself is an unknown type under the *skip* policy, the result is a valid, empty view: there are no siblings to keep.

## Error taxonomy

The closed set of typed errors the gate can throw, with the structured detail each carries. Every error also carries a non-normative diagnostic message.

| Error | Raised when | Detail fields |
|---|---|---|
| `MalformedDocument` | Input is not well-formed JSON or violates envelope structure | Location of the defect (path when determinable) |
| `UnsupportedVersion` | The declared major is not implemented, or the declared minor exceeds what the runtime implements for it | `declared`, the document's version; `supported`, the runtime's ranges as `major.minor` strings (`"1.0"`, `"2.0"`) |
| `SchemaViolation` | Vocabulary, expression typing, action encoding, event, id, or namespace rules are violated; supplied context or initial-state values do not match declarations | The rule violated; expected; found; and the node reference (id or path) when the violation is anchored to a node (document-level violations, such as a data value not matching its declaration, carry none) |
| `UnknownComponentType` | A type not declared in the vocabulary is found and the effective policy is *fail* | Node reference; the unknown type name |
| `LimitExceeded` | Any resource limit is exceeded at the gate, the node count measured on the materialized tree | The limit's name; its configured value; the actual value |

The `rule` strings a `SchemaViolation` may carry are contract, pinned by the conformance suite, and so is the detail each carries (an absent cell is `null`):

| Rule | Violation | `node` | `expected` | `found` |
|---|---|---|---|---|
| `construct` | A node `type` begins with the reserved `$` prefix and names no construct the document's contract version admits | the node | `component type` | the type name |
| `contract-feature` | The document uses a feature (a construct key, a document section, an expression root, a function) that a later minor of its declared major introduced | the node, when the feature sits in one | the `major.minor` that introduced the feature (`2.1`) | the feature's name (`key`, `on`, `failure`, `abs`, ...) |
| `switch` | A `$switch` violates its encoding: at the root, carrying `properties`, `on`, or `id`, an undeclared key, a missing or non-expression `subject`, no `cases`, a case naming a non-member, a branch that is not a non-empty node list, a `subject` that is not a non-optional `enum`, or a member that neither a case nor a `default` covers | the node | the requirement: `not the root`, `no properties`, `no on`, `no id`, `declared key`, `subject expression`, `cases`, `enum subject`, `declared member`, `case branch`, `default branch`, `every member or a default` | what was found |
| `conditional` | An `$if` violates its encoding: at the root, carrying `properties`, `on`, or `id`, an undeclared key, a missing or non-expression `condition`, a branch that is not a non-empty node list, or a `condition` that is not a non-optional `bool` | the node | the requirement: `not the root`, `no properties`, `no on`, `no id`, `declared key`, `condition expression`, `then branch`, `else branch`, `bool condition` | what was found |
| `repeat` | A `$repeat` violates its encoding: at the root, carrying properties or bindings, without a template, `items` missing, a literal, or not a non-optional array, `as` missing, reserved, or shadowing an enclosing binding, `key` a literal or of the wrong type, or two elements rendering the same key | the node | the requirement: `child position`, `items expression`, `array items`, `template`, `binding identifier`, `distinct binding`, `key expression`, `key type`, `distinct key` | what was found |
| `id-uniqueness` | A node `id` appears more than once in the document | the repeated id | | the id |
| `children` | A node carries `children` but its component type does not accept them | the node | `no children` | `children` |
| `undeclared-property` | An undeclared property on a `strict` component type | the node | | the property name |
| `property-type` | A literal property value does not match the declared type | the node | the declared type, or `enum member` | the literal's kind, or the non-member string |
| `event-binding` | A node's `on` entry names an event the component type does not declare, or the document's `on` entry names a signal that is not `appear` or `disappear` | the node; none for the document's | `declared event`, or `lifecycle event` | the event or signal name |
| `expression` | An expression fails to parse or type-check against the expected type | the node; none in a lifecycle or watch list | the type the position expects | |
| `action-encoding` | A built-in or custom action violates its encoding: unknown or missing parameters, ill-typed values, an undeclared or unsuitable target of `$set`, `$append`, `$remove`, or `$update` | the node; none in a lifecycle or watch list | `declared state key`, `array state key`, `record element`, `declared field`, `declared parameter`, or the name of the missing required parameter | the undeclared key, field, or parameter; none for a missing one |
| `action-capability` | A custom action outside the surface's granted set | the node | `granted action` | the action name |
| `vocabulary-requirement` | The document's declared vocabulary requirement is not met by the engine's vocabulary | | the required name, or `>=` the required minimum | the held name or version |
| `context-declaration` | A context declaration is malformed (non-identifier key, invalid descriptor) or a supplied context value does not match it | | `identifier`, `type descriptor`, the missing key, the declared type, or `enum member` | the malformed key, the value's kind, or the non-member string |
| `state-declaration` | A state declaration is malformed (non-identifier key, invalid descriptor), a provided state value does not match it, or the document declares state and the surface configured no state data provider | | `identifier`, `type descriptor`, the declared type, `enum member`, or `state data provider` | the malformed key, the value's kind (`null` when the provider omitted a required value), or the non-member string |
| `watch` | A `watch` entry names a key the document's `state` section does not declare | | `declared state key` | the key |
| `action-handler` | The document binds custom actions and the surface configured no action handler (raised by the builder at build, before dispatch exists) | | `action handler` | |
| `function-handler` | The document calls host functions and the engine configured no function handler (raised at build, before any evaluation) | | `function handler` | |

Occurrences (rejected context updates and dropped events at runtime, skipped or placeholder nodes at the gate) are not errors: they flow to the engine observer as defined in Foundations.

## Resource limits

Defaults, adjustable per engine.

| Limit | Default |
|---|---|
| Maximum tree depth | 32 |
| Maximum node count | 10,000 |
| Maximum document size | 1 MiB |
| Maximum expression length | 1,024 Unicode scalars |
| Maximum value size | 65,536 |

The first four are gate limits: the tree, its expressions, and their lengths are fixed at the gate, and no update can grow them. Values are not fixed at the gate, so the value size limit applies wherever a value enters state or context: at the gate, to the supplied context values and the initial state values (step 6, a `LimitExceeded` with limit `maxValueSize`), and at runtime, to every context update and every `$set`, where a value past the limit rejects the update or the mutation whole and reports it (state and actions spec). Event payloads and completion results are not bounded: they live for one dispatch, and whatever a document keeps from them passes through `$set`.

The size of a value counts one for a bool, an int, a double, or null; one per Unicode scalar for a string; and, for an array or a record, one plus the sizes of its elements or fields. Record shapes and nesting are fixed by declarations, so one number bounds every value.

Limits are denial-of-service bounds for untrusted input, not performance budgets: a document within every limit can still be a poor fit for an interactive surface. Measured guidance lives in the runtime documentation.

## Notes

- An official schema, `schemas/document.schema.json` in this repository, validates the canonical encoding's structure (envelope shapes, type descriptors, expression wrappers, action encoding). Semantic rules stay with the gate: vocabulary resolution, expression typing, id uniqueness, and resource limits are not schema-checkable.
- The schemas are open wherever the contract may grow (the top level, the node envelope, the `vocabulary` section, type descriptors), because the tolerance rule in Foundations makes unknown keys there ignorable rather than invalid; the `$expr` wrapper is the one closed object, since this model defines it as exactly single-key. Strictness against typos in those objects is producer tooling's job, not the contract's: the reference checker's `--document` mode warns about unknown keys in contract-governed objects, and the vocabulary-specialized document schema is strict about component properties, which are vocabulary-governed and therefore fixed.
- `metadata` is host-only: it is never visible to expressions.
- The identifier grammar for state keys, context keys, and all vocabulary names is defined in the [vocabulary schema spec](02-vocabulary-schema.html).
- Custom action, completion result, failure payload, event payload, and host function declarations are owned by the [vocabulary schema spec](02-vocabulary-schema.html). Expression grammar and semantics, host function calls included, are owned by the [expression language spec](03-expression-language.html). Dispatch semantics, dispatch identity, lifecycle signal handling, watch execution, and document replacement are owned by the [state and actions spec](04-state-and-actions.html).
