# Read-only Table 3 transition graph output syntax

`build_type_transition_graph(..., output="full")` prints the complete result as
stable text: the initial state, every normalized state, all transition labels,
and each edge's Table 3 derivation evidence. The formatter supports internal
presentation and review; there is no parser for constructing graphs from this text.

## Interface

```python
from hcsp_typechecker import build_type_transition_graph

graph = build_type_transition_graph(type_ast, output="full")
```

## Output grammar

```ebnf
graph_output
    ::= "type" "transition" "graph" "{"
            "initial" "=" state_id
            states_block
            transitions_block
        "}"

states_block
    ::= "states" "{" state_entry { state_entry } "}"

state_entry
    ::= state_id "=" normalized_type_output

transitions_block
    ::= "transitions" "{}"
      | "transitions" "{" transition { transition } "}"

transition
    ::= state_id "--" transition_label "-->" state_id
        "by" "{" derivation { derivation } "}"

transition_label
    ::= "tau"
      | "time" "(" time_duration ","
            "ready=" "{" [ ready_action { "," ready_action } ] "}"
        ")"

ready_action
    ::= IDENT "?" | IDENT "!"

time_duration
    ::= POSITIVE_INTEGER
      | POSITIVE_INTEGER "/" POSITIVE_INTEGER
      | "infinity"

derivation
    ::= RULE_NAME "(" [ derivation_arguments ] ")"
        [ "{" derivation { derivation } "}" ]

derivation_arguments
    ::= named_argument { "," named_argument }

named_argument
    ::= "components=" index_list
      | "branches=" index_list
      | "channel=" STRING

index_list
    ::= "[" NONNEGATIVE_INTEGER
        { "," NONNEGATIVE_INTEGER } "]"

state_id
    ::= "S" NONNEGATIVE_INTEGER
```

Whitespace and line breaks are not semantic; formatting uses four-space indentation.
`tau` denotes a transition that consumes no time. Ready sets are sorted by channel
name and direction. All derivations of the same graph edge appear in one `by`
block, with recursive or parallel premise evidence nested inside its parent rule.

Indices in `components=[...]` are zero-based positions in the source state's
displayed `normalized_type_output` parallel components. `branches=[...]` similarly
indexes visible internal-choice or Angelic branches. For communication, matching
positions in the two lists identify a participating component and its selected
interrupt branch. Indices do not expose internal term-graph node order; duplicate
parallel components retain separate visible positions.

Current `RULE_NAME` values and evidence are:

- `P-unrhd`: communication synchronization; two components, two Angelic branches, and a channel.
- `P-triangleright`: zero-delay timeout; the component taking the timeout.
- `P-sqcup`: internal choice; the component and selected branch.
- `P-unrhd-prime`: time advancement of one component.
- `P-parallel`: common parallel time advancement; `components` and nested premises have matching order.

`P-mu` is not printed separately. Recursion is compiled into term-graph back edges
as part of state identity. Evidence indices refer to executable components or
branches after leading recursion is unfolded; no administrative unfolding-only
edges are generated.

Each state's `normalized_type_output` follows the
[Read-only normalized Type syntax](NORMALIZED_TYPE_OUTPUT_SYNTAX.md).
Nodes are deduplicated by equi-recursive regular trees, so `mu t.T` and its finite
unfoldings share a `state_id`. The displayed normalized AST is deterministically
generated from the equivalence class's minimal cyclic term graph; it does not
participate in state equality or transition calculation.

## Example

```text
type transition graph {
    initial = S0
    states {
        S0 = normalized type delay(2) then empty
        S1 = normalized type delay(0) then empty
        S2 = normalized type empty
    }
    transitions {
        S0 -- time(2, ready={}) --> S1 by {
            P-unrhd-prime()
        }
        S1 -- tau --> S2 by {
            P-triangleright(components=[0])
        }
    }
}
```

Successful graph output always represents the complete reachable closure. If
`max_states` or `max_transitions` is exceeded, the interface raises
`HCSPTypeTransitionGraphError(kind="size-limit")` without displaying or returning
a partial graph. Its `result/full` error formatter is separate from the successful
graph grammar defined here. `output="result"` also uses a summary rather than
this full grammar: state count, edge count, and the initial normalized Type.
