---
title: "Expression language"
nav_order: 4
---

# Milano Expression Language

**Status:** Stable v1.0.0 · 2026-08-16

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
call           = identifier , "(" , [ expression , { "," , expression } ] , ")" ;
reference      = identifier ;                                  (* must be a reserved root *)
literal        = number | string | "true" | "false" | "null" ;
number         = digit , { digit } , [ "." , digit , { digit } ] ;  (* no leading dot, no exponent *)
string         = "'" , { character | "\'" | "\\" } , "'" ;
identifier     = letter , { letter | digit | "_" } ;
```

Notes:

- `character` is any Unicode scalar other than `'` and `\`, which appear only through their escapes. `letter` is ASCII `A`-`Z` and `a`-`z`; `digit` is ASCII `0`-`9`. Non-ASCII letters and digits (including Unicode digit characters) are not part of the grammar and fail to tokenize.
- A bare `identifier` in `primary` position must be a reserved root usable as a value: `event` or `result`, in their scopes. `state` and `context` are namespaces, valid only as the base of a field access; a bare `state` or `context`, and any other bare identifier, is a `SchemaViolation` at the gate. Function names appear only in `call` position.
- Negative literals are the unary `-` operator applied to a number.
- A `number` without a decimal point is an `int` literal; with one, a `double` literal.

## References

- Reserved roots: `state`, `context`, `event` (only inside `on` bindings of events declaring a payload), and `result` (only inside `onSuccess` bindings of actions declaring a result).
- Record fields are accessed with `.` (dot). Field access requires a non-optional record type; an optional must be resolved with `??` first. This rule is checked at the gate, which is what makes null dereference impossible at runtime.
- There is no array indexing in v1.0.

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
| 5 | `==` `!=` | non-optional scalars of the same type after numeric promotion. An optional operand is comparable only to `null`: comparing it to anything else, including another optional, is a `SchemaViolation` at the gate, and a producer resolves it with `??` first, the same rule as field access and `if`. A non-optional operand beside `null`, or `null` beside `null`, is likewise a `SchemaViolation` (the comparison could only ever be constant). Arrays and records are not comparable in v1.0: comparing them is a `SchemaViolation` at the gate |
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
- **Conversions.** `double(x)` converts an int exactly when representable, otherwise round-to-nearest. `int(x)` truncates toward zero and saturates at the int64 bounds; saturation is reported to the observer. `int(NaN)` is `0`, reported as saturation.

## Strings

- `+` concatenates two strings. There is no implicit stringification: mixing a string with a number in `+` is a `SchemaViolation` at the gate.
- `str(x)` converts scalars to strings, locale-independently: ints in decimal; bools as `true` / `false`. Doubles use a Milano-defined format, never the platform default: non-finite values are `nan`, `inf`, `-inf`; finite values use the shortest round-trip digits, rendered as plain decimal (integral values keep one fractional digit: `5.0`) while the normalized exponent is within [-4, 15], otherwise as scientific notation `d[.ddd]e[-]NN` with a lowercase `e`, no plus sign, no zero padding.
- Ordering operators do not apply to strings; equality does.
- Substring functions (`contains`, `startsWith`, `endsWith`) compare Unicode scalar sequences literally: no normalization, no grapheme clustering. String values are Unicode scalar sequences by definition; host-constructed values containing unpaired surrogates are outside the contract.
- `trim` removes exactly the characters with the Unicode White_Space property, from an explicit table every runtime shares; platform whitespace helpers are not used.

## Functions

The complete v1.0 set. All functions are pure and total. Arguments are evaluated eagerly, with one exception: `if` evaluates only the taken branch, like `&&`, `||`, and `??`.

| Function | Signature | Notes |
|---|---|---|
| `str` | scalar to string | Locale-independent formats above |
| `int` | double to int | Truncates toward zero, saturates, reports saturation |
| `double` | int to double | Round-to-nearest |
| `concat` | strings... to string | Two or more arguments |
| `length` | string or array to int | Strings: Unicode scalar count |
| `isEmpty` | string or array to bool | |
| `contains` | string, string to bool | |
| `startsWith` | string, string to bool | |
| `endsWith` | string, string to bool | |
| `trim` | string to string | Removes leading and trailing Unicode whitespace |
| `if` | bool, T, T to T | Both branches type-check to exactly the same T, optionality included: a `T?` branch beside a `T` branch is rejected (resolve the optional with `??` first), a single `null` branch makes T optional, and two `null` branches are rejected (no T to infer); only the taken branch is evaluated, observable as the absence of the untaken branch's arithmetic reports |

There are no regular expressions in v1.0: string validation beyond these functions belongs to the producer or the host. There are no case-mapping functions in v1.0: case rules are locale-sensitive and belong to renderers.

## Typing and totality

- Every expression has a static type, determined at the gate from literals, declared state and context types, event payload and action result types, operator rules, and function signatures. A property expression must type-check to the property's declared type; mismatches are a `SchemaViolation` at the gate.
- A non-optional `T` is accepted wherever an optional `T` is expected; the reverse never holds. An `int` expression is accepted wherever a `double` is expected, and its value is promoted to `double` at evaluation, exactly as an `int` literal or data value is (document model spec); a `double` is never accepted where `int` is expected.
- Both acceptances apply where a declared type meets an expression: property values, `$set` values, and action parameters. Neither applies between the two branches of `if`, which must have exactly the same type, optionality included, with the one exception the function table grants: a single `null` branch beside a `T` branch makes the result `T?`. Otherwise a producer resolves the optional branch with `??` first.

Enum types follow four rules, all enforced at the gate:

- **Refinement.** The expected type propagates into `if` branches and both sides of `??`. A string literal in an enum position (a property value, `$set` value, action parameter, or a propagated branch of one) must be a member of that enum and takes the enum type; a non-member is a `SchemaViolation`. Everywhere else a string literal is a plain `string`.
- **Strictness.** An enum position accepts member literals and expressions of the same enum type only; an expression of type `string` is a `SchemaViolation` there. Two enum types are the same exactly when their member sets are equal, and expressions over distinct enums never mix.
- **Widening.** An enum value is accepted wherever a `string` is expected: string functions (`concat`, `str`, `length`, `isEmpty`, and the rest), `+` concatenation, and `string`-declared positions. Widening is one-way.
- **Comparison.** `==` and `!=` between an enum and a string literal require the literal to be a member (the typo fails the gate instead of evaluating to a silently constant `false`); between two enums they require the same enum type; between an enum and a non-literal `string` expression they compare by string value. Ordering operators never accept enums.
- After the gate: no type errors (static), no null dereference (the `??` rule), no division failures (defined results), no overflow traps (wrapping and saturation). Evaluation is total. The conformance suite includes vectors for every boundary in this section.
