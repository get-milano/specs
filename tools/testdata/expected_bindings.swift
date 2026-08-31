// Generated from vocabulary "fixture" 2.3.4 by generate_bindings.py.
// Do not edit; regenerate when the vocabulary changes.

import MilanoSDK

/// Members of the `layout` enum on `Widget`. Gate-guaranteed: decoding never fails.
public enum FxWidgetLayout: String {
    case compact
    case wide
}

/// Members of the `kind` field of `FxWidgetPayload`. Gate-guaranteed: decoding never fails.
public enum FxWidgetPayloadKind: String {
    case major
    case minor
}

/// Members of the `tone` enum on `Widget`. Gate-guaranteed: decoding never fails.
public enum FxWidgetTone: String {
    case dark
    case light
}

/// Members of the `pick` payload enum on `Widget`. Gate-guaranteed: decoding never fails.
public enum FxWidgetPickPayload: String {
    case one
    case two
}

/// Members of the `mode` enum on action `submit`. Gate-guaranteed: decoding never fails.
public enum FxSubmitMode: String {
    case draft
    case final
}

/// Members of the failure enum of action `submit`. Gate-guaranteed: decoding never fails.
public enum FxSubmitFailure: String {
    case offline
    case rejected
}

/// Fields of the element of the `items` array on `Widget`. Non-optional accessors are gate-guaranteed.
public struct FxWidgetItemsItem {
    public let value: MilanoValue
    public init(_ value: MilanoValue) { self.value = value }
    public init(sku: String, qty: Int64) {
        value = .record([
            "sku": .string(sku),
            "qty": .int(qty)
        ])
    }
    public var sku: String { (value.recordValue?["sku"] ?? .null).stringValue! }
    public var qty: Int64 { (value.recordValue?["qty"] ?? .null).intValue! }
}

/// Fields of the `payload` record on `Widget`. Non-optional accessors are gate-guaranteed.
public struct FxWidgetPayload {
    public let value: MilanoValue
    public init(_ value: MilanoValue) { self.value = value }
    public init(
        id: String,
        count: Int64?,
        kind: FxWidgetPayloadKind,
        owner: FxWidgetPayloadOwner,
        labels: [String]?
    ) {
        value = .record([
            "id": .string(id),
            "count": count.map { .int($0) } ?? .null,
            "kind": .string(kind.rawValue),
            "owner": owner.value,
            "labels": labels.map { .array($0.map { .string($0) }) } ?? .null
        ])
    }
    public var id: String { (value.recordValue?["id"] ?? .null).stringValue! }
    public var count: Int64? { (value.recordValue?["count"] ?? .null).intValue }
    public var kind: FxWidgetPayloadKind {
        FxWidgetPayloadKind(rawValue: (value.recordValue?["kind"] ?? .null).stringValue!)!
    }
    public var owner: FxWidgetPayloadOwner { FxWidgetPayloadOwner(value.recordValue?["owner"] ?? .null) }
    public var labels: [String]? { (value.recordValue?["labels"] ?? .null).arrayValue?.map { $0.stringValue! } }
}

/// Fields of the `owner` field of `FxWidgetPayload`. Non-optional accessors are gate-guaranteed.
public struct FxWidgetPayloadOwner {
    public let value: MilanoValue
    public init(_ value: MilanoValue) { self.value = value }
    public init(name: String) {
        value = .record([
            "name": .string(name)
        ])
    }
    public var name: String { (value.recordValue?["name"] ?? .null).stringValue! }
}

/// Fields of the `submit` payload record on `Widget`. Non-optional accessors are gate-guaranteed.
public struct FxWidgetSubmitPayload {
    public let value: MilanoValue
    public init(_ value: MilanoValue) { self.value = value }
    public init(id: String, lines: [Int64]) {
        value = .record([
            "id": .string(id),
            "lines": .array(lines.map { .int($0) })
        ])
    }
    public var id: String { (value.recordValue?["id"] ?? .null).stringValue! }
    public var lines: [Int64] { (value.recordValue?["lines"] ?? .null).arrayValue!.map { $0.intValue! } }
}

/// Fields of the `cart` record on action `order`. Non-optional accessors are gate-guaranteed.
public struct FxOrderCart {
    public let value: MilanoValue
    public init(_ value: MilanoValue) { self.value = value }
    public init(id: String, lines: [Int64]) {
        value = .record([
            "id": .string(id),
            "lines": .array(lines.map { .int($0) })
        ])
    }
    public var id: String { (value.recordValue?["id"] ?? .null).stringValue! }
    public var lines: [Int64] { (value.recordValue?["lines"] ?? .null).arrayValue!.map { $0.intValue! } }
}

/// Fields of the `note` record on action `order`. Non-optional accessors are gate-guaranteed.
public struct FxOrderNote {
    public let value: MilanoValue
    public init(_ value: MilanoValue) { self.value = value }
    public init(text: String) {
        value = .record([
            "text": .string(text)
        ])
    }
    public var text: String { (value.recordValue?["text"] ?? .null).stringValue! }
}

/// Fields of the result record of action `order`. Non-optional accessors are gate-guaranteed.
public struct FxOrderResult {
    public let value: MilanoValue
    public init(_ value: MilanoValue) { self.value = value }
    public init(reference: String) {
        value = .record([
            "reference": .string(reference)
        ])
    }
    public var reference: String { (value.recordValue?["reference"] ?? .null).stringValue! }
}

/// Fields of the failure record of action `order`. Non-optional accessors are gate-guaranteed.
public struct FxOrderFailure {
    public let value: MilanoValue
    public init(_ value: MilanoValue) { self.value = value }
    public init(code: Int64, reason: String) {
        value = .record([
            "code": .int(code),
            "reason": .string(reason)
        ])
    }
    public var code: Int64 { (value.recordValue?["code"] ?? .null).intValue! }
    public var reason: String { (value.recordValue?["reason"] ?? .null).stringValue! }
}

/// Typed view of a resolved `Plain` node. Non-optional accessors are gate-guaranteed.
public struct FxPlainNode {
    public let node: MilanoNode
    public init(_ node: MilanoNode) { self.node = node }
}

/// Typed view of a resolved `Widget` node. Non-optional accessors are gate-guaranteed.
public struct FxWidgetNode {
    public let node: MilanoNode
    public init(_ node: MilanoNode) { self.node = node }
    public var count: Int64 { node.property("count").intValue! }
    public var enabled: Bool { node.property("enabled").boolValue! }
    public var items: [FxWidgetItemsItem] {
        node.property("items").arrayValue!.map { FxWidgetItemsItem($0) }
    }
    public var layout: FxWidgetLayout {
        FxWidgetLayout(rawValue: node.property("layout").stringValue!)!
    }
    public var payload: FxWidgetPayload {
        FxWidgetPayload(node.property("payload"))
    }
    public var ratio: Double? { node.property("ratio").doubleValue }
    public var subtitle: String? { node.property("subtitle").stringValue }
    public var tags: [String] { node.property("tags").arrayValue!.map { $0.stringValue! } }
    public var title: String { node.property("title").stringValue! }
    public var tone: FxWidgetTone? {
        node.property("tone").stringValue.flatMap(FxWidgetTone.init(rawValue:))
    }
    public func emitChange(_ payload: String) { node.emit("change", payload: .string(payload)) }
    public func emitPick(_ payload: FxWidgetPickPayload) {
        node.emit("pick", payload: .string(payload.rawValue))
    }
    public func emitResize(_ payload: Int64?) { node.emit("resize", payload: payload.map { .int($0) } ?? .null) }
    public func emitSubmit(_ payload: FxWidgetSubmitPayload) {
        node.emit("submit", payload: payload.value)
    }
    public func emitTap() { node.emit("tap") }
}

/// Every custom action this vocabulary declares, decoded from dispatch.
public enum FxAction {
    case noop
    case openUrl(referrer: String?, url: String)
    /// The handler completes it with a `{"record": {"reference": "string"}}` result, bound to `result` in
    /// onSuccess.
    /// The handler fails it with a `{"record": {"code": "int", "reason": "string"}}` payload (a
    /// MilanoActionFailure), bound to `failure` in onFailure.
    case order(cart: FxOrderCart, note: FxOrderNote?)
    /// The handler completes it with a `string` result, bound to `result` in onSuccess.
    /// The handler fails it with a `{"enum": ["rejected", "offline"]}` payload (a MilanoActionFailure),
    /// bound to `failure` in onFailure.
    case submit(mode: FxSubmitMode)
    /// An action outside this vocabulary's declarations (builder-declared, or a newer vocabulary).
    case unrecognized(MilanoAction)

    public init(_ action: MilanoAction) {
        switch action.name {
        case "noop":
            self = .noop
        case "openUrl":
            self = .openUrl(
                referrer: action.parameters["referrer"]?.stringValue,
                url: action.parameters["url"]!.stringValue!)
        case "order":
            self = .order(
                cart: FxOrderCart(action.parameters["cart"] ?? .null),
                note: (action.parameters["note"] ?? .null).isNull ? nil : FxOrderNote(action.parameters["note"] ?? .null))
        case "submit":
            self = .submit(mode: FxSubmitMode(rawValue: action.parameters["mode"]!.stringValue!)!)
        default:
            self = .unrecognized(action)
        }
    }
}

/// The vocabulary these bindings were generated from.
public enum FxVocabulary {
    public static let name = "fixture"
    public static let version = "2.3.4"

    /// Refuses to run against an engine holding a different vocabulary.
    public static func assertMatches(_ engine: MilanoEngine) {
        precondition(
            engine.vocabularyName == name && engine.vocabularyVersion == version,
            "bindings generated from \(name)@\(version), engine holds"
                + " \(engine.vocabularyName)@\(engine.vocabularyVersion)")
    }
}
