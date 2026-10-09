r"""Build Table 3 transition graphs for parallel, recursive, and timed types.

From the repository root: python examples/demo_type_transition_graph.py
Requires Python/Z3. Exit code 0 means all three graphs were built completely.
The examples illustrate graph rules and can contain lock counterexamples.
The fixtures use internal AST constructors to exercise those rules directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import sys

# Resolve the checkout package when this file is run directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hcsp_typechecker import (
    HCSPTypeTransitionGraphError,
    TypeAST,
    build_type_transition_graph,
)
from hcsp_typechecker.data_structures.type_ast import (
    EmptyType,
    FiniteDelayType,
    InfiniteDelayType,
    InputType,
    InternalChoiceType,
    MuType,
    NoInterruptType,
    OutputType,
    ParallelType,
    TypeVar,
    format_type_source,
    make_external_choice,
)


# Use "result" or "full" to select graph display verbosity.
GRAPH_OUTPUT_MODE = "full"


@dataclass(frozen=True, slots=True)
class GraphExample:
    r"""A named Type AST example ready for graph construction."""

    title: str
    purpose: str
    type_ast: TypeAST


def _racing_clients_example() -> GraphExample:
    r"""Model a recursive server competing to synchronize with two identical clients."""

    server = MuType(
        "server_loop",
        InfiniteDelayType(
            InputType("request", TypeVar("server_loop"))
        ),
    )
    client = InfiniteDelayType(OutputType("request", EmptyType()))
    return GraphExample(
        '1. Recursive server with two competing clients',
        (
            'Either client can synchronize with the server on request. Identical clients produce the same edge with two derivations. Equi-recursive states merge the folded server and its unfolding, yielding three states.'
        ),
        ParallelType((server, client, client)),
    )


def _watchdog_protocol_example() -> GraphExample:
    r"""Model a request/reply protocol with a watchdog that can stop the server."""

    server = MuType(
        "server_loop",
        InfiniteDelayType(
            make_external_choice(
                (
                    InputType(
                        "request",
                        FiniteDelayType(
                            2,
                            NoInterruptType(),
                            InfiniteDelayType(
                                OutputType(
                                    "reply",
                                    TypeVar("server_loop"),
                                )
                            ),
                        ),
                    ),
                    InputType("stop", EmptyType()),
                )
            )
        ),
    )
    client = InfiniteDelayType(
        OutputType(
            "request",
            InfiniteDelayType(InputType("reply", EmptyType())),
        )
    )
    watchdog = FiniteDelayType(
        1,
        OutputType("stop", EmptyType()),
        EmptyType(),
    )
    return GraphExample(
        '2. Request/reply server, client, and watchdog',
        (
            'The initial state permits request or stop synchronization. After request, two time steps of duration 1 reach the watchdog deadline at elapsed time 1 and the server deadline at elapsed time 2, followed by reply synchronization and the recursive server.'
        ),
        ParallelType((server, client, watchdog)),
    )


def _choice_and_deadlines_example() -> GraphExample:
    r"""Combine three internal choices, distinct deadlines, and an Empty parallel component."""

    worker = InternalChoiceType(
        (
            FiniteDelayType(
                1,
                OutputType("alarm", EmptyType()),
                InfiniteDelayType(OutputType("done", EmptyType())),
            ),
            FiniteDelayType(
                3,
                OutputType("status", EmptyType()),
                EmptyType(),
            ),
            InfiniteDelayType(OutputType("idle", EmptyType())),
        )
    )
    observer = InfiniteDelayType(InputType("done", EmptyType()))
    return GraphExample(
        '3. Internal choice, staggered deadlines, and the Empty parallel identity',
        (
            'The worker chooses among three behaviors: synchronize on done after time 1, wait until time 3, or wait forever. Normalization removes the Empty component without blocking time progress.'
        ),
        ParallelType((worker, observer, EmptyType())),
    )


def build_examples() -> tuple[GraphExample, ...]:
    r"""Return independent Type AST examples in display order."""

    return (
        _racing_clients_example(),
        _watchdog_protocol_example(),
        _choice_and_deadlines_example(),
    )


def _run_example(example: GraphExample) -> None:
    r"""Display a Type AST and its complete reachable graph."""

    print("\n" + "=" * 76)
    print(example.title)
    print(example.purpose)
    print("-" * 76)
    print('Input Type AST in user syntax:')
    print(format_type_source(example.type_ast))
    print('\nTable 3 transition graph:')
    graph = build_type_transition_graph(
        example.type_ast,
        output=GRAPH_OUTPUT_MODE,
    )
    print(
        '\nGraph summary: '
        f"{len(graph.states)} normalized states, "
        f"{len(graph.transitions)} transitions."
    )


def main() -> int:
    r"""Build complete Table 3 graphs for all three parallel examples."""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if GRAPH_OUTPUT_MODE not in {"result", "full"}:
        print('GRAPH_OUTPUT_MODE must be "result" or "full".')
        return 2

    print('Parallel Type AST -> normalized Type -> Table 3 transition graph demo')
    print(f"Graph output mode: {GRAPH_OUTPUT_MODE!r}")
    try:
        for example in build_examples():
            _run_example(example)
    except HCSPTypeTransitionGraphError:
        # The API already printed the error; only determine the script exit code here.
        return 1

    print("\n" + "=" * 76)
    print('Demo complete: all transition graphs were constructed successfully.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
