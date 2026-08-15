<img src="assets/img/get-milano.png" alt="Milano logo" width="112" align="right">

# Milano SDK Specifications

Canonical repository: `github.com/get-milano/specs`. The engines and sample apps live in `github.com/get-milano/sdk`.

Milano is a client-only, design-system-agnostic Document-Driven UI (DDUI) framework for SwiftUI and Compose. Document-driven rather than server-driven: Milano is agnostic of how the document is obtained. Milano targets UI toolkits, not operating systems: it is usable wherever SwiftUI runs (iPhone, iPad, macOS, watchOS) and wherever Compose runs (Android, desktop). The first sample apps target iOS and Android.

Milano consumes UI documents and defines the mechanics of document-driven UI: the document model, its expression language, its state and action models, and the runtimes that materialize documents into native UI (SwiftUI, Compose). The consumer defines everything else: the component vocabulary and its visual rendering. Documents carry structure and declarations only, never data values.

Milano is not server-driven UI (it never talks to a server), not a SaaS (there is nothing hosted, nothing to sign up for), and not a design system (it draws nothing).

Version 0.1 targets two capabilities: banners and interstitials, and simple document-defined forms.

## Specifications

| # | Spec | Status |
|---|---|---|
| 00 | [Foundations](00-foundations.md) | Beta |
| 01 | [Document model](01-document-model.md) | Beta |
| 02 | [Vocabulary schema](02-vocabulary-schema.md) | Beta |
| 03 | [Expression language](03-expression-language.md) | Beta |
| 04 | [State & actions](04-state-and-actions.md) | Beta |
| 05 | [Conformance suite](05-conformance-suite.md) | Beta |
| 06 | [Runtime API](06-runtime-api.md) | Beta |

Worked examples for both v0.1 capabilities: [Examples](examples.md), with executable vectors in [`conformance/`](conformance/).

## Spec process

Every spec moves through three statuses:

1. **Beta**: the content is being shaped. Anything may change, without trace.
2. **Review**: the content is complete and precise. Changes require recording what changed and why in the spec's history.
3. **Stable**: the spec is normative. Runtimes and conformance vectors may rely on it; changes happen only through an amendment that bumps the contract version.

This repository also renders as a website via GitHub Pages (Jekyll, just-the-docs theme); `index.md` is the site's landing page.

## License

The specifications are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): share and adapt freely, with credit to Ezequiel Aceto and the Milano project. The Milano name and logo are trademarks of Ezequiel Aceto: use them to refer to this project, not to brand derivatives.
