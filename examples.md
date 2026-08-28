---
title: "Examples"
nav_order: 8
---

# Worked Examples

The two v1.0 target capabilities, written end to end: a shared vocabulary, two documents, and the behavior each must produce. Both live as executable vectors in `conformance/`, in the format of the [conformance suite spec](05-conformance-suite.html). Together they exercise every v1.0 mechanic: context, expressions, state, events, built-in and custom actions, consent gating, and async completion.

## Recommended integration architecture

Non-normative, but strongly recommended and followed by the sample apps: keep the design system pure, and give Milano exactly one doorway into it.

- **Design system** (`DesignSystem/`, `designsystem/`): plain UI components taking typed models (a banner model with layout, heights, and alignment; a button model with a label, an enabled flag, and a tap closure). Zero Milano imports: every component is previewable and unit-testable on its own, and reusable outside Milano entirely.
- **Milano bridge** (`MilanoBridge/`, `milanobridge/`): the only UI-layer code that imports Milano. For each component, an initializer that builds the model from a MilanoNode (properties read once, events wired into the model's closures), and the renderer that registers it. One obvious file per component; the whole Milano surface of the design system is auditable at a glance.
- **Environment**: engine setup, builders, the action funnel, the observer. Screens depend on this service, never on engine internals.

The result: Milano never leaks into the components, the components never learn about documents, and replacing either side leaves the other untouched.

## The vocabulary

A minimal consumer vocabulary, `examples 1.0.0`, with nine component types and two custom actions:

| Component | Properties | Events | Children |
|---|---|---|---|
| `Banner` | `backgroundImageUrl: string` | | yes |
| `Column` | | | yes |
| `Text` | `text: string`, `visible: bool?` | | |
| `Button` | `label: string`, `enabled: bool` | `tap` (no payload) | |
| `TextField` | `label: string`, `value: string` | `change: string` | |
| `NumberField` | `label: string`, `value: double` | `change: double` | |
| `Checkbox` | `label: string`, `checked: bool` | `change: bool` | |
| `Badge` | `label: string`, `tone: enum(info, warning, danger)` | `select: enum(info, warning, danger)` | |
| `Meta` | `key: string`; strict, so an undeclared property is rejected at the gate | | |

| Action | Declared | Parameters |
|---|---|---|
| `openUrl` | Vocabulary (global) | `url: string` |
| `submitContact` | Vocabulary (global) | `name: string`, `surname: string`, `email: string`, `phone: string?` |

What these components look like is entirely the consumer's business: Milano only guarantees their properties arrive resolved and typed, and their declared events dispatch.

The artifact lives once at `conformance/examples/vocabulary.json`, beside its vectors per the suite layout: nothing references it by path, mirroring the runtime, where a document never names its vocabulary. It validates against the official meta-schema `schemas/vocabulary.schema.json`.

## The banner

A background image, a personalized title, a subtitle, and a call-to-action button that asks the host to open a URL.

```json
{
  "version": "1.0.0",
  "context": { "userName": "string" },
  "root": {
    "type": "Banner",
    "id": "banner",
    "properties": { "backgroundImageUrl": "https://cdn.example.com/promo.jpg" },
    "children": [
      {
        "type": "Text",
        "id": "title",
        "properties": { "text": { "$expr": "concat('Hello, ', context.userName)" } }
      },
      {
        "type": "Text",
        "id": "subtitle",
        "properties": { "text": "A summer of savings starts today." }
      },
      {
        "type": "Button",
        "id": "cta",
        "properties": { "label": "Learn more", "enabled": true },
        "on": {
          "tap": [ { "action": "openUrl", "url": "https://example.com/promo" } ]
        }
      }
    ]
  }
}
```

What it demonstrates:

- **Structure without data**: the document declares that it reads `context.userName`; the host injects the value (`"Ada"`), and the title resolves to `Hello, Ada`. The same cached document greets every user.
- **The action boundary**: tapping the button dispatches `openUrl` with its captured `url` parameter to the host's action handler. Milano does not open URLs; the host does.
- Vector: `conformance/examples/banner-open-url.json` expects the resolved tree, the dispatched action, and zero occurrences.

## The contact form

Name, surname, email, optional phone, and a consent checkbox that gates submission. All field composition is document-defined: adding a field is a document change, not an app release.

```json
{
  "version": "1.0.0",
  "state": {
    "name": "string",
    "surname": "string",
    "email": "string",
    "phone": "string?",
    "consent": "bool",
    "submitted": "bool"
  },
  "root": {
    "type": "Column",
    "id": "form",
    "children": [
      {
        "type": "TextField",
        "id": "name",
        "properties": { "label": "Name", "value": { "$expr": "state.name" } },
        "on": { "change": [ { "action": "$set", "key": "name", "value": { "$expr": "event" } } ] }
      },
      {
        "type": "TextField",
        "id": "surname",
        "properties": { "label": "Surname", "value": { "$expr": "state.surname" } },
        "on": { "change": [ { "action": "$set", "key": "surname", "value": { "$expr": "event" } } ] }
      },
      {
        "type": "TextField",
        "id": "email",
        "properties": { "label": "Email", "value": { "$expr": "state.email" } },
        "on": { "change": [ { "action": "$set", "key": "email", "value": { "$expr": "event" } } ] }
      },
      {
        "type": "TextField",
        "id": "phone",
        "properties": { "label": "Phone (optional)", "value": { "$expr": "state.phone ?? ''" } },
        "on": { "change": [ { "action": "$set", "key": "phone", "value": { "$expr": "event" } } ] }
      },
      {
        "type": "Checkbox",
        "id": "consent",
        "properties": { "label": "I agree to be contacted", "checked": { "$expr": "state.consent" } },
        "on": { "change": [ { "action": "$set", "key": "consent", "value": { "$expr": "event" } } ] }
      },
      {
        "type": "Button",
        "id": "submit",
        "properties": {
          "label": "Send",
          "enabled": { "$expr": "state.consent && !isEmpty(trim(state.name)) && !isEmpty(trim(state.surname)) && !isEmpty(trim(state.email)) && !state.submitted" }
        },
        "on": {
          "tap": [
            {
              "action": "$when",
              "condition": { "$expr": "state.consent && !isEmpty(trim(state.name)) && !isEmpty(trim(state.surname)) && !isEmpty(trim(state.email)) && !state.submitted" },
              "then": [
                {
                  "action": "submitContact",
                  "name": { "$expr": "trim(state.name)" },
                  "surname": { "$expr": "trim(state.surname)" },
                  "email": { "$expr": "trim(state.email)" },
                  "phone": { "$expr": "state.phone" },
                  "onSuccess": [ { "action": "$set", "key": "submitted", "value": true } ]
                }
              ]
            }
          ]
        }
      },
      {
        "type": "Text",
        "id": "thanks",
        "properties": { "text": { "$expr": "if(state.submitted, 'Thanks! We will be in touch.', '')" } }
      }
    ]
  }
}
```

What it demonstrates:

- **State shape in the document, values from outside**: the state data provider supplies the initial values (empty strings, `null` phone, `false` flags), awaited during the asynchronous build.
- **The unidirectional loop**: each field renders `state.x` and its `change` event runs `$set` with the event payload. The renderer never writes state; the loop closes through dispatch.
- **Actions as capabilities**: `submitContact` is declared in the app's vocabulary; documents never declare actions, so nothing reaches a handler the app did not consciously grant. A surface can narrow the set (`allowActions`) or override a signature (builder `action(...)`) without touching the vocabulary; meaning stays with each surface's handler.
- **Consent gating, twice**: the `enabled` expression handles presentation (the consumer's Button decides what disabled looks like), and the `$when` guard handles semantics: a `tap` emitted while the condition is false dispatches nothing. The gate is in the document, not in renderer logic.
- **Async completion**: `submitContact` is delivered to the host's handler; the sequence does not wait. When the handler succeeds, `onSuccess` sets `submitted`, which disables the button and reveals the thank-you text through `if(...)`.
- **Optionality**: `phone` is `string?` end to end: `null` from the provider, displayed via `?? ''`, passed as `null` to the handler when never edited.
- Vector: `conformance/examples/form-contact-consent.json` walks the full interaction: fill fields, tap while unconsented (nothing dispatches), consent, tap, complete with success; expects the final state store, the single dispatched action, and zero occurrences.
