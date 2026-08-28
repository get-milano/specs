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
The contract has been at 1.0.0 since the first release.

## Unreleased

### Clarified

- **`if` branches agree on optionality.** Both branches type-check to
  exactly the same T: a `T?` branch beside a `T` branch is rejected, and
  the optional is resolved with `??` first. The Swift and Kotlin engines
  always behaved this way; the TypeScript engine and the reference
  checker widened the result to `T?` instead, so the same document built
  on one platform and failed on another. Pinned by
  `gate-expression-if-optional-branch-mismatch` and
  `expr-if-optional-branch-resolved`.
- **An `int` expression is accepted where a `double` is declared** and
  promoted at evaluation, exactly as an `int` literal or data value is.
  Every engine did this; the prose only promised it for values and the
  reference checker refused it. Pinned by
  `expr-int-expression-in-double-slot`.

### Added

- `expr-double-modulo-non-finite`: double `%` with an infinite or zero
  operand, per IEEE 754.
- `gate-state-key-non-ascii`: declaration keys follow the ASCII identifier
  grammar; a Unicode letter is not a letter here.

### Fixed

- **`reference_check.py` crashed on `inf % x`** (`math.fmod` raises on an
  infinite dividend) where every engine answers `nan`, and
  `generate_numeric_vectors.py` swallowed the crash with a bare `except`,
  so no generated vector could ever pin the case. The remainder is now
  computed per IEEE 754, and the generator skips only type mismatches.
- **`reference_check.py` accepted Unicode letters in identifiers**
  (`str.isalpha`) where the schemas and every engine are ASCII only, so
  the `--document` CLI validated state and context keys the engines
  reject.

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
