// Generated from vocabulary "fixture" 2.3.4 by generate_bindings.py.
// Do not edit; regenerate when the vocabulary changes.
package com.example.fixture

import dev.getmilano.MilanoAction
import dev.getmilano.MilanoEngine
import dev.getmilano.MilanoNode
import dev.getmilano.MilanoValue

/** Members of the `layout` enum on `Widget`. Gate-guaranteed: decoding never fails. */
enum class WidgetLayout(
    val value: String,
) {
    Compact("compact"),
    Wide("wide"),
    ;

    companion object {
        fun from(value: String): WidgetLayout = entries.first { it.value == value }
    }
}

/** Members of the `tone` enum on `Widget`. Gate-guaranteed: decoding never fails. */
enum class WidgetTone(
    val value: String,
) {
    Dark("dark"),
    Light("light"),
    ;

    companion object {
        fun from(value: String): WidgetTone = entries.first { it.value == value }
    }
}

/** Members of the `pick` payload enum on `Widget`. Gate-guaranteed: decoding never fails. */
enum class WidgetPickPayload(
    val value: String,
) {
    One("one"),
    Two("two"),
    ;

    companion object {
        fun from(value: String): WidgetPickPayload = entries.first { it.value == value }
    }
}

/** Members of the `mode` enum on action `submit`. Gate-guaranteed: decoding never fails. */
enum class SubmitMode(
    val value: String,
) {
    Draft("draft"),
    Final("final"),
    ;

    companion object {
        fun from(value: String): SubmitMode = entries.first { it.value == value }
    }
}

/** Typed view of a resolved [Plain] node; non-null accessors are gate-guaranteed. */
class PlainNode(
    val node: MilanoNode,
)

/** Typed view of a resolved [Widget] node; non-null accessors are gate-guaranteed. */
class WidgetNode(
    val node: MilanoNode,
) {
    val count: Long get() = node.property("count").intOrNull!!

    val enabled: Boolean get() = node.property("enabled").boolOrNull!!

    val layout: WidgetLayout get() =
        WidgetLayout.from(node.property("layout").stringOrNull!!)

    /** payload: record-typed, read fields through MilanoValue. */
    val payload: MilanoValue get() = node.property("payload")

    val ratio: Double? get() = node.property("ratio").doubleOrNull

    val subtitle: String? get() = node.property("subtitle").stringOrNull

    val tags: List<String> get() = node.property("tags").arrayOrNull!!.map { it.stringOrNull!! }

    val title: String get() = node.property("title").stringOrNull!!

    val tone: WidgetTone? get() =
        node.property("tone").stringOrNull?.let {
            WidgetTone.from(it)
        }

    fun emitChange(payload: String) = node.emit("change", MilanoValue.StringValue(payload))

    fun emitPick(payload: WidgetPickPayload) = node.emit("pick", MilanoValue.StringValue(payload.value))

    fun emitResize(payload: Long?) = node.emit("resize", payload?.let { MilanoValue.IntValue(it) } ?: MilanoValue.Null)

    fun emitTap() = node.emit("tap")
}

/** Every custom action this vocabulary declares, decoded from dispatch. */
sealed interface FixtureAction {
    data object Noop : FixtureAction

    data class OpenUrl(
        val referrer: String?,
        val url: String,
    ) : FixtureAction

    /** The handler completes it with a `string` result, bound to `result` in onSuccess. */
    data class Submit(
        val mode: SubmitMode,
    ) : FixtureAction

    /** An action outside this vocabulary's declarations. */
    data class Unrecognized(
        val action: MilanoAction,
    ) : FixtureAction

    companion object {
        fun from(action: MilanoAction): FixtureAction =
            when (action.name) {
                "noop" -> {
                    Noop
                }

                "openUrl" -> {
                    OpenUrl(
                        referrer = action.parameters["referrer"]?.stringOrNull,
                        url = action.parameters["url"]!!.stringOrNull!!,
                    )
                }

                "submit" -> {
                    Submit(
                        mode = SubmitMode.from(action.parameters["mode"]!!.stringOrNull!!),
                    )
                }

                else -> {
                    Unrecognized(action)
                }
            }
    }
}

/** The vocabulary these bindings were generated from. */
object FixtureVocabulary {
    const val NAME: String = "fixture"
    const val VERSION: String = "2.3.4"

    /** Refuses to run against an engine holding a different vocabulary. */
    fun assertMatches(engine: MilanoEngine) {
        check(engine.vocabularyName == NAME && engine.vocabularyVersion == VERSION) {
            "bindings generated from $NAME@$VERSION, engine holds" +
                " ${engine.vocabularyName}@${engine.vocabularyVersion}"
        }
    }
}
