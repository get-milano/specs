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
