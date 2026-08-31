---
title: "Expression language"
nav_order: 4
---

# Milano Expression Language

**Status:** Stable · contract 2.1 · repository release 2.1.0 · 2026-08-31

Defines the grammar and semantics of the expression strings carried by the `$expr` wrapper. Expressions are pure, statically typed, and total: after the gate accepts a document, evaluation can never fail. Every runtime implements this spec independently; the conformance suite is the arbiter of identical behavior.

## Grammar

The complete grammar, EBNF. Whitespace (spaces and tabs) may appear between any two tokens and is insignificant; there are no comments.

```ebnf
expression     = coalesce ;
coalesce       = or , [ "??" , coalesce ] ;                    (* right-associative *)
or             = and , { "||" , and } ;
and            = equality , { "&&" , equality } ;
equality       = comparison , { ( "==" | "!=" ) , comparison } ;
comparison     = additive , { ( "<" | "<=" | ">" | ">=" ) , additive } ;
additive       = multiplicative , { ( "+" | "-" ) , multiplicative } ;
multiplicative = unary , { ( "*" | "/" | "%" ) , unary } ;
unary          = ( "!" | "-" ) , unary | postfix ;
postfix        = primary , { "." , identifier } ;
primary        = literal | call | reference | "(" , expression , ")" ;
call           = ( builtin | identifier ) , "(" , [ expression , { "," , expression } ] , ")" ;
builtin        = "$" , identifier ;                            (* a function of the contract *)
reference      = identifier ;                                  (* must be a reserved root *)
literal        = number | string | "true" | "false" | "null" ;
number         = digit , { digit } , [ "." , digit , { digit } ] ;  (* no leading dot, no exponent *)
string         = "'" , { character | "\'" | "\\" } , "'" ;
identifier     = letter , { letter | digit | "_" } ;
```

Notes:

- `character` is any Unicode scalar other than `'` and `\`, which appear only through their escapes. `letter` is ASCII `A`-`Z` and `a`-`z`; `digit` is ASCII `0`-`9`. Non-ASCII letters and digits (including Unicode digit characters) are not part of the grammar and fail to tokenize.
- A bare `identifier` in `primary` position must be a root usable as a value: `event`, `result`, or `failure` in their scopes, or a `$repeat` binding in its template. `state` and `context` are namespaces, valid only as the base of a field access; a bare `state` or `context`, and any other bare identifier, is a `SchemaViolation` at the gate. Function names appear only in `call` position.
- A `builtin` names one of the functions below, in the `$` namespace the contract reserves everywhere else (`$set`, `$repeat`, `$expr`). A `$` token anywhere but immediately before a call's `(`, and a `$` name this spec does not define, are a `SchemaViolation` under rule `expression`. Host functions (below) are declared by consumers and called by bare identifiers, so the two sets cannot collide: a vocabulary may declare `abs`, `round`, or `formatMoney`, and `$abs` still means exactly what the table below says. That separation is also what lets a later minor add a built-in without invalidating a vocabulary that already declares the name.
- Negative literals are the unary `-` operator applied to a number.
- A `number` without a decimal point is an `int` literal; with one, a `double` literal.

## References

- Reserved roots: `state`, `context`, `event` (only inside a node's `on` bindings of events declaring a payload; never in the document's lifecycle bindings), `result` (only inside `onSuccess` bindings of actions declaring a result), and `failure` (contract 2.1; only inside `onFailure` bindings of actions declaring a failure type, see the vocabulary schema spec). Inside a `$repeat` template (document model spec), the names the construct binds are roots too: `<as>` is the element, `<as>_index` its position, both available in property expressions, the construct's `key`, and the template's action bindings, including follow-ups.
- Record fields are accessed with `.` (dot). Field access requires a non-optional record type; an optional must be resolved with `??` first. This rule is checked at the gate, which is what makes null dereference impossible at runtime.
- There is no array indexing in contract 2.0.

## Literals

- `int`: decimal digits, optionally negated. A literal outside the 64-bit range is a `SchemaViolation` at the gate: what the producer wrote is rejected, never silently changed.
- `double`: decimal digits with a decimal point, optionally negated.
- `string`: single-quoted, with `\'` and `\\` escapes.
- `bool`: `true`, `false`.
- `null`: valid only where the expected type is optional.

## Operators

In precedence order, tightest first. Parentheses group.

| Level | Operators | Operands |
|---|---|---|
| 1 | `!` `-` (unary) | bool; int or double |
| 2 | `*` `/` `%` | numeric |
| 3 | `+` `-` | numeric; `+` also concatenates when both operands are strings |
| 4 | `<` `<=` `>` `>=` | numeric only |
| 5 | `==` `!=` | non-optional scalars of the same type after numeric promotion. An optional operand is comparable only to `null`: comparing it to anything else, including another optional, is a `SchemaViolation` at the gate, and a producer resolves it with `??` first, the same rule as field access and `if`. A non-optional operand beside `null`, or `null` beside `null`, is likewise a `SchemaViolation` (the comparison could only ever be constant). Arrays and records are not comparable in contract 2.0: comparing them is a `SchemaViolation` at the gate |
| 6 | `&&` | bool, short-circuit |
| 7 | `||` | bool, short-circuit |
| 8 | `??` | optional T on the left, T on the right; result T; right-associative |

Binary operators associate left except `??`, which associates right.

## Numeric semantics

Fixed exactly, because independent runtimes must agree to the bit:

- **Promotion.** When `int` and `double` meet in an arithmetic or comparison operator, the `int` converts to `double` (IEEE 754 round-to-nearest) and the operation is a double operation. `int` with `int` stays `int`.
- **Integer arithmetic.** 64-bit two's complement, wrapping on overflow. Division truncates toward zero; the sign of `%` follows the dividend.
- **Division and modulo by zero (int).** The result is `0`, and the occurrence is reported to the engine observer. Evaluation does not fail.
- **Double arithmetic.** IEEE 754 binary64 throughout: division by zero yields infinities, `0.0/0.0` yields NaN, and NaN compares unequal to everything including itself.
- **Conversions.** `$double(x)` converts an int exactly when representable, otherwise round-to-nearest. `$int(x)` truncates toward zero and saturates at the int64 bounds; saturation is reported to the observer. `$int(NaN)` is `0`, reported as saturation.

## Strings

- `+` concatenates two strings. There is no implicit stringification: mixing a string with a number in `+` is a `SchemaViolation` at the gate.
- `$str(x)` converts scalars to strings, locale-independently: ints in decimal; bools as `true` / `false`. Doubles use a Milano-defined format, never the platform default: non-finite values are `nan`, `inf`, `-inf`; finite values use the shortest round-trip digits, rendered as plain decimal (integral values keep one fractional digit: `5.0`) while the normalized exponent is within [-4, 15], otherwise as scientific notation `d[.ddd]e[-]NN` with a lowercase `e`, no plus sign, no zero padding.
- Ordering operators do not apply to strings; equality does.
- Substring functions (`contains`, `startsWith`, `endsWith`) compare Unicode scalar sequences literally: no normalization, no grapheme clustering. String values are Unicode scalar sequences by definition; host-constructed values containing unpaired surrogates are outside the contract.
- `trim` removes exactly the characters with the Unicode White_Space property, from an explicit table every runtime shares; platform whitespace helpers are not used.

## Lookups

Contract 2.1. `record[key]` reads one field of a record, choosing it at evaluation rather than writing it in the document. It exists for the shape every view has: a code, and a label for each code.

```
context.labels[state.status]
```

Four rules, all at the gate:

- The subject is a non-optional `record`.
- The key is an expression of a non-optional `enum` type. A `string` key is a `SchemaViolation`: a string is not checkable against the record's fields, and the check is the point.
- **The enum's members and the record's fields are the same set.** This is what makes the lookup total, so it can never fail at runtime, and what makes it exhaustive: add a member to the enum later and the record no longer covers it, so the gate refuses the document instead of the view rendering the wrong label.
- Every field of the record shares one type, optionality included, and that is the lookup's type. A record whose fields disagree has no single type to give.

An enum value is its member string at runtime, so evaluation is the field of that name, which the gate proved is there. A document declaring contract 2.0 that writes one fails with the `contract-feature` rule, the feature spelled `[]`.

The alternative a document would otherwise write is a chain of `$if`s comparing the subject to each member. That chain type-checks, but its last `else` silently absorbs every member added afterwards; the lookup is the version the gate can check.

## Functions

The complete set of built-in functions in contract 2.1, each named in the contract's `$` namespace; a vocabulary may add host functions (below), which are bare identifiers and cannot collide with these. All functions are pure and total. Arguments are evaluated eagerly, with one exception: `if` evaluates only the taken branch, like `&&`, `||`, and `??`. The last eleven rows arrived with contract 2.1; a document declaring 2.0 that calls one fails the gate with the `contract-feature` rule (document model spec, Validation).

| Function | Signature | Notes |
|---|---|---|
| `$str` | scalar to string | Locale-independent formats above |
| `$int` | double to int | Truncates toward zero, saturates, reports saturation |
| `$double` | int to double | Round-to-nearest |
| `$concat` | strings... to string | Two or more arguments |
| `$length` | string or array to int | Strings: Unicode scalar count |
| `$isEmpty` | string or array to bool | |
| `$contains` | string, string to bool | |
| `$startsWith` | string, string to bool | |
| `$endsWith` | string, string to bool | |
| `$trim` | string to string | Removes leading and trailing Unicode whitespace |
| `$if` | bool, T, T to T | Both branches type-check to exactly the same T, optionality included: a `T?` branch beside a `T` branch is rejected (resolve the optional with `??` first), a single `null` branch makes T optional, and two `null` branches are rejected (no T to infer); only the taken branch is evaluated, observable as the absence of the untaken branch's arithmetic reports |
| `$abs` | int to int; double to double | The magnitude. Ints wrap: the minimum int has no positive counterpart and stays itself, with no report. Doubles follow IEEE 754: `$abs(-0.0)` is `0.0`, NaN stays NaN |
| `$min` | numeric... to numeric | Two or more arguments. All `int` gives `int`; otherwise every argument promotes to `double`. The result starts as the first argument and is replaced by each later argument that is strictly less (`<`); a NaN anywhere makes the result NaN. So ties keep the leftmost, and `$min(0.0, -0.0)` is `0.0` |
| `$max` | numeric... to numeric | As `min` with strictly greater (`>`) |
| `$floor` | double to double | The greatest integral double not above the argument, IEEE 754: `$floor(-0.5)` is `-1.0`, `$floor(-0.0)` is `-0.0`; NaN and infinities pass through |
| `$ceil` | double to double | The least integral double not below the argument: `$ceil(-0.5)` is `-0.0`; NaN and infinities pass through |
| `$round` | double to double | The nearest integral double, ties away from zero: `$round(0.5)` is `1.0`, `$round(-2.5)` is `-3.0`, `$round(-0.4)` is `-0.0`; NaN and infinities pass through. Never the platform's rounding, whose tie rule differs by language |
| `$substring` | string, int, int to string | The scalars from the first index up to, not including, the second. Both are clamped to `[0, $length]`, so every pair names a slice and nothing is out of range: a first index at or past the second gives the empty string |
| `$indexOf` | string, string to int | The scalar index where the second argument first occurs in the first, or `-1` when it does not. An empty needle is `0` |
| `$replace` | string, string, string to string | Every non-overlapping occurrence, found left to right, replaced. An empty needle returns the subject unchanged |
| `$split` | string, string to array of string | The pieces between occurrences of the separator, left to right: always at least one element, adjacent separators giving empty ones. An empty separator returns a one-element array holding the subject |
| `$join` | array of string, string to string | The elements in order with the separator between them; an empty array gives the empty string. An array of enum joins by member string, as enums widen to string everywhere |

The rounding functions return doubles: `$int($round(x))` is how a document gets an integer from one, with `int`'s saturation rules. Like `int` and `double`, they take exactly the type they name: an `int` argument to `floor`, `ceil`, or `round` is a `SchemaViolation`. `abs`, `min`, and `max` accept either numeric type, promoting as the arithmetic operators do.

The string functions are total the way the numeric ones are, and by the same discipline: every argument names a result, so none of them reports. `substring` clamps rather than failing on an index outside the string, `indexOf` answers `-1` rather than failing on an absent needle, and the two guards that look like special cases are what keep results bounded by their inputs: an empty needle in `replace` matches at every position, and an empty separator in `split` would produce one element per scalar, so each returns its subject instead. Where a result is later assigned to state, the value size limit applies to it as to any other value.

There are no regular expressions in contract 2.1: string validation beyond these functions belongs to the producer or the host. There are no case-mapping or formatting functions among the built-ins: case rules, number and date formats are locale matters, and a host that needs them in a document declares host functions.

## Host functions

Contract 2.1. A function the surface declares (in the vocabulary's `functions` section, or on the builder; vocabulary schema spec, Function declarations) is called exactly like a built-in: by name, with positional arguments, anywhere an expression goes.

```
$concat('Total: ', formatMoney(state.total, 'EUR', context.locale))
```

- **Resolution.** A `$name` call names a built-in (Functions, above) and a bare `name` call a declared host function; neither can shadow the other, and a name in either namespace that nothing declares is a `SchemaViolation` under rule `expression`. A document declaring a contract before 2.1 that calls a declared function fails with the `contract-feature` rule naming the function (document model spec, Validation).
- **Typing.** The call takes exactly as many arguments as declared. Each argument is a declared position: it must type-check to the declared type under the acceptance rules of this spec (an `int` where `double` is declared is promoted at evaluation, a non-optional value fits an optional declaration, a string literal in an enum position must be a member and takes the enum type). The call's type is exactly the declared `returns`, optionality included; an optional return is resolved with `??` like any optional.
- **Evaluation.** Arguments are evaluated eagerly, left to right, and promoted to their declared types; the runtime then calls the engine's function handler synchronously, on the thread evaluating the expression (the main thread), with the function's name and the argument values as `MilanoValue`s (runtime API spec, `MilanoFunctionHandler`). The handler's value is validated against `returns` like a completion result against `result`.
- **Invalid results.** A handler that throws, or returns a value that does not match `returns`, produces an **invalid function result**: the occurrence `invalidFunctionResult` is reported (the node and property being resolved as for arithmetic reports, `name` the function's name, `expected` the declared return type, `found` the value's kind or `error` for a throw), and the call evaluates to the **zero value** of the declared return type, so evaluation stays total: `false`, `0`, `0.0`, the empty string, the first declared member of an enum, the empty array, a record of zero values, and `null` for any optional type. A handler that cannot compute a value declares an optional return and answers `null`, which the document resolves with `??`; a throw is a defect, not a signal.
- **Purity.** Host functions are pure over their arguments (vocabulary schema spec). The runtime may evaluate a call every time a dependency of the expression changes, more than once per update, and may cache by arguments within a view; a document can observe none of it. Dependency tracking follows the arguments: a property calling `formatMoney(state.total, 'EUR', context.locale)` re-evaluates when `state.total` or `context.locale` changes, and never otherwise.

## Typing and totality

- Every expression has a static type, determined at the gate from literals, declared state and context types, event payload, action result, and failure payload types, operator rules, and function signatures, built-in and declared alike. A property expression must type-check to the property's declared type; mismatches are a `SchemaViolation` at the gate.
- A non-optional `T` is accepted wherever an optional `T` is expected; the reverse never holds. An `int` expression is accepted wherever a `double` is expected, and its value is promoted to `double` at evaluation, exactly as an `int` literal or data value is (document model spec); a `double` is never accepted where `int` is expected.
- Both acceptances apply where a declared type meets an expression: property values, `$set` values, and action parameters. Neither applies between the two branches of `if`, which must have exactly the same type, optionality included, with the one exception the function table grants: a single `null` branch beside a `T` branch makes the result `T?`. Otherwise a producer resolves the optional branch with `??` first.

Enum types follow four rules, all enforced at the gate:

- **Refinement.** The expected type propagates into `if` branches and both sides of `??`. A string literal in an enum position (a property value, `$set` value, action parameter, or a propagated branch of one) must be a member of that enum and takes the enum type; a non-member is a `SchemaViolation`. Everywhere else a string literal is a plain `string`.
- **Strictness.** An enum position accepts member literals and expressions of the same enum type only; an expression of type `string` is a `SchemaViolation` there. Two enum types are the same exactly when their member sets are equal, and expressions over distinct enums never mix.
- **Widening.** An enum value is accepted wherever a `string` is expected: string functions (`concat`, `str`, `length`, `isEmpty`, and the rest), `+` concatenation, and `string`-declared positions. Widening is one-way.
- **Comparison.** `==` and `!=` between an enum and a string literal require the literal to be a member (the typo fails the gate instead of evaluating to a silently constant `false`); between two enums they require the same enum type; between an enum and a non-literal `string` expression they compare by string value. Ordering operators never accept enums.
- After the gate: no type errors (static), no null dereference (the `??` rule), no division failures (defined results), no overflow traps (wrapping and saturation). Evaluation is total. The conformance suite includes vectors for every boundary in this section.
