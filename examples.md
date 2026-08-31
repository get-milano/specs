---
title: "Examples"
nav_order: 8
---

# Worked Examples

Four surfaces written end to end, a banner, a form, a list, and a strip of quick actions: a shared vocabulary, four documents, and the behavior each must produce. The banner and the form live as executable vectors in `conformance/`, in the format of the [conformance suite spec](05-conformance-suite.html), and every mechanic the other two use is pinned by vectors of its own. Together they exercise the contract: context, expressions, state, events, built-in and custom actions, consent gating, async completion with a typed result and a typed failure payload, keyed lists edited in place, reactions to state, lifecycle signals, and functions the host computes. They illustrate the mechanics, not the boundary of what the mechanics serve.

## Recommended integration architecture

Non-normative, but strongly recommended and followed by the sample apps: keep the design system pure, and give Milano exactly one doorway into it.

- **Design system** (`DesignSystem/`, `designsystem/`): plain UI components taking typed models (a banner model with layout, heights, and alignment; a button model with a label, an enabled flag, and a tap closure). Zero Milano imports: every component is previewable and unit-testable on its own, and reusable outside Milano entirely.
- **Milano bridge** (`MilanoBridge/`, `milanobridge/`): the only UI-layer code that imports Milano. For each component, an initializer that builds the model from a MilanoNode (properties read once, events wired into the model's closures), and the renderer that registers it. One obvious file per component; the whole Milano surface of the design system is auditable at a glance.
- **Environment**: engine setup, builders, the action funnel, the observer. Screens depend on this service, never on engine internals.

The result: Milano never leaks into the components, the components never learn about documents, and replacing either side leaves the other untouched.

## The vocabulary

A minimal consumer vocabulary, `examples`, with twelve component types, four custom actions, and the functions the app computes:

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
| `Row` | `spacing: int?` | | yes |
| `Card` | `cornerRadius: int?`, `accessibilityLabel: string?` | `tap` (no payload) | yes |
| `Icon` | `name: enum(person, list, search, edit, settings, help)` | | |

| Action | Declared | Parameters |
|---|---|---|
| `openUrl` | Vocabulary (global) | `url: string` |
| `submitContact` | Vocabulary (global) | `name: string`, `surname: string`, `email: string`, `phone: string?`; fails with `enum(invalid, unavailable)` |
| `navigate` | Vocabulary (global) | `screen: enum(profile, catalog, settings, help)` |
| `logEvent` | Vocabulary (global) | `event: string`, `surface: string`, `position: int` |

| Function | Arguments | Returns |
|---|---|---|
| `formatMoney` | `int`, `string` | `string` |
| `shout` | `string` | `string` |
| `parseInt` | `string` | `int?` |
| `scale` | `double`, `int` | `double` |
| `tone` | `enum(info, warning, danger)` | `enum(info, warning, danger)` |
| `round` | `double`, `int` | `string` |

Functions are declared like actions and computed by the app, not by Milano (vocabulary schema spec, Function declarations). `round` is declared deliberately: the contract's own `$round` is a different function in a different namespace, and neither shadows the other.

What these components look like is entirely the consumer's business: Milano only guarantees their properties arrive resolved and typed, and their declared events dispatch.

The artifact lives once at `conformance/examples/vocabulary.json`, beside its vectors per the suite layout: nothing references it by path, mirroring the runtime, where a document never names its vocabulary. It validates against the official meta-schema `schemas/vocabulary.schema.json`.

## The banner

A background image, a personalized title, a subtitle, and a call-to-action button that asks the host to open a URL.

```json
{
  "version": "2.0.0",
  "context": { "userName": "string" },
  "root": {
    "type": "Banner",
    "id": "banner",
    "properties": { "backgroundImageUrl": "https://cdn.example.com/promo.jpg" },
    "children": [
      {
        "type": "Text",
        "id": "title",
        "properties": { "text": { "$expr": "$concat('Hello, ', context.userName)" } }
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

## The shopping list

A list the document owns and edits in place: one `$repeat` keyed on each
item, the three array actions behind its buttons, a `watch` that clears the
draft whenever the list changes, a lifecycle binding, and a price formatted
by a function the app computes.

```json
{
  "version": "2.1.0",
  "vocabulary": { "name": "examples", "min": "1.0.0" },
  "state": {
    "items": { "array": { "record": { "id": "string", "name": "string", "cents": "int", "done": "bool" } } },
    "draft": "string",
    "seen": "bool"
  },
  "root": {
    "type": "Column",
    "id": "list",
    "children": [
      {
        "type": "Text",
        "id": "heading",
        "properties": { "text": { "$expr": "$concat('Basket: ', $str($length(state.items)), ' items')" } }
      },
      {
        "type": "TextField",
        "id": "draft",
        "properties": { "label": "Add an item", "value": { "$expr": "state.draft" } },
        "on": { "change": [ { "action": "$set", "key": "draft", "value": { "$expr": "event" } } ] }
      },
      {
        "type": "Button",
        "id": "add",
        "properties": { "label": "Add", "enabled": { "$expr": "!$isEmpty($trim(state.draft))" } },
        "on": {
          "tap": [
            {
              "action": "$append",
              "key": "items",
              "value": { "id": "", "name": "", "cents": 250, "done": false }
            },
            {
              "action": "$update",
              "key": "items",
              "at": { "$expr": "$length(state.items) - 1" },
              "field": "id",
              "value": { "$expr": "$trim(state.draft)" }
            },
            {
              "action": "$update",
              "key": "items",
              "at": { "$expr": "$length(state.items) - 1" },
              "field": "name",
              "value": { "$expr": "$trim(state.draft)" }
            }
          ]
        }
      },
      {
        "type": "$repeat",
        "id": "rows",
        "items": { "$expr": "state.items" },
        "as": "item",
        "key": { "$expr": "item.id" },
        "children": [
          {
            "type": "Checkbox",
            "id": "done",
            "properties": {
              "label": { "$expr": "$concat(item.name, ': ', formatMoney(item.cents, 'EUR'))" },
              "checked": { "$expr": "item.done" }
            },
            "on": {
              "change": [
                {
                  "action": "$update",
                  "key": "items",
                  "at": { "$expr": "item_index" },
                  "field": "done",
                  "value": { "$expr": "event" }
                }
              ]
            }
          },
          {
            "type": "Button",
            "id": "remove",
            "properties": { "label": "Remove", "enabled": true },
            "on": {
              "tap": [ { "action": "$remove", "key": "items", "at": { "$expr": "item_index" } } ]
            }
          }
        ]
      }
    ]
  },
  "on": { "appear": [ { "action": "$set", "key": "seen", "value": true } ] },
  "watch": { "items": [ { "action": "$set", "key": "draft", "value": "" } ] }
}
```

What it demonstrates:

- **Keyed instances** (contract 2.1): `key` is `item.id`, so a row's reference is `done[milk]` rather than `done[0]`. It keeps that identity when the list is reordered or an earlier row is removed, which is what makes an emission from it, and every report about it, still mean the same row.
- **Editing one element**: `$append` adds a row, `$update` sets a field of the row at `at`, and `$remove` drops it. Inside the template, `<as>_index` is the row's position at the moment of the tap, so a row edits and removes itself without the document knowing where it sits. Everything else about a mutation is unchanged: the same limits, the same distinct-key rule, the same end of the action list when one is rejected.
- **Reacting to the document's own data**: the `watch` on `items` clears `draft` as part of whatever mutation changed the list, before the next action of that list runs. Mutations made inside a watch trigger no further watch, so there is no cascade to reason about.
- **A lifecycle binding**: `appear` runs when the host says the view is on screen, and again each time it returns. Nothing here is inferred by Milano; the host delivers the signal.
- **A host function**: `formatMoney(item.cents, 'EUR')` is declared by the vocabulary and computed by the app, so money is formatted by the platform's own locale services while the document stays free of formatting rules. It is called by its bare name, where the contract's own functions carry a `$` (`$concat`, `$length`, `$trim`, `$isEmpty`, `$str`), which is why a vocabulary may declare `round` beside `$round` without either shadowing the other.
- Vectors: the mechanics here are pinned piece by piece rather than by one scenario, by `array-*`, `watch-*`, `repeat-key-*`, `lifecycle-*`, and `function-*` in `conformance/examples/`.

## The contact form

Name, surname, email, optional phone, and a consent checkbox that gates submission. All field composition is document-defined: adding a field is a document change, not an app release.

```json
{
  "version": "2.1.0",
  "state": {
    "name": "string",
    "surname": "string",
    "email": "string",
    "phone": "string?",
    "consent": "bool",
    "submitted": "bool",
    "error": "string"
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
          "enabled": { "$expr": "state.consent && !$isEmpty($trim(state.name)) && !$isEmpty($trim(state.surname)) && !$isEmpty($trim(state.email)) && !state.submitted" }
        },
        "on": {
          "tap": [
            {
              "action": "$when",
              "condition": { "$expr": "state.consent && !$isEmpty($trim(state.name)) && !$isEmpty($trim(state.surname)) && !$isEmpty($trim(state.email)) && !state.submitted" },
              "then": [
                {
                  "action": "submitContact",
                  "name": { "$expr": "$trim(state.name)" },
                  "surname": { "$expr": "$trim(state.surname)" },
                  "email": { "$expr": "$trim(state.email)" },
                  "phone": { "$expr": "state.phone" },
                  "onSuccess": [ { "action": "$set", "key": "submitted", "value": true } ],
                  "onFailure": [
                    {
                      "action": "$set",
                      "key": "error",
                      "value": { "$expr": "$if(failure == 'invalid', 'Check your details and try again.', 'We could not reach the server. Try again later.')" }
                    }
                  ]
                }
              ]
            }
          ]
        }
      },
      {
        "type": "Text",
        "id": "thanks",
        "properties": { "text": { "$expr": "$if(state.submitted, 'Thanks! We will be in touch.', '')" } }
      },
      {
        "type": "Text",
        "id": "problem",
        "properties": { "text": { "$expr": "state.error" }, "visible": { "$expr": "!$isEmpty(state.error)" } }
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
- **Async completion**: `submitContact` is delivered to the host's handler; the sequence does not wait. When the handler succeeds, `onSuccess` sets `submitted`, which disables the button and reveals the thank-you text through `$if(...)`.
- **Failure payloads** (contract 2.1): `submitContact` declares a `failure` enum, so when the handler fails with `invalid` or `unavailable`, `failure` binds inside `onFailure` and the document chooses the message itself; a plain error from the handler, carrying no value, would be an invalid completion against this non-optional declaration, which is why the sample handler maps every error to a reason. The handler also receives the dispatch identity with the action, an idempotency key for the request it makes.
- **Optionality**: `phone` is `string?` end to end: `null` from the provider, displayed via `?? ''`, passed as `null` to the handler when never edited.
- Vector: `conformance/examples/form-contact-consent.json` walks the full interaction: fill fields, tap while unconsented (nothing dispatches), consent, tap, complete with success; expects the final state store, the single dispatched action (number 0), and zero occurrences. The failure branch is walked by the `completion-failure-*` vectors.

## Quick actions

A horizontal strip of tiles, each an icon above a label, that records which one was tapped and then asks the host to open a screen. The list is data, not markup: one template, four tiles.

```json
{
  "version": "2.1.0",
  "vocabulary": { "name": "examples", "min": "1.1.0" },
  "state": {
    "actions": {
      "array": {
        "record": {
          "id": "string",
          "label": "string",
          "icon": { "enum": ["person", "list", "search", "edit", "settings", "help"] },
          "screen": { "enum": ["profile", "catalog", "settings", "help"] }
        }
      }
    }
  },
  "root": {
    "type": "Column",
    "id": "home",
    "children": [
      {
        "type": "Text",
        "properties": { "text": "Quick actions" }
      },
      {
        "type": "Row",
        "id": "strip",
        "properties": { "spacing": 12 },
        "children": [
          {
            "type": "$repeat",
            "id": "tiles",
            "items": { "$expr": "state.actions" },
            "as": "tile",
            "key": { "$expr": "tile.id" },
            "children": [
              {
                "type": "Card",
                "id": "tile",
                "properties": {
                  "cornerRadius": 12,
                  "accessibilityLabel": { "$expr": "tile.label" }
                },
                "on": {
                  "tap": [
                    {
                      "action": "logEvent",
                      "event": "quick_action_tapped",
                      "surface": "home",
                      "position": { "$expr": "tile_index" }
                    },
                    {
                      "action": "navigate",
                      "screen": { "$expr": "tile.screen" }
                    }
                  ]
                },
                "children": [
                  {
                    "type": "Column",
                    "children": [
                      { "type": "Icon", "properties": { "name": { "$expr": "tile.icon" } } },
                      { "type": "Text", "properties": { "text": { "$expr": "tile.label" } } }
                    ]
                  }
                ]
              }
            ]
          }
        ]
      }
    ]
  },
  "metadata": { "screen": "home" }
}
```

What it demonstrates:

- **The template is written once**: `$repeat` renders one `Card` per element of `state.actions`, so adding a fifth quick action is a change to the data the app supplies, not to the document. Reordering them is the same.
- **Enums cross the state boundary**: `icon` and `screen` are declared as enums *in the state declaration*, so `tile.icon` has an enum type and satisfies `Icon`'s enum property. A `string` there would be a `SchemaViolation`: an enum position accepts member literals and expressions of the same enum type only (expression language spec, Enum rules). This is what keeps a typo in the supplied data from reaching a renderer as an icon name nobody handles.
- **The tapped element's position, in the payload**: `tile_index` is the element's index in `state.actions` at dispatch time, so the third tile dispatches `logEvent` with `position` 2. The index is bound per instance; nothing in the document counts, and no renderer passes a position back.
- **Position and identity are different things**: because this `$repeat` carries a `key`, every report about the instance names it `tile[settings]`, not `tile[2]`: the identity that survives a reorder. Analytics that wants the *order* takes `tile_index` as a parameter, as this document does; analytics that wants the *thing* reads the reference. An unkeyed repeat has only the index, and reports it as `tile[2]`.
- **A sequence, in document order**: the two actions on `tap` run in order, and both are dispatched with the binding captured at dispatch, so `logEvent` cannot record one tile while `navigate` opens another.
- **The names here are this vocabulary's, not the contract's**: nothing
  blesses `logEvent` or `navigate`. The SDK's sample apps model the same
  strip against their own vocabulary and call the analytics action
  `track`, with an `event` member for the tap; a document written for one
  app does not carry over to another with a different manifest, which is
  the point of a vocabulary being the app's capability list.
- **Navigation is a capability, not a URL**: `navigate` declares `screen` as an enum, so a document can only ask for a screen the app declared. Compare `openUrl` in the banner, where the value is a `string` and the handler is the last check: the enum moves that check to the gate, which is the right trade when the set of destinations is closed and known.
