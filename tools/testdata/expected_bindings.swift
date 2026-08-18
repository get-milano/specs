// Generated from vocabulary "fixture" 2.3.4 by generate_bindings.py.
// Do not edit; regenerate when the vocabulary changes.

import MilanoSDK

/// Members of the `layout` enum on `Widget`. Gate-guaranteed: decoding never fails.
public enum FxWidgetLayout: String {
    case compact
    case wide
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
    public var layout: FxWidgetLayout {
        FxWidgetLayout(rawValue: node.property("layout").stringValue!)!
    }
    /// payload: raw MilanoValue: record-typed read fields through MilanoValue accessors.
    public var payload: MilanoValue { node.property("payload") }
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
    public func emitTap() { node.emit("tap") }
}

/// Every custom action this vocabulary declares, decoded from dispatch.
public enum FxAction {
    case noop
    case openUrl(referrer: String?, url: String)
    /// The handler completes it with a `string` result, bound to `result` in onSuccess.
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
