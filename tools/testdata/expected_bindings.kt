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

/** Members of the `kind` field of `WidgetPayload`. Gate-guaranteed: decoding never fails. */
enum class WidgetPayloadKind(
    val value: String,
) {
    Major("major"),
    Minor("minor"),
    ;

    companion object {
        fun from(value: String): WidgetPayloadKind = entries.first { it.value == value }
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

/** Fields of the element of the `items` array on `Widget`. Non-null accessors are gate-guaranteed. */
class WidgetItemsItem(
    val value: MilanoValue,
) {
    val sku: String get() = (value.recordOrNull?.get("sku") ?: MilanoValue.Null).stringOrNull!!
    val qty: Long get() = (value.recordOrNull?.get("qty") ?: MilanoValue.Null).intOrNull!!

    companion object {
        fun of(
            sku: String,
            qty: Long,
        ): WidgetItemsItem =
            WidgetItemsItem(
                MilanoValue.RecordValue(
                    mapOf(
                        "sku" to (MilanoValue.StringValue(sku)),
                        "qty" to (MilanoValue.IntValue(qty)),
                    ),
                ),
            )
    }
}

/** Fields of the `payload` record on `Widget`. Non-null accessors are gate-guaranteed. */
class WidgetPayload(
    val value: MilanoValue,
) {
    val id: String get() = (value.recordOrNull?.get("id") ?: MilanoValue.Null).stringOrNull!!
    val count: Long? get() = (value.recordOrNull?.get("count") ?: MilanoValue.Null).intOrNull
    val kind: WidgetPayloadKind get() = WidgetPayloadKind.from((value.recordOrNull?.get("kind") ?: MilanoValue.Null).stringOrNull!!)
    val owner: WidgetPayloadOwner get() = WidgetPayloadOwner(value.recordOrNull?.get("owner") ?: MilanoValue.Null)
    val labels: List<String>? get() = (value.recordOrNull?.get("labels") ?: MilanoValue.Null).arrayOrNull?.map { item -> item.stringOrNull!! }

    companion object {
        fun of(
            id: String,
            count: Long?,
            kind: WidgetPayloadKind,
            owner: WidgetPayloadOwner,
            labels: List<String>?,
        ): WidgetPayload =
            WidgetPayload(
                MilanoValue.RecordValue(
                    mapOf(
                        "id" to (MilanoValue.StringValue(id)),
                        "count" to (count?.let { MilanoValue.IntValue(it) } ?: MilanoValue.Null),
                        "kind" to (MilanoValue.StringValue(kind.value)),
                        "owner" to (owner.value),
                        "labels" to (labels?.let { MilanoValue.ArrayValue(it.map { item -> MilanoValue.StringValue(item) }) } ?: MilanoValue.Null),
                    ),
                ),
            )
    }
}

/** Fields of the `owner` field of `WidgetPayload`. Non-null accessors are gate-guaranteed. */
class WidgetPayloadOwner(
    val value: MilanoValue,
) {
    val name: String get() = (value.recordOrNull?.get("name") ?: MilanoValue.Null).stringOrNull!!

    companion object {
        fun of(
            name: String,
        ): WidgetPayloadOwner =
            WidgetPayloadOwner(
                MilanoValue.RecordValue(
                    mapOf(
                        "name" to (MilanoValue.StringValue(name)),
                    ),
                ),
            )
    }
}

/** Fields of the `submit` payload record on `Widget`. Non-null accessors are gate-guaranteed. */
class WidgetSubmitPayload(
    val value: MilanoValue,
) {
    val id: String get() = (value.recordOrNull?.get("id") ?: MilanoValue.Null).stringOrNull!!
    val lines: List<Long> get() = (value.recordOrNull?.get("lines") ?: MilanoValue.Null).arrayOrNull!!.map { item -> item.intOrNull!! }

    companion object {
        fun of(
            id: String,
            lines: List<Long>,
        ): WidgetSubmitPayload =
            WidgetSubmitPayload(
                MilanoValue.RecordValue(
                    mapOf(
                        "id" to (MilanoValue.StringValue(id)),
                        "lines" to (MilanoValue.ArrayValue(lines.map { item -> MilanoValue.IntValue(item) })),
                    ),
                ),
            )
    }
}

/** Fields of the `cart` record on action `order`. Non-null accessors are gate-guaranteed. */
class OrderCart(
    val value: MilanoValue,
) {
    val id: String get() = (value.recordOrNull?.get("id") ?: MilanoValue.Null).stringOrNull!!
    val lines: List<Long> get() = (value.recordOrNull?.get("lines") ?: MilanoValue.Null).arrayOrNull!!.map { item -> item.intOrNull!! }

    companion object {
        fun of(
            id: String,
            lines: List<Long>,
        ): OrderCart =
            OrderCart(
                MilanoValue.RecordValue(
                    mapOf(
                        "id" to (MilanoValue.StringValue(id)),
                        "lines" to (MilanoValue.ArrayValue(lines.map { item -> MilanoValue.IntValue(item) })),
                    ),
                ),
            )
    }
}

/** Fields of the `note` record on action `order`. Non-null accessors are gate-guaranteed. */
class OrderNote(
    val value: MilanoValue,
) {
    val text: String get() = (value.recordOrNull?.get("text") ?: MilanoValue.Null).stringOrNull!!

    companion object {
        fun of(
            text: String,
        ): OrderNote =
            OrderNote(
                MilanoValue.RecordValue(
                    mapOf(
                        "text" to (MilanoValue.StringValue(text)),
                    ),
                ),
            )
    }
}

/** Fields of the result record of action `order`. Non-null accessors are gate-guaranteed. */
class OrderResult(
    val value: MilanoValue,
) {
    val reference: String get() = (value.recordOrNull?.get("reference") ?: MilanoValue.Null).stringOrNull!!

    companion object {
        fun of(
            reference: String,
        ): OrderResult =
            OrderResult(
                MilanoValue.RecordValue(
                    mapOf(
                        "reference" to (MilanoValue.StringValue(reference)),
                    ),
                ),
            )
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

    val items: List<WidgetItemsItem> get() =
        node.property("items").arrayOrNull!!.map { item -> WidgetItemsItem(item) }

    val layout: WidgetLayout get() =
        WidgetLayout.from(node.property("layout").stringOrNull!!)

    val payload: WidgetPayload get() =
        WidgetPayload(node.property("payload"))

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

    fun emitSubmit(payload: WidgetSubmitPayload) = node.emit("submit", payload.value)

    fun emitTap() = node.emit("tap")
}

/** Every custom action this vocabulary declares, decoded from dispatch. */
sealed interface FixtureAction {
    data object Noop : FixtureAction

    data class OpenUrl(
        val referrer: String?,
        val url: String,
    ) : FixtureAction

    /** The handler completes it with a `{"record": {"reference": "string"}}` result, bound to `result` in onSuccess. */
    data class Order(
        val cart: OrderCart,
        val note: OrderNote?,
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

                "order" -> {
                    Order(
                        cart = OrderCart(action.parameters["cart"] ?: MilanoValue.Null),
                        note = (action.parameters["note"] ?: MilanoValue.Null).takeUnless { it.isNull }?.let { OrderNote(it) },
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
