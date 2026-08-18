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

/** Members of the `tone` enum on `Widget`. Gate-guaranteed: the value is always a member. */
export type FxWidgetTone = "dark" | "light";

/** Members of the `pick` payload enum on `Widget`. Gate-guaranteed: the value is always a member. */
export type FxWidgetPickPayload = "one" | "two";

/** Members of the `mode` enum on action `submit`. Gate-guaranteed: the value is always a member. */
export type FxSubmitMode = "draft" | "final";

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

  get layout(): FxWidgetLayout {
    return this.node.property("layout").stringValue as FxWidgetLayout;
  }

  /** The raw value; record-typed: read fields through MilanoValue accessors. */
  get payload(): MilanoValue { return this.node.property("payload"); }

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

  emitTap(): void { this.node.emit("tap"); }
}

/** Every custom action this vocabulary declares, decoded from dispatch. */
export type FxAction =
  | { readonly kind: "noop" }
  | { readonly kind: "openUrl"; readonly referrer: string | null; readonly url: string }
  /** The handler completes it with a `string` result, bound to `result` in onSuccess. */
  | { readonly kind: "submit"; readonly mode: FxSubmitMode }
  /** An action outside this vocabulary's declarations (builder-declared, or a newer vocabulary). */
  | { readonly kind: "unrecognized"; readonly action: MilanoAction };

/** Decodes a dispatched action; the switch over `kind` is exhaustive. */
export function fxAction(action: MilanoAction): FxAction {
  switch (action.name) {
    case "noop":
      return { kind: "noop" };
    case "openUrl":
      return { kind: "openUrl", referrer: action.parameters["referrer"]?.stringValue as string | null, url: action.parameters["url"]?.stringValue as string };
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
