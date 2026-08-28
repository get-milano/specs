---
title: Home
nav_order: 0
---

# Milano SDK Specifications

Milano is a client-only, design-system-agnostic Document-Driven UI (DDUI) framework for SwiftUI, Compose, and React. Milano targets UI toolkits, not operating systems: it is usable wherever SwiftUI runs (iPhone, iPad, macOS, watchOS), wherever Compose runs (Android, desktop), and wherever React runs (the web, and React Native on iOS and Android). The sample apps target iOS, Android, desktop, and React Native.

Milano consumes **UI documents** and defines the **mechanics** of document-driven UI: the document model, its expression language, its state and action models, and the runtimes that materialize documents into native UI (SwiftUI, Compose, React). The consumer defines everything else: the component vocabulary and its visual rendering.

Milano is **not** server-driven UI (it never talks to a server), **not** a SaaS (there is nothing hosted, nothing to sign up for), and **not** a design system (it draws nothing).

The contract targets two capabilities: banners and interstitials, and simple document-defined forms. The same mechanics serve whole screens beyond those targets, such as user profile screens and intermediate screens like a catalog. Contract 2.0 is stable: the versioning and tolerance rules in [Foundations](00-foundations.html) are promises, a document declares the version it was written for, and a runtime rejects versions it does not implement.

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

Worked examples for both target capabilities, with their conformance vectors: [Examples](examples.html).

## Releases and the contract version

Two numbers move at different speeds. The **contract version** is what a document declares in `version` and a vocabulary in `milano`: it names the rules a document is written against, and it moves only when a document could observe the difference (a new construct, function, or field; a changed rule). The **repository release** (the tags of this repository, which the conformance suite and the SDK track) moves whenever the normative text, the schemas, the tools, or the suite change, including clarifications that pin behavior the engines already had. So repository releases 1.0.0 through 1.3.1 all shipped contract 1.0, and release 2.0.0 ships contract 2.0, a superset under which every 1.x document stays valid and means the same thing. Conformance is claimed against a repository release ("passes suite 1.3.0"); compatibility is declared against a contract version.

## Spec process

Every spec moves through three statuses:

1. **Beta**: the content is being shaped. Anything may change, without trace.
2. **Review**: the content is complete and precise. Changes require recording what changed and why in the spec's history.
3. **Stable**: the spec is normative. Runtimes and conformance vectors may rely on it; changes ship as repository releases, and the contract version bumps only when a document could observe the change (see above).
