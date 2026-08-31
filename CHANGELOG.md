# Changelog

Changes to the specification, its conformance suite, and its tools.

Two versions live here, and they are not the same number.

The headings below are **repository tags**, cut alongside the SDK release
they were verified against, so that a given SDK version names an exact
state of the specification, its vectors, and its tools.

The **contract version** is what documents and vocabularies declare
(`"milano": "1.0.0"`), and it moves only when the contract itself does.
Clarifications that describe behaviour every engine already implements do
not move it; neither do tool or suite changes. Anything that changes what
a conformant engine must do is a contract change, and comes with vectors.
The contract was 1.0 from the first release through 1.3.1; repository
release 2.0.0 moved it to 2.0, a superset under which every 1.x document
stays valid.

## 2.1.0

Contract 2.1, a superset of 2.0: every 2.0 document stays valid with the
same meaning, and a document must declare 2.1 to use what this release
adds.

### Added

- **`key` on `$repeat`.** An expression of a non-optional `string`, `int`,
  or enum type, evaluated per element with the template's roots in scope,
  whose rendering replaces the element index in the instance's reference
  (`card[abc]`), so identity follows the element through reorderings; an
  emission from a keyed instance binds the element whose key matches at
  dispatch time. Keys are distinct within a materialization: a repeat is
  the `repeat` rule at build (`distinct key`) and a rejected mutation or
  context update at runtime. Vectors: `repeat-key-*`, `gate-repeat-key-*`,
  `dispatch-set-rejected-duplicate-key`,
  `context-update-rejected-duplicate-key`.
- **Typed failure payloads.** An action may declare a `failure` type; the
  handler fails with a value of that type, validated like a result, bound
  to the `failure` root inside that action's `onFailure`, rebinding at
  each nesting. A missing value is `null`, so it satisfies an optional
  declaration and violates a non-optional one; an action declaring none
  keeps the 2.0 rule. Vectors: `completion-failure-*`, `gate-failure-*`.
  The vocabulary meta-schema, the bindings generator (a nominal type per
  failure site, a doc note per action), and the vocabulary diff (adding
  is additive, removing or retyping breaking) follow.
- **Lifecycle bindings.** A top-level `on` section binds action lists to
  the `appear` and `disappear` signals the host delivers to a view;
  accepted signals dispatch in FIFO order with events, carry no payload,
  flip the view's appeared state, and emit `viewAppeared` /
  `viewDisappeared` interaction records; redundant and post-teardown
  signals are ignored silently. Vector steps `appear` and `disappear`.
  Vectors: `lifecycle-*`, `gate-lifecycle-*`.
- **Dispatch identity.** Every custom action delivered to a handler
  carries `dispatch`, its zero-based number among the view's dispatches
  in delivery order, and `dispatchId`, a string unique across every
  dispatch of every view in the process; `actionDispatched`,
  `completionSucceeded`, and `completionFailed` records carry the number,
  and completion records now carry the validated result or failure
  payload as their value. Vectors: `dispatch-numbering`,
  `interaction-completion-values`; `expect.dispatched` and
  `expect.interactions` entries may state `dispatch`. Uniqueness is
  engine-pinned (`dispatch-id-unique-across-views`).
- **Numeric functions**: `abs`, `min`, `max`, `floor`, `ceil`, `round`,
  specified to the bit (wrapping `abs`, leftmost-wins extrema with NaN
  propagation, ties away from zero, signed zeros preserved). Vectors:
  `expr-abs`, `expr-min-max`, `expr-rounding`, the `numeric` and
  `contract` families of the typing suite, and a second batch of the
  numeric suite (`gen-numeric-fn-*`) in 2.1 documents.
- **Array actions.** `$append` (`key`, `value`), `$remove` (`key`, `at`),
  and `$update` (`key`, `at`, `field`, `value`) change one element of an
  array-typed state key under exactly the rules of `$set` (visibility,
  dependent re-evaluation, the no-change rule, the three requirements and
  their rejected-mutation reports, ending the list on rejection); an index
  outside the array is a rejected mutation with `expected` `index in
  range`. Encoding rules are `action-encoding` violations naming `array
  state key`, `record element`, `declared field`, or the missing
  parameter. Vectors: `array-*`, `gate-array-*`.
- **Watch bindings.** A top-level `watch` section binds action lists to
  changes of a state key; the list runs as part of the mutation that
  changed the key, before the next action of the list that applied it,
  with no `event` root; mutations made inside a watch list never trigger
  a watch, so there is no cascade and no loop by rule; a rejection inside
  a watch ends the watch list only. An undeclared key is the new `watch`
  rule. Vectors: `watch-*`, `gate-watch-*`.
- **Host functions.** A vocabulary's `functions` section (or the builder)
  declares typed functions the host computes; expressions call them like
  built-ins, the gate types the calls as declared positions, and the
  engine's synchronous function handler answers at evaluation. Functions
  are pure over their arguments. A mismatched or thrown result is the
  `invalidFunctionResult` occurrence and the zero value of the return
  type. A document calling one on an engine without a handler is the
  `function-handler` rule. The vocabulary meta-schema and the vocabulary
  diff (adding additive, removing or retyping breaking) follow; the
  bindings generator does not yet emit function signatures. Vector config
  `functions.declare`, `functions.results`, `functionHandler`. Vectors:
  `function-*`, `gate-function-*`.
- **Document replacement.** `MilanoView.replace(document)` rebuilds the
  view's binding through the gate: state carries over where the
  declaration is unchanged and comes from the provider otherwise; a failed
  replacement leaves the view untouched; identity, dispatch numbering, and
  the appeared state persist; pending completions of the old document are
  dropped as `completionAfterReplace`; a `viewReplaced` record is
  contributed. Vector step `replace`. Vectors: `replace-*`. Engine-pinned:
  `replace-provider-failure-propagates`.
- **`contract-feature`** also covers: `$append`, `$remove`,
  `$update`, `watch`, and every declared function by name; a `functions`
  section in a vocabulary declaring `milano` below 2.1 is the
  `InvalidVocabulary` form.

### Changed

- **`tools/generate_bindings.py` wraps what would overflow**: doc comments
  at 100 columns, and the declarations that render long (a TypeScript union
  arm or decode case, a record accessor in any language, a Kotlin factory
  signature or map entry, a Swift computed property). An action declaring a
  record or a long enum used to render a line past the limits the generated
  files are linted against downstream, and the Kotlin now satisfies
  ktlint's indent and function-signature rules as well. The goldens under
  `tools/testdata/` are regenerated; nothing but formatting moved.

- **Built-in functions moved into the `$` namespace.** Every function of
  the expression language is now called as `$name`: `$str`, `$int`,
  `$double`, `$concat`, `$length`, `$isEmpty`, `$contains`, `$startsWith`,
  `$endsWith`, `$trim`, `$if`, `$abs`, `$min`, `$max`, `$floor`, `$ceil`,
  `$round`. A bare name in call position is a host function the surface
  declares, and the two namespaces never fall back to one another: a
  vocabulary may declare `round` or `concat` and get its own function
  beside the contract's, which is why the rule refusing a built-in's name
  is gone. It also means a later minor can add a built-in without
  invalidating a vocabulary that already declares the name. The grammar
  gains `builtin = "$" , identifier`; a `$` name the contract does not
  define, and a built-in's name outside call position, are the
  `expression` violation. The `contract-feature` detail for the numeric
  functions carries the sigil (`$abs`). Vectors: `function-named-like-a-builtin`,
  `gate-unknown-builtin-function`, `gate-builtin-without-arguments`,
  `gate-host-function-not-declared`, and every expression in the suite.

- **The scope is document-driven UI, not two surfaces.** Foundations no
  longer names banners, interstitials, and forms as the contract's
  targets or as the rule deciding inclusion; a mechanic enters the
  contract by need, under a version, with vectors. The banner and the
  form remain the worked examples.
- **Features are gated by the declared version.** A document is processed
  under the rules of the `major.minor` it declares; using a feature a
  later minor introduced is a `SchemaViolation` under the new rule
  `contract-feature` (`expected` the version that introduced it, `found`
  the feature's name: `key`, `on`, `failure`, or a function). A
  vocabulary declaring `milano` below 2.1 may not declare `failure`
  (`InvalidVocabulary`, rule `contract-feature`). Vectors:
  `gate-*-in-2-0-document`, `gen-typing-contract-*`, the
  `contract-feature` injector of the order suite.
- **Runtimes declare 1.0 and 2.1.** `UnsupportedVersion.supported` reads
  `["1.0", "2.1"]`; a 2.2 document is refused. The examples vocabulary
  declares `milano` 2.1.0, gives `submitContact` a failure type, which
  the contact form binds, and declares three host functions
  (`formatMoney`, `shout`, `parseInt`) that its vectors call.
- `event-binding` also covers an unknown lifecycle signal name (no node,
  `expected` `lifecycle event`); `repeat` gains the `key expression`,
  `key type`, and `distinct key` requirements; `invalidEmission` may find
  `key K`; `rejectedMutation` and `rejectedContextUpdate` may expect
  `distinct key`; `invalidCompletion` may expect the declared failure
  type.
- Clarified that an enum's declaration order, while never part of its
  identity, is what the zero value reads, so a runtime keeps that order
  beside the member set: a representation storing an unordered set alone
  cannot answer for the zero. No behaviour changes; this is what every
  engine already had to do.
- **`reference_check.synthesized_values` had no enum branch**, so an
  enum-declared state or context key synthesized to an empty record, a
  value the gate would refuse. It now returns `zero_value` per key, which
  is the same rule the contract uses for an invalid function result:
  one definition of a type's zero, not two.
- **Lookups: `record[key]`.** A record field chosen by an enum, so a code
  becomes a label without a chain of comparisons. The enum's members and
  the record's fields must be the same set, which makes the lookup total
  and its coverage exhaustive: a member added later leaves the record not
  covering it, and the gate refuses the document instead of the view
  showing the wrong label. The key must be an enum, every field must
  share one type, and the grammar's postfix gains `"[" expression "]"`.
  Seven vectors; the feature is spelled `[]` in a `contract-feature`
  report.
- **The `$switch` construct.** A third construct beside `$repeat` and
  `$if`, transparent the same way, keyed on an enum: `cases` names the
  nodes each member materializes, `default` covers the rest. **Every
  member must be covered**, by a case or a default, which is its reason
  to exist over nested `$if`s: a member added to the enum fails the build
  naming the one missed. Eleven vectors, rule `switch`.
- Two step vectors, `conditional-emission-from-a-branch` and
  `switch-emission-from-a-branch`: a node inside a branch dispatches like
  any other. Every engine walked only `children` to index its bindings, so
  all three dropped the emission; the vectors are what say they must not.
- **The `$if` construct.** A second construct node type beside `$repeat`,
  and transparent the same way: `condition` chooses between `then` and
  `else`, and the chosen branch's nodes take the construct's place in the
  parent. It is the tree-level counterpart of the `$if` function and the
  `$when` action, and the three do not collide because node types, action
  names, and function names are separate namespaces. Both branches are
  validated whichever one a build takes, so a condition flipping at
  runtime never reveals a document the gate has not seen, and ids stay
  unique across both; only the taken branch is resolved, so the other
  costs nothing in reports or against the node count. It carries no
  `properties`, `on`, or `id`, is never the root, and a node in a branch
  is pathed `root/children[2]/then[0]`, so a report says which branch it
  came from. Eighteen vectors, rule `conditional`.
- **Five string functions**, in the contract's `$` namespace like the
  rest: `$substring` (both indices clamped to the string, so no index is
  out of range), `$indexOf` (`-1` when absent), `$replace` (every
  non-overlapping occurrence), `$split` (always at least one element) and
  `$join` (the only fold in the language). Total like the numeric ones:
  none of them reports. Two guards keep every result bounded by its
  inputs, an empty needle in `$replace` and an empty separator in
  `$split`, each returning its subject. Indices count Unicode scalars, as
  `$length` does. Gated like the other 2.1 functions: a 2.0 document
  calling one fails with `contract-feature`.
- **A generated string suite**, `conformance/generated-string/`: 220
  vectors composed from subjects and needles chosen for their edges,
  empty strings, separators at the ends, adjacent separators, needles
  that overlap themselves, indices outside the string, and text outside
  the Basic Multilingual Plane where a scalar count and a UTF-16 code
  unit count disagree. Seeded and deterministic, like the numeric
  generator, with the reference checker as the oracle. Forty further
  named vectors in `conformance/examples/` pin each documented rule on
  its own.
- The `examples` vocabulary is at 1.1.0: three components (`Row`, `Card`
  with a `tap` event, `Icon` with an enum `name`) and two actions
  (`navigate` with an enum `screen`, `logEvent`) were added for the quick
  actions example. Additive only, so every existing vector and every
  document declaring `min` 1.0.0 is unaffected.
- A fourth worked example, **quick actions**: a keyed `$repeat` of tiles
  whose tap records the tapped element's position through `<as>_index` and
  then navigates. It shows enums declared in `state` satisfying an enum
  property, and why an instance's reference carries the key rather than
  the index once a `$repeat` is keyed. No contract change: every rule it
  demonstrates was already in 2.1.

### Fixed

- **The reference checker's node count and tree depth walked only
  `children`**, so a document whose nodes sat inside `$if` branches or
  `$switch` cases measured smaller for the oracle than for every engine: a
  document 53 nodes over the limit built for the checker and failed with
  `LimitExceeded` on all three runtimes. The walk now counts every branch,
  which is what the engines always did, and three vectors pin it at
  configured limits. The document model spec said the opposite in passing
  ("only what is materialized counts"); it now separates the two checks
  that share `maxNodeCount`: the document walk sees every branch, as it
  validates every branch, and the materialized count sees only the branch
  a build took.
- **The reference checker did not validate type descriptors.** Any string
  was accepted as a scalar type name, `string??` was accepted outright, an
  empty or duplicated `enum` passed, and `{}` or a number crashed the tool
  with a Python traceback. Malformed descriptors now raise the section's
  own violation with `expected` `type descriptor`, matching what every
  engine already produced, and five vectors pin it.
- **Declarations were visited in document order by the checker**, though
  the validation rules require lexicographic key order for every object's
  members. Each declaration is now checked whole (key, then descriptor) in
  key order.
- **The suite lint did not walk construct branches**, so a vector whose
  step emitted from a node inside an `$if` or `$switch` was reported as
  emitting from a node that does not exist.
- **Error vectors under-asserted.** Eighteen vectors named a rule without
  the detail fields the rule tables promise, which left `identifier`,
  `enum member`, `no children`, `declared event` and others unpinned; they
  now carry them. Tightening them surfaced two engine defects, fixed in
  the SDK release alongside this one: a non-identifier declaration key was
  reported as a bad `type descriptor`, and a string that is not a member of
  a declared enum was reported as an `enum`/`string` type mismatch rather
  than naming the rejected string.
- Vectors for `$startsWith` and `$endsWith`, which had no conformance
  coverage at all, including the literal scalar comparison the expression
  spec requires (a combining sequence is not a prefix of its precomposed
  form). Vectors for the nine `$if` and `$switch` encoding details that
  had none: `else branch`, `no on`, `not the root`, `no properties`,
  `declared key`, `subject expression`, `enum subject`, `default branch`.
- **The suite spec said four suites ship**; five do, and
  `generated-string` was undocumented.
- **Foundations' scope table described `$repeat` but not `$if` or
  `$switch`**; structural choice is now a row of its own.
- The two `InvalidVocabulary` statements no vector can express (creation
  validates the artifact; a contract version the engine does not implement
  is rejected) are now in `conformance/engine-pinned.json`, so every
  runtime's test for them is checked to exist rather than assumed.

## 2.0.0

### Added

- **The `$repeat` construct.** A node of type `$repeat` instantiates its
  template once per element of an array expression, binding the element
  and its index by name (`as`, `<as>_index`); the instances replace the
  construct in the parent's children, referenced by template reference
  plus index (`card[2]`). Its rules are the `repeat` rule; the node count
  limit is measured on the materialized tree, at build and at runtime,
  where a growing update is rejected whole. 2.x documents only. Vectors:
  `repeat-*`, `gate-repeat-*`, `dispatch-set-rejected-node-count`. The
  document schema and its generator admit the construct.

### Changed

- **Contract 2.0, a superset of 1.0.** A runtime declares, per major, the
  highest minor it implements (1.0 and 2.0 today); a document above that
  is `UnsupportedVersion` naming the declared version and the supported
  ranges as `major.minor` strings, where the detail listed bare majors.
  The patch never matters. Every 1.x document stays valid with the same
  meaning. The handwritten suite, the examples, and the vocabulary
  artifact declare 2.0.0; the generated suites keep 1.0.0 and pin its
  acceptance. Vectors: `gate-version-*`.
- **Limit rejections name the limit.** A `rejectedMutation` or
  `rejectedContextUpdate` past a limit carries the limit name as
  `expected` (`maxValueSize`, `maxNodeCount`) and the measured value as
  `found`. Vectors: `dispatch-set-rejected-value-size`,
  `context-update-rejected-value-size`.

## 1.3.1

### Clarified

- **Object members are visited in lexicographic key order.** JSON defines
  no order for them, and the Swift engine's parser keeps none, so which
  defect a multi-defect document reported first was random there and
  serializer-dependent everywhere. Document order still applies to
  arrays. Vector: `gate-order-object-members-lexicographic`; the order
  suite regenerated under the rule.

## 1.3.0

### Clarified

- **What a release number means.** README and the home page distinguish
  the repository release (this 1.3.0) from the contract version documents
  declare (still 1.0), and say which moves when.
- **The detail every error rule and every occurrence kind carries** is
  tabulated in the document model and runtime API specs; the glossary
  defines gate, surface, occurrence, user interaction, dispatch,
  dispatcher, and resolution.
- **The vocabulary version is exposed on the engine**, not carried in
  reports, as the vocabulary schema spec claimed.
- **A required state value the provider omits is null**, reported as the
  declared type against `null`; the checker said "missing key". Vector:
  `gate-state-value-missing`.
- **The loading view belongs to the hosting container**, not the builder;
  the builder carries gate concerns only, so it has one shape on every
  toolkit. Foundations said otherwise.
- **An optional operand compares only to `null`.** The operator table now
  says what the reference gate always enforced: `sOpt == 'a'` and
  `sOpt == s` are rejected; resolve with `??` first. The typing suite
  now generates those pairs.
- **`metadata` is a JSON object**; any other shape is `MalformedDocument`.
  Vector: `gate-metadata-not-object`.
- **The schemas are open wherever the contract may grow** (top level,
  envelope, `vocabulary`, type descriptors), matching the tolerance rule;
  they closed `vocabulary` and descriptors before. `$expr` stays closed.
- **Values are bounded at runtime.** Foundations promised that a context
  update or state mutation past a runtime limit is rejected whole; no
  limit said what that meant. A value size limit (default 65,536: one per
  scalar, one per Unicode scalar of a string, one plus the contents for
  an array or record) now applies wherever a value enters state or
  context: `LimitExceeded` at the gate, a rejected context update at
  runtime, and for `$set` a new `rejectedMutation` occurrence that ends
  the action list. Vectors: `gate-limit-value-size-*`,
  `context-update-rejected-value-size`, `dispatch-set-rejected-value-size`.
- **`if` branches agree on optionality.** Both branches type to the same
  T; resolve an optional with `??` first. The Swift and Kotlin rule, now
  everywhere. Vectors: `gate-expression-if-optional-branch-mismatch`,
  `expr-if-optional-branch-resolved`.
- **An `int` expression is accepted where a `double` is declared**, as an
  `int` literal always was. Vector: `expr-int-expression-in-double-slot`.
- **The specifications name all three runtimes**, including the
  TypeScript engine with its React binding, and say what "main thread"
  means on an event loop. Prose only.
- **Loosening a property from required to optional is breaking**, as
  `vocabulary_diff.py` already reported. Optionality is part of the type.
- **Only dependent expressions re-evaluate**: those reading a key whose
  value changed. A `$set` or context update that changes no value
  re-evaluates nothing. Vector:
  `dispatch-set-independent-expression-not-reevaluated`.
- **An empty node `id` is a `MalformedDocument`.** Vector: `gate-id-empty`.
- **Occurrences carry detail**: optional `name`, `expected`, and `found`
  fields, accepted by the vector schema and stated by the existing
  occurrence vectors.
- Identifiers are ASCII, in so many words.
- Editorial: a `character` definition in the expression grammar, the
  `userInteraction` node method in the runtime API table, corrected
  cross-references, and the desktop sample named where the samples are.

### Added

- **A validation-order suite**, `conformance/generated-order`, from
  `tools/generate_order_vectors.py`: every pair of gate violations in one
  document, the reference gate deciding which error wins.
- Vectors `context-update-after-teardown` and
  `interaction-view-built-without-metadata`, pinning two promises the
  runtime API spec made without a vector.
- **`config.stateDataProvider` and `config.actionHandler` in vectors**, so
  the builder-level rules are vectors: `gate-state-declaration-no-provider`,
  `gate-action-handler-missing`.
- **An engine-pinned registry**, `conformance/engine-pinned.json`, for the
  statements no vector can express (teardown during an action list,
  deallocation as teardown, the megabyte-scale default limits); every
  applicable engine carries a test naming the id.
- **Unknown-key warnings** in `reference_check.py --document`, for typos
  the tolerance rule makes silent, and `gate-unknown-keys-ignored`, the
  vector pinning that the gate ignores them everywhere the contract may
  grow.
- **`config.limits` in vectors**: engine limit overrides by name, so a
  limit is pinned at a small value. `gate-limit-node-count` and
  `gate-limit-document-size` use it; those two limits had no vector.
- **Typed records in the generated bindings**: one wrapper type per record
  declaration site in all three languages, with typed field accessors, a
  memberwise constructor, and nesting through fields and array elements.
- **A typing-rule suite**, `conformance/generated-typing`, generated
  exhaustively from a small operand grammar by
  `tools/generate_typing_vectors.py`, with the reference gate deciding
  each pair.
- Vectors `expr-double-modulo-non-finite`, `gate-id-empty`, and
  `gate-state-key-non-ascii`.

### Fixed

- `reference_check.py`: `inf % x` crashed instead of answering `nan`;
  a non-optional compared to `null` was accepted; Unicode letters were
  accepted in identifiers. `generate_numeric_vectors.py` no longer
  swallows checker crashes.
- `vocabulary_diff.py` ignored completion results; removing or retyping
  one is now BREAKING, adding one ADDITIVE.
- `examples.md` lists all nine component types.

## 1.2.0

### Clarified

- **Teardown during an action list.** A teardown observed while an action
  list is executing does not interrupt it: the list runs to completion,
  and only work arriving afterwards is refused. Every engine already
  behaved this way; the rule was never written down. Not expressible as a
  vector (steps run between events, never inside one), so it is pinned by
  a test in each engine instead.

### Added

- **A TypeScript emitter** in `tools/generate_bindings.py`, alongside the
  Swift and Kotlin ones.
- **Tests for every tool**, run in CI by discovery, so a new
  `tools/test_*.py` needs no workflow change. The bindings generator's
  output is compared against golden files and checked for properties the
  goldens cannot express; the document-schema generator is checked against
  a real validator, including the two places it is deliberately stricter
  than the gate; `reference_check.py` is asserted against the prose rather
  than against itself, since as the suite's oracle it has nothing else to
  disagree with; `validate_suite.py` is driven against deliberately broken
  repositories, because a gate that has stopped detecting anything still
  exits zero; and `generate_numeric_vectors.py` is regenerated into a temp
  directory and compared byte for byte with the 150 committed vectors.

### Fixed

- **`generate_bindings.py` escapes reserved words.** A vocabulary
  declaring a property called `class` or an action called `switch`
  produced Swift and Kotlin that could not compile. Declarations are now
  escaped in each language's own way; the wire name is untouched, and
  TypeScript needs no escaping because reserved words are legal as
  property names there.
- **`vocabulary_diff.py` no longer reports reordered enum members as a
  change.** Enum identity is the member set, but the tool compared
  serialized descriptors, so reordering members produced a spurious
  `ADDITIVE` verdict with an empty "gained" list and forced a needless
  minor bump.

## 1.0.0

The first stable contract: foundations, document model, vocabulary schema,
expression language, state and actions, runtime API, and the conformance
suite that defines what correct means.
