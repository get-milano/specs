# Contributing

- Every spec follows the three-status process on the [home page](index.md): Beta, Review, Stable.
- Normative changes ship together with the conformance vectors that pin them; a spec change without its vectors is incomplete.
- Documents in this repository never use the em dash character.
- Vectors live in `conformance/`, one directory per vocabulary; every file must remain valid JSON and pass the suite in every engine (see [get-milano/sdk](https://github.com/get-milano/sdk)).
- CI runs `tools/validate_suite.py` (schema validation, requires `pip install jsonschema`), `tools/reference_check.py` (semantic check of step-free vectors, no dependencies), and `tools/run_tests.py` (every tool's tests, by discovery). Run them locally before pushing, or enable the bundled hook once with `git config core.hooksPath .githooks`.
