# TypeChecker: checking a supplied Type against the rules

TypeChecker accepts complete input containing Gamma, optional Parameters, Theta,
an annotated HCSP Process, and a supplied Type, in that order. It checks whether
the Type is a conclusion of the implemented Table 2 rules.

The implemented rules include multiple communication slots, continuations owned by
control nodes, a shared full Gamma, read-only parameters, the implicit ODE clock,
two candidates for `ODE;skip`, three-valued proofs, and tail-recursion restrictions.
They are an implementation of the judgments with explicit engineering choices.
[Implementation semantics and the paper's rules](IMPLEMENTATION_SEMANTICS.md)
lists these algorithms and differences. This page focuses on how the checker
consumes the supplied Type; individual formula derivations are covered in the constructor reference.

The implementation is distributed by responsibility:

- `hcsp_typechecker/backend/type_checker/checker.py`: type-directed checking.
- `hcsp_typechecker/backend/common/environment.py`: normalized environments shared with construction.
- `hcsp_typechecker/backend/common/rule_engine.py`: shared Table 2 expansion,
  symbolic states, and proof scheduling.
- `hcsp_typechecker/backend/common/logic.py`, `dl.py`, and `keymaerax.py`: FOL/dL formulas and provers.
- `hcsp_typechecker/backend/type_checker/model.py`: checking requests and reports.

TypeChecker does not import `backend/type_constructor`; both backends share the common layer.

## Public entry point

```python
from hcsp_typechecker import check_hcsp_type

type_ast = check_hcsp_type(source, output="result")
```

The complete signature is:

```text
check_hcsp_type(
    source,
    *,
    source_name="<input>",
    initial_states=None,
    path_condition=True,
    output="none",
    stream=None,
    z3_timeout_ms=5000,
    keymaerax_timeout_seconds=None,
) -> TypeAST
```

On success, the function returns the parsed supplied `TypeAST`. Invalid input
syntax raises `HCSPInputError`. A structural mismatch, failed static premise,
refuted formula, or unresolved proof raises `HCSPTypeCheckingError`.
`output` supports `none`, `result`, and `full`, affecting presentation only.
`initial_states` and `path_condition` have the same meaning as in construction.

The source must contain `gamma`, optional `parameters`, `theta`, `process`, and
`type` in order. `source_name` labels diagnostics. For one component,
`initial_states` is a partial-state mapping; for parallel components, it is a
mapping sequence of the same length and order. `path_condition` is a bool or
expression string. `z3_timeout_ms` and `keymaerax_timeout_seconds` control FOL
and dL proof timeouts. See the [Public API guide](PUBLIC_API_GUIDE.md#4-checker-interface)
for argument constraints and runnable examples.

## Error categories and diagnostics

`HCSPTypeCheckingError` exposes structured evidence:

- `kind`: a `TypeCheckingErrorKind` with value `environment`, `type-mismatch`,
  `rule-application`, `proof-failed`, or `proof-unknown`.
- `phase`: `environment`, `type-matching`, `rule-derivation`, or `proof`.
- `rule` and `location`: the primary failing Table 2 rule and judgment location.
- `details`: all `HCSPErrorDetail` records participating in the final verdict;
  proof details also include the formula kind, formula, and backend explanation.
- `type_mismatch_detected`: whether a structural mismatch was definitely found.
- `type_structure_matched`: `True` for complete consumption, `False` for a
  definite mismatch, and `None` when environment or premise failure prevented completion.

Lexical, syntax, and frontend validation errors use `HCSPInputError`, with source
line, column, and a caret. `result` shows primary evidence; `full` includes the
original input, rule steps, proof formulas, backend explanations, and diagnostics.
Both print before raising, so a caller should avoid printing the same
`format_result()` or `format_full()` again after catching the exception.

## Algorithm

The checker does not call `TypeConstructor.construct` or first construct a
complete Type for a final equivalence comparison. Each judgment carries its
Process fragment, symbolic context, and the supplied Type at that position:

1. Normalize Gamma, Theta, parameters, initial states, and paths with the same
   static checks as construction.
2. Use the current Process node to select rules and the supplied Type to determine
   the required conclusion shape.
3. Immediately dispatch FOL/state/dL premises to the shared proof backend.
4. Pass corresponding supplied Type subtrees to the child judgments.
5. Succeed only when every Type subtree is consumed exactly and every active proof is true.

Step 1 validates every Theta refinement, including unused channels. Unbound names,
non-Bool refinements, and other static expression errors are therefore classified
as `environment` errors before structural Type checking begins.

A `false` proof immediately fails the current rule. An `unknown` proof is retained
while checking continues through the remaining Type structure, so the full report
can describe other matches. If checking completes without a mismatch or other
definite failure, unresolved proofs raise
`HCSPTypeCheckingError(kind="proof-unknown")`. A later mismatch or refuted premise
can take precedence in the final error category. The checker does not
deliver a newly constructed untrusted Type through an exception; its report records
progress through the supplied Type.

An `unknown` result is displayed as `Check result : unverified`. A completely
matched Type structure is reported separately from its unresolved proof status.
Missing Z3 stops translation with `proof-unknown` and no completed rule checking;
a Z3 query failure retains its backend explanation without claiming refutation.
See [Failure recovery](PUBLIC_API_GUIDE.md#87-handling-failures-in-an-application)
for caller actions and the boundary between Type-graph analysis and verified HCSP behavior.

The main rule mappings are:

- Terminal `skip` and an empty sequence tail require `EmptyType` (`empty` in user syntax).
- Assertions, assignments, and intermediate `skip` preserve the checked continuation Type.
- Input/output requires the same-channel `InfiniteDelayType(InputType/OutputType)`
  and checks the communication continuation.
- `if` has exactly two child judgments; an n-ary internal choice has one per
  Process branch. Each user `internal` branch requires parentheses, preserving
  nested rule grouping. The checker uses the current node's arity and source order;
  it neither searches alternative groupings nor applies associativity or commutativity.
- ODE delays must match the annotations, and the source must explicitly provide a
  continuation. The frontend lowers `ODE;Q` to an ODE with `continuation=Q`.
  For `ODE;skip`, `T-\unrhd` requires `BottomType` as the supplied continuation
  and checks only A; `T-\unrhd'` requires a non-bottom continuation and checks both
  A and the actual `skip :: EmptyType`. The supplied continuation shape can reject
  a candidate before its remaining proofs are attempted. A finite non-skip
  continuation uses only the prime rule; infinite delay has no natural timeout.
- An n-ary EventChoice requires the same number of normalized Angelic branches,
  with matching directions, channels, and continuations in order.
- Recursion maintains an alpha correspondence between source variables and supplied
  `MuType` variables; back edges require the corresponding `TypeVar`.
- Parallel Type components must match top-level configurations in count and order.

These checking forms reuse construction's rule expansion, including multiple scalar
slots, the implicit ODE clock, finite ODE boundaries, safety annotations, input
refinement assumptions, output refinement proofs, lazy assignment post-states,
and parallel state ownership.

## Constructor round-trip property

A trusted Type `T` produced by construction should be accepted after canonical
serialization under the same initial states, path, parameters, and proof settings:

```python
from hcsp_typechecker import construct_hcsp_type, check_hcsp_type
from hcsp_typechecker.frontend.type_syntax import format_type_source

constructed = construct_hcsp_type(program_source)
checked = check_hcsp_type(
    program_source + "\n" + format_type_source(constructed)
)
assert checked == constructed
```

Regression tests cover discrete statements, conditionals, n-ary and nested internal
choices, n-ary interrupts, recursion, parallelism, and ODEs. They also reject
reordered choice groups and monitor the full constructor entry point to prevent
checking from becoming construction followed by comparison.
