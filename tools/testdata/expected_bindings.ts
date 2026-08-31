// Generated from vocabulary "fixture" 2.3.4 by generate_bindings.py.
// Do not edit; regenerate when the vocabulary changes.

import { MilanoValue } from "@get-milano/core";
import type { MilanoAction } from "@get-milano/core";

/**
 * What these wrappers need from a resolved node. The React binding's
 * `MilanoNode` satisfies it, and so does any other host wrapper, so
 * the generated file never depends on a UI toolkit.
 */
export interface MilanoNodeLike {
  property(name: string): MilanoValue;
  emit(event: string, payload?: MilanoValue | null): void;
}

/** Members of the `layout` enum on `Widget`. Gate-guaranteed: the value is always a member. */
export type FxWidgetLayout = "compact" | "wide";

/** Members of the `kind` field of `FxWidgetPayload`. Gate-guaranteed: the value is always a member. */
export type FxWidgetPayloadKind = "major" | "minor";

/** Members of the `tone` enum on `Widget`. Gate-guaranteed: the value is always a member. */
export type FxWidgetTone = "dark" | "light";

/** Members of the `pick` payload enum on `Widget`. Gate-guaranteed: the value is always a member. */
export type FxWidgetPickPayload = "one" | "two";

/** Members of the `mode` enum on action `submit`. Gate-guaranteed: the value is always a member. */
export type FxSubmitMode = "draft" | "final";

/** Members of the failure enum of action `submit`. Gate-guaranteed: the value is always a member. */
export type FxSubmitFailure = "offline" | "rejected";

/** Fields of the element of the `items` array on `Widget`. Non-optional accessors are gate-guaranteed. */
export class FxWidgetItemsItem {
  readonly value: MilanoValue;

  constructor(value: MilanoValue) {
    this.value = value;
  }

  static of(fields: { readonly sku: string; readonly qty: bigint }): FxWidgetItemsItem {
    return new FxWidgetItemsItem(MilanoValue.record({
      sku: MilanoValue.string(fields.sku),
      qty: MilanoValue.int(fields.qty),
    }));
  }

  get sku(): string { return (this.field("sku").stringValue as string); }

  get qty(): bigint { return (this.field("qty").intValue as bigint); }

  private field(name: string): MilanoValue {
    return this.value.recordValue?.[name] ?? MilanoValue.null;
  }
}

/** Fields of the `payload` record on `Widget`. Non-optional accessors are gate-guaranteed. */
export class FxWidgetPayload {
  readonly value: MilanoValue;

  constructor(value: MilanoValue) {
    this.value = value;
  }

  static of(fields: {
    readonly id: string;
    readonly count: bigint | null;
    readonly kind: FxWidgetPayloadKind;
    readonly owner: FxWidgetPayloadOwner;
    readonly labels: readonly string[] | null;
  }): FxWidgetPayload {
    return new FxWidgetPayload(MilanoValue.record({
      id: MilanoValue.string(fields.id),
      count: fields.count === null ? MilanoValue.null : MilanoValue.int(fields.count),
      kind: MilanoValue.string(fields.kind),
      owner: fields.owner.value,
      labels:
        fields.labels === null ? MilanoValue.null : MilanoValue.array(fields.labels.map((item) => MilanoValue.string(item))),
    }));
  }

  get id(): string { return (this.field("id").stringValue as string); }

  get count(): bigint | null { return this.field("count").intValue; }

  get kind(): FxWidgetPayloadKind { return (this.field("kind").stringValue as FxWidgetPayloadKind); }

  get owner(): FxWidgetPayloadOwner { return new FxWidgetPayloadOwner(this.field("owner")); }

  get labels(): readonly string[] | null {
    return (this.field("labels").arrayValue?.map((item) => (item.stringValue as string)) ?? null);
  }

  private field(name: string): MilanoValue {
    return this.value.recordValue?.[name] ?? MilanoValue.null;
  }
}

/** Fields of the `owner` field of `FxWidgetPayload`. Non-optional accessors are gate-guaranteed. */
export class FxWidgetPayloadOwner {
  readonly value: MilanoValue;

  constructor(value: MilanoValue) {
    this.value = value;
  }

  static of(fields: { readonly name: string }): FxWidgetPayloadOwner {
    return new FxWidgetPayloadOwner(MilanoValue.record({
      name: MilanoValue.string(fields.name),
    }));
  }

  get name(): string { return (this.field("name").stringValue as string); }

  private field(name: string): MilanoValue {
    return this.value.recordValue?.[name] ?? MilanoValue.null;
  }
}

/** Fields of the `submit` payload record on `Widget`. Non-optional accessors are gate-guaranteed. */
export class FxWidgetSubmitPayload {
  readonly value: MilanoValue;

  constructor(value: MilanoValue) {
    this.value = value;
  }

  static of(fields: {
    readonly id: string;
    readonly lines: readonly bigint[];
  }): FxWidgetSubmitPayload {
    return new FxWidgetSubmitPayload(MilanoValue.record({
      id: MilanoValue.string(fields.id),
      lines: MilanoValue.array(fields.lines.map((item) => MilanoValue.int(item))),
    }));
  }

  get id(): string { return (this.field("id").stringValue as string); }

  get lines(): readonly bigint[] {
    return (this.field("lines").arrayValue as readonly MilanoValue[]).map((item) => (item.intValue as bigint));
  }

  private field(name: string): MilanoValue {
    return this.value.recordValue?.[name] ?? MilanoValue.null;
  }
}

/** Fields of the `cart` record on action `order`. Non-optional accessors are gate-guaranteed. */
export class FxOrderCart {
  readonly value: MilanoValue;

  constructor(value: MilanoValue) {
    this.value = value;
  }

  static of(fields: { readonly id: string; readonly lines: readonly bigint[] }): FxOrderCart {
    return new FxOrderCart(MilanoValue.record({
      id: MilanoValue.string(fields.id),
      lines: MilanoValue.array(fields.lines.map((item) => MilanoValue.int(item))),
    }));
  }

  get id(): string { return (this.field("id").stringValue as string); }

  get lines(): readonly bigint[] {
    return (this.field("lines").arrayValue as readonly MilanoValue[]).map((item) => (item.intValue as bigint));
  }

  private field(name: string): MilanoValue {
    return this.value.recordValue?.[name] ?? MilanoValue.null;
  }
}

/** Fields of the `note` record on action `order`. Non-optional accessors are gate-guaranteed. */
export class FxOrderNote {
  readonly value: MilanoValue;

  constructor(value: MilanoValue) {
    this.value = value;
  }

  static of(fields: { readonly text: string }): FxOrderNote {
    return new FxOrderNote(MilanoValue.record({
      text: MilanoValue.string(fields.text),
    }));
  }

  get text(): string { return (this.field("text").stringValue as string); }

  private field(name: string): MilanoValue {
    return this.value.recordValue?.[name] ?? MilanoValue.null;
  }
}

/** Fields of the result record of action `order`. Non-optional accessors are gate-guaranteed. */
export class FxOrderResult {
  readonly value: MilanoValue;

  constructor(value: MilanoValue) {
    this.value = value;
  }

  static of(fields: { readonly reference: string }): FxOrderResult {
    return new FxOrderResult(MilanoValue.record({
      reference: MilanoValue.string(fields.reference),
    }));
  }

  get reference(): string { return (this.field("reference").stringValue as string); }

  private field(name: string): MilanoValue {
    return this.value.recordValue?.[name] ?? MilanoValue.null;
  }
}

/** Fields of the failure record of action `order`. Non-optional accessors are gate-guaranteed. */
export class FxOrderFailure {
  readonly value: MilanoValue;

  constructor(value: MilanoValue) {
    this.value = value;
  }

  static of(fields: { readonly code: bigint; readonly reason: string }): FxOrderFailure {
    return new FxOrderFailure(MilanoValue.record({
      code: MilanoValue.int(fields.code),
      reason: MilanoValue.string(fields.reason),
    }));
  }

  get code(): bigint { return (this.field("code").intValue as bigint); }

  get reason(): string { return (this.field("reason").stringValue as string); }

  private field(name: string): MilanoValue {
    return this.value.recordValue?.[name] ?? MilanoValue.null;
  }
}

/** Typed view of a resolved `Plain` node. Non-optional accessors are gate-guaranteed. */
export class FxPlainNode {
  readonly node: MilanoNodeLike;

  constructor(node: MilanoNodeLike) {
    this.node = node;
  }
}

/** Typed view of a resolved `Widget` node. Non-optional accessors are gate-guaranteed. */
export class FxWidgetNode {
  readonly node: MilanoNodeLike;

  constructor(node: MilanoNodeLike) {
    this.node = node;
  }

  get count(): bigint { return this.node.property("count").intValue as bigint; }

  get enabled(): boolean { return this.node.property("enabled").boolValue as boolean; }

  get items(): readonly FxWidgetItemsItem[] {
    return (this.node.property("items").arrayValue as readonly MilanoValue[]).map((item) => new FxWidgetItemsItem(item));
  }

  get layout(): FxWidgetLayout {
    return this.node.property("layout").stringValue as FxWidgetLayout;
  }

  get payload(): FxWidgetPayload {
    return new FxWidgetPayload(this.node.property("payload"));
  }

  get ratio(): number | null { return this.node.property("ratio").doubleValue; }

  get subtitle(): string | null { return this.node.property("subtitle").stringValue; }

  get tags(): readonly string[] {
    return (this.node.property("tags").arrayValue as readonly MilanoValue[]).map((item) => item.stringValue as string);
  }

  get title(): string { return this.node.property("title").stringValue as string; }

  get tone(): FxWidgetTone | null {
    return this.node.property("tone").stringValue as FxWidgetTone | null;
  }

  emitChange(payload: string): void { this.node.emit("change", MilanoValue.string(payload)); }

  emitPick(payload: FxWidgetPickPayload): void {
    this.node.emit("pick", MilanoValue.string(payload));
  }

  emitResize(payload: bigint | null): void {
    this.node.emit("resize", payload === null ? MilanoValue.null : MilanoValue.int(payload));
  }

  emitSubmit(payload: FxWidgetSubmitPayload): void {
    this.node.emit("submit", payload.value);
  }

  emitTap(): void { this.node.emit("tap"); }
}

/** Every custom action this vocabulary declares, decoded from dispatch. */
export type FxAction =
  | { readonly kind: "noop" }
  | { readonly kind: "openUrl"; readonly referrer: string | null; readonly url: string }
  /**
   * The handler completes it with a `{"record": {"reference": "string"}}` result, bound to `result` in
   * onSuccess.
   * The handler fails it with a `{"record": {"code": "int", "reason": "string"}}` payload (a
   * MilanoActionFailure), bound to `failure` in onFailure.
   */
  | { readonly kind: "order"; readonly cart: FxOrderCart; readonly note: FxOrderNote | null }
  /**
   * The handler completes it with a `string` result, bound to `result` in onSuccess.
   * The handler fails it with a `{"enum": ["rejected", "offline"]}` payload (a MilanoActionFailure),
   * bound to `failure` in onFailure.
   */
  | { readonly kind: "submit"; readonly mode: FxSubmitMode }
  /** An action outside this vocabulary's declarations (builder-declared, or a newer vocabulary). */
  | { readonly kind: "unrecognized"; readonly action: MilanoAction };

/** Decodes a dispatched action; the switch over `kind` is exhaustive. */
export function fxAction(action: MilanoAction): FxAction {
  switch (action.name) {
    case "noop":
      return { kind: "noop" };
    case "openUrl":
      return {
        kind: "openUrl",
        referrer: action.parameters["referrer"]?.stringValue as string | null,
        url: action.parameters["url"]?.stringValue as string,
      };
    case "order":
      return {
        kind: "order",
        cart: new FxOrderCart(action.parameters["cart"] ?? MilanoValue.null),
        note: (
            (action.parameters["note"] ?? MilanoValue.null).isNull
                ? null
                : new FxOrderNote(action.parameters["note"] ?? MilanoValue.null)
                ),
      };
    case "submit":
      return { kind: "submit", mode: action.parameters["mode"]?.stringValue as FxSubmitMode };
    default:
      return { kind: "unrecognized", action };
  }
}

/** The vocabulary these bindings were generated from. */
export const FxVocabulary = {
  name: "fixture",
  version: "2.3.4",

  /** Throws if the engine holds a different vocabulary. */
  assertMatches(engine: { readonly vocabulary: { readonly name: string; readonly version: string } }): void {
    const held = engine.vocabulary;
    if (held.name !== "fixture" || held.version !== "2.3.4") {
      throw new Error(
        `bindings generated from fixture@2.3.4, engine holds ${held.name}@${held.version}`,
      );
    }
  },
} as const;
