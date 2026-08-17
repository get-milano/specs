---
title: Home
nav_order: 0
---

# Milano SDK Specifications

Milano is a client-only, design-system-agnostic Document-Driven UI (DDUI) framework for SwiftUI and Compose. Milano targets UI toolkits, not operating systems: it is usable wherever SwiftUI runs (iPhone, iPad, macOS, watchOS) and wherever Compose runs (Android, desktop). The first sample apps target iOS and Android.

Milano consumes **UI documents** and defines the **mechanics** of document-driven UI: the document model, its expression language, its state and action models, and the runtimes that materialize documents into native UI (SwiftUI, Compose). The consumer defines everything else: the component vocabulary and its visual rendering.

Milano is **not** server-driven UI (it never talks to a server), **not** a SaaS (there is nothing hosted, nothing to sign up for), and **not** a design system (it draws nothing).

Version 1.0 targets two capabilities: banners and interstitials, and simple document-defined forms. The same mechanics serve whole screens beyond those targets, such as user profile screens and intermediate screens like a catalog. Contract v1.0 is stable: the versioning and tolerance rules below are promises, relied on by the 1.0 SDK release, and changes ship as amendments that bump the contract version.

Try the contract in the browser: the [Milano Playground](https://get-milano.dev/playground/) validates vocabularies and documents against these schemas and the reference checker, live.

## Specifications

| # | Spec | Status |
|---|---|---|
| 00 | [Foundations](00-foundations.html) | Stable |
| 01 | [Document model](01-document-model.html) | Stable |
| 02 | [Vocabulary schema](02-vocabulary-schema.html) | Stable |
| 03 | [Expression language](03-expression-language.html) | Stable |
| 04 | [State & actions](04-state-and-actions.html) | Stable |
| 05 | [Conformance suite](05-conformance-suite.html) | Stable |
| 06 | [Runtime API](06-runtime-api.html) | Stable |

Worked examples for both v1.0 capabilities, with their conformance vectors: [Examples](examples.html).

## Spec process

Every spec moves through three statuses:

1. **Beta**: the content is being shaped. Anything may change, without trace.
2. **Review**: the content is complete and precise. Changes require recording what changed and why in the spec's history.
3. **Stable**: the spec is normative. Runtimes and conformance vectors may rely on it; changes happen only through an amendment that bumps the contract version.
