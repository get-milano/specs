<img src="assets/img/get-milano.png" alt="Milano logo" width="112" align="right">

# Milano SDK Specifications

Canonical repository: `github.com/get-milano/specs`. The engines and sample apps live in `github.com/get-milano/sdk`.

Try the contract in the browser: the [Milano Playground](https://get-milano.dev/playground/) validates vocabularies and documents against these schemas and the reference checker, live.

Milano is a client-only, design-system-agnostic Document-Driven UI (DDUI) framework for SwiftUI, Compose, and React. Document-driven rather than server-driven: Milano is agnostic of how the document is obtained. Milano targets UI toolkits, not operating systems: it is usable wherever SwiftUI runs (iPhone, iPad, macOS, watchOS), wherever Compose runs (Android, desktop), and wherever React runs (the web, and React Native on iOS and Android). The sample apps target iOS, Android, desktop, and React Native.

Milano consumes UI documents and defines the mechanics of document-driven UI: the document model, its expression language, its state and action models, and the runtimes that materialize documents into native UI (SwiftUI, Compose, React). The consumer defines everything else: the component vocabulary and its visual rendering. Documents carry structure and declarations only, never data values.

Milano is not server-driven UI (it never talks to a server), not a SaaS (there is nothing hosted, nothing to sign up for), and not a design system (it draws nothing).

The contract serves document-driven UI of any kind: fragments embedded between native components (banners, quick actions, forms) and whole screens (profiles, catalogs, details, confirmation flows) are the same mechanics at different sizes. Contract 2.1 is stable: the versioning and tolerance rules in [Foundations](00-foundations.md) are promises, a document declares the version it was written for, and a runtime rejects versions it does not implement.

## Specifications

| # | Spec | Status |
|---|---|---|
| 00 | [Foundations](00-foundations.md) | Stable |
| 01 | [Document model](01-document-model.md) | Stable |
| 02 | [Vocabulary schema](02-vocabulary-schema.md) | Stable |
| 03 | [Expression language](03-expression-language.md) | Stable |
| 04 | [State & actions](04-state-and-actions.md) | Stable |
| 05 | [Conformance suite](05-conformance-suite.md) | Stable |
| 06 | [Runtime API](06-runtime-api.md) | Stable |

Worked examples written end to end, a banner, a shopping list, a quick actions strip, and a form: [Examples](examples.md), with executable vectors in [`conformance/`](conformance/).

## Releases and the contract version

Two numbers move at different speeds. The **contract version** is what a document declares in `version` and a vocabulary in `milano`: it names the rules a document is written against, and it moves only when a document could observe the difference (a new construct, function, or field; a changed rule). The **repository release** (the tags of this repository, which the conformance suite and the SDK track) moves whenever the normative text, the schemas, the tools, or the suite change, including clarifications that pin behavior the engines already had. So repository releases 1.0.0 through 1.3.1 all shipped contract 1.0, release 2.0.0 shipped contract 2.0, and release 2.1.0 ships contract 2.1; each is a superset of the one before, under which every earlier document stays valid and means the same thing. Conformance is claimed against a repository release ("passes suite 2.1.0"); compatibility is declared against a contract version.

## Spec process

Every spec moves through three statuses:

1. **Beta**: the content is being shaped. Anything may change, without trace.
2. **Review**: the content is complete and precise. Changes require recording what changed and why in the spec's history.
3. **Stable**: the spec is normative. Runtimes and conformance vectors may rely on it; changes ship as repository releases, and the contract version bumps only when a document could observe the change (see above).

This repository also renders as a website via GitHub Pages (Jekyll, just-the-docs theme); `index.md` is the site's landing page.

## License

The specifications are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): share and adapt freely, with credit to Ezequiel (Kimi) Aceto and the Milano project.
