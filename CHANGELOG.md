# Changelog

Changes to the specification, its conformance suite, and its tools.

The **contract version** is what documents and vocabularies declare
(`"milano": "1.0.0"`), and it moves only when the contract itself does.
Clarifications that describe behaviour every engine already implements do
not move it; neither do tool or suite changes. Anything that changes what
a conformant engine must do is a contract change, and comes with vectors.

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
- **Tests for the tools**, run in CI: `generate_bindings.py`,
  `vocabulary_diff.py`, and `generate_document_schema.py`. The bindings
  generator's output is compared against golden files and checked for
  properties the goldens cannot express; the document-schema generator is
  checked against a real validator, including the two places it is
  deliberately stricter than the gate.

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
