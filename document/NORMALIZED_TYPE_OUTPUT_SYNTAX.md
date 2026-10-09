# Read-only normalized Type output syntax

Each graph `TypeState` stores a `NormalizedConfigurationType` display representative
deterministically generated from its minimal cyclic term graph. The internal
formatter reuses familiar user Type syntax where possible. Structural changes
have explicit spellings: `normalized type` at the root, flattened internal choices
without rule-grouping parentheses, anonymous recursion as `mu {T}`, and references
as `recursion_position(index)`.

This is **read-only output syntax**. The project does not parse it, accept it as
Type input, or convert normalized Type ASTs back to original Type ASTs.
Supplied Types use the [Original Type input syntax](TYPE_INPUT_SYNTAX.md).

## Usage

```python
from hcsp_typechecker import build_type_transition_graph

graph = build_type_transition_graph(type_ast, output="result")
```

`result` mode prints the initial normalized Type after its summary; `full` mode
uses this syntax for every state. The underlying formatter is an internal
frontend implementation, outside the package-root public API.

The text describes a readable state representative, not state identity. Minimal
cyclic term graphs determine identity, so display trees with different finite
recursion unfoldings may denote one graph state. The public interface merges
these equi-recursive states before displaying them.

## Output grammar

```ebnf
normalized_type_output
    ::= "normalized" "type" configuration_type

configuration_type
    ::= process_type
      | "parallel" "{" process_type { "," process_type } "}"

process_type
    ::= "empty"
      | "bottom"
      | recursion_position
      | "internal" "{" process_type
            "," process_type { "," process_type } "}"
      | "delay" "(" duration ")"
            [ "interrupt" angelic_type ]
            "then" process_type
      | "forever" [ "interrupt" angelic_type ]
      | "mu" "{" process_type "}"

recursion_position
    ::= "recursion_position" "(" NONNEGATIVE_INTEGER ")"

angelic_type
    ::= "angelic" "{" [ communication_branch
            { "," communication_branch } ] "}"

communication_branch
    ::= IDENT "?" "->" process_type
      | IDENT "!" "->" process_type

duration
    ::= NONNEGATIVE_INTEGER
      | NONNEGATIVE_INTEGER "/" POSITIVE_INTEGER
```

Formatting uses four-space indentation. Finite rational delays use reduced
fractions, or integers when the denominator is 1. Normalized internal choices
are flat n-ary nodes, delimited by braces and commas; TypeChecker's original
rule-grouping parentheses are not retained.

`bottom` and `empty` remain distinct. Bottom is unreachable/error behavior with
no timeout, while Empty is reachable normal empty communication behavior and is
removed as the parallel-root identity. `angelic {}` means no communication
interrupts and belongs to a separate syntactic category.

## Anonymous recursion and recursion positions

Normalized ASTs use De Bruijn indices instead of original recursion variable names.
`mu` is therefore an anonymous block, with references displaying their binder positions:

- `recursion_position(0)`: the nearest enclosing `mu`.
- `recursion_position(1)`: the next enclosing `mu`.
- Larger indices continue counting outward.

For example, either of these original spellings:

```text
mu Loop. forever interrupt angelic { ch? -> Loop }
```

or:

```text
mu Again. forever interrupt angelic { ch? -> Again }
```

has this normalized output:

```text
mu {
    forever interrupt angelic {
        ch? -> recursion_position(0)
    }
}
```

In nested recursion, `recursion_position(1)` denotes the second enclosing `mu`
binder counted outward, not a graph state identifier.

## Complete example

```text
normalized type parallel {
    delay(3/2) interrupt angelic {
        reset? -> mu {
            forever interrupt angelic {
                again? -> recursion_position(0)
            }
        },
        report! -> empty
    } then internal {
        empty,
        bottom
    },
    forever
}
```

The text retains familiar `parallel`, `delay`, `angelic`, `internal`, `empty`,
`bottom`, `forever`, and `mu` keywords. Sorting, flattening, deduplication, removal
of parallel identities, and alpha-equivalence normalization are reflected in
branch order, branch count, and recursion positions.

The graph also merges `mu t.T` with `T[mu t.T/t]` as equi-recursive regular trees.
The formatter builds a stable De Bruijn `mu` display tree from the normalized
cyclic term graph rather than reusing the original Type AST. Each state identifier
has one display text, but textual comparison cannot replace the equi-recursive state key.
