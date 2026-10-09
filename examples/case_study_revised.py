r"""Run the revised paper's Section 5 case through construction, graphs, and lock analysis.

From the repository root: python examples/case_study_revised.py --d 1
Requires Python/Z3 and configured Java/KeYmaera X.

Expected results (--d 1; physical parameters remain symbolic):
- Stage 1: a trusted Type AST with all required proof obligations verified.
- Stage 2: a complete reachable graph with 8 states and 8 transitions.
- Stage 3: deadlock_free, livelock_free, and lock_free are all True.
  The report also shows error_free=True and behavior_correct=True.

Exit code 0 requires successful type construction, a complete graph, and
lock freedom. error_free and behavior_correct are reported separately and
do not determine the exit code. See case_study_revised.txt for the revised
safety conditions and verification stages.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import os
from pathlib import Path
import sys
from typing import Sequence

# Add the checkout root before imports when running this file directly.
EXAMPLES_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = EXAMPLES_DIRECTORY.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPTypeTransitionGraphError,
    HCSPTypeLockAnalysisError,
    HCSPUntrustedTypeConstructionError,
    build_type_transition_graph,
    analyze_type_lock_freedom,
    construct_hcsp_type,
)


PARAMETER_ASSUMPTIONS = (
    "end >= 0 and vmax >= 0 and amin < 0 and amax >= 0"
)
ARTIFACTS_DIRECTORY = (
    EXAMPLES_DIRECTORY / "tmp" / "general-case-keymaerax-artifacts"
)
KEYMAERAX_HOME_DIRECTORY = (
    EXAMPLES_DIRECTORY / "tmp" / "general-case-keymaerax-home"
)

# Set to "full" to include proof formulas and rule traces.
OUTPUT_MODE = "result"

# Set to "full" to display all states, labels, and Table 3 evidence.
GRAPH_OUTPUT_MODE = "result"

# Set to "full" to display reachable prefixes and lock witnesses.
LOCK_ANALYSIS_OUTPUT_MODE = "result"


def _number_text(value: Fraction) -> str:
    r"""Render an exact rational in the input expression syntax."""

    if value.denominator == 1:
        return str(value.numerator)
    return f"({value.numerator}/{value.denominator})"


def position_safety(position: str) -> str:
    r"""Return the position safety condition for symbolic physical parameters."""

    return f"({position}) <= end"


def velocity_safety(position: str, velocity: str) -> str:
    r"""Return the division-free, three-part velocity safety condition."""

    remaining = f"(end - ({position}))"
    braking_capacity = f"((-2 * amin) * {remaining})"
    maximum_speed_square = "(vmax * vmax)"
    return (
        f"((({position}) >= end and ({velocity}) <= 0) or "
        f"({braking_capacity} >= {maximum_speed_square} and "
        f"({velocity}) <= vmax) or "
        f"(0 < {remaining} and "
        f"{braking_capacity} < {maximum_speed_square} and "
        f"(({velocity}) <= 0 or "
        f"({velocity}) * ({velocity}) <= {braking_capacity})))"
    )


def acceleration_safety(
    position: str,
    velocity: str,
    acceleration: str,
    period: Fraction,
) -> str:
    r"""Include endpoint and interior turning-point checks in the acceleration condition."""

    duration = _number_text(period)
    predicted_position = (
        f"(({position}) + ({velocity}) * {duration} + "
        f"({acceleration}) * {duration} ** 2 / 2)"
    )
    predicted_velocity = f"(({velocity}) + ({acceleration}) * {duration})"
    turning_point_safe = (
        f"(({acceleration}) >= 0 or "
        f"({velocity}) <= 0 or "
        f"({predicted_velocity}) > 0 or "
        f"({velocity}) * ({velocity}) <= "
        f"-2 * ({acceleration}) * (end - ({position})))"
    )
    return (
        f"(amin <= ({acceleration}) and "
        f"({acceleration}) <= amax and "
        f"{position_safety(predicted_position)} and "
        f"{velocity_safety(predicted_position, predicted_velocity)} and "
        f"{turning_point_safe})"
    )


def build_source(period: Fraction) -> str:
    r"""Build the revised vehicle/controller input with endpoint and turning-point checks."""

    phi_p = position_safety("p")
    phi_v = velocity_safety("p", "v")
    phi_a = acceleration_safety("p", "v", "a", period)
    ode_safety = f"({phi_p}) and ({phi_v})"
    loop_invariant = f"({ode_safety}) and ({phi_a})"
    received_acceleration_is_safe = acceleration_safety(
        "p", "v", "new_acc", period
    )
    maximum_acceleration_is_safe = acceleration_safety(
        "x", "y", "amax", period
    )
    zero_acceleration_is_safe = acceleration_safety(
        "x", "y", "0", period
    )
    duration = _number_text(period)

    # Double braces escape Python f-strings, producing single HCSP braces.
    return f"""
gamma(
    p: Real,
    v: Real,
    a: Real,
    vehicle_ode: continuous(p, v, a),
    command: Real
)

parameters(
    end: Real,
    vmax: Real,
    amin: Real,
    amax: Real
) where(
    {PARAMETER_ASSUMPTIONS}
)

theta(
    ch: channel(position: Real, velocity: Real),
    dh: channel(eta: Real) where(amin <= eta and eta <= amax),
    stop: channel(eta: Int) where(eta == 0)
)

process {{
    {{
        p := 0;
        v := 0;
        a := 0;
        mu X invariant({loop_invariant}) {{
            ode(
                flow(
                    dot p = v,
                    dot v = a,
                    dot a = 0
                ),
                domain(true),
                safety({ode_safety}),
                delay({duration}),
                interrupt(
                    on ch!(p, v) {{
                        ode(
                            flow(),
                            domain(true),
                            safety({ode_safety}),
                            delay(inf),
                            interrupt(
                                on dh?(new_acc) {{
                                    if ({received_acceleration_is_safe}) {{
                                        a := new_acc
                                    }} else {{
                                        a := amin
                                    }};
                                    call X
                                }},
                                on stop?(stop_signal) {{
                                    skip
                                }}
                            )
                            );
                            skip
                        }}
                )
            );
            skip
        }}
    }},
    {{
        mu Y invariant(true) {{
            ch?(x, y);
            if (y >= 0) {{
                if ({maximum_acceleration_is_safe}) {{
                    command := amax
                }} else {{
                    if ({zero_acceleration_is_safe}) {{
                        command := 0
                    }} else {{
                        command := amin
                    }}
                }};
                dh!(command);
                ode(flow(), domain(t < {duration}), delay({duration}));
                call Y
            }} else {{
                stop!(0)
            }}
        }}
    }}
}}
""".strip()


def _positive_fraction(value: str) -> Fraction:
    r"""Parse d as a strictly positive rational ODE annotation."""

    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise argparse.ArgumentTypeError(
            f"invalid rational delay: {value!r}"
        ) from exc
    if result <= 0:
        raise argparse.ArgumentTypeError("d must be a positive rational number")
    return result


def parse_period(argv: Sequence[str] | None = None) -> Fraction:
    r"""Read the concrete period while keeping all four physical parameters symbolic."""

    parser = argparse.ArgumentParser(
        description=(
            "Run the revised paper's case for all admissible end/vmax/amin/amax; "
            "only the annotation delay d is concrete."
        ),
    )
    parser.add_argument("--d", type=_positive_fraction, default=Fraction(1, 1))
    return parser.parse_args(argv).d


def main(argv: Sequence[str] | None = None) -> int:
    r"""Require a trusted type, a complete graph, and a lock-free analysis result."""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    period = parse_period(argv)
    source = build_source(period)

    # Configure prover artifacts only for this script and its child processes.
    os.environ["KEYMAERAX_HOME"] = str(KEYMAERAX_HOME_DIRECTORY)
    os.environ["KEYMAERAX_KEEP_ARTIFACTS"] = "true"
    os.environ["KEYMAERAX_ARTIFACTS"] = str(ARTIFACTS_DIRECTORY)

    print(f"Revised paper case study: d={period}; physical parameters remain symbolic.")
    print("Expected outcome: a trusted Type, a complete graph, and lock freedom.")

    try:
        type_ast = construct_hcsp_type(
            source,
            source_name=(
                f"examples/case_study_revised.py --d {_number_text(period)}"
            ),
            output=OUTPUT_MODE,
            keymaerax_timeout_seconds=180.0,
        )
    except HCSPInputError as error:
        print(
            'Case stopped: invalid input '
            f"[{error.kind}], at {error.source_name}:{error.line}:{error.column}."
        )
        return 1
    except HCSPUntrustedTypeConstructionError as error:
        print(
            (
                'Case failed: the Type is complete but proof obligations remain '
                'unresolved ['
                f'{error.kind.value}'
                '], rule '
                f"{error.rule or '-'}"
                ', location '
                f"{error.location or '-'}"
                '.'
            )
        )
        return 1
    except HCSPTypeConstructionError as error:
        print(
            (
                'Case failed: TypeConstructor failed ['
                f'{error.kind.value}'
                '/'
                f'{error.phase}'
                '], rule '
                f"{error.rule or '-'}"
                ', location '
                f"{error.location or '-'}"
                '.'
            )
        )
        return 1
    print('Stage 1 passed: the Type was constructed and all proof obligations were verified.')

    try:
        graph = build_type_transition_graph(
            type_ast,
            output=GRAPH_OUTPUT_MODE,
        )
    except HCSPTypeTransitionGraphError as error:
        print(
            'Stage 2 failed: could not build the complete transition graph '
            f"[{error.kind.value}/{error.phase}]."
        )
        return 1

    print(
        (
            'Stage 2 passed: a complete transition graph was built from the '
            'trusted Type AST; states: '
            f'{len(graph.states)}'
            ', transitions: '
            f'{len(graph.transitions)}'
            '.'
        )
    )
    try:
        report = analyze_type_lock_freedom(
            graph,
            output=LOCK_ANALYSIS_OUTPUT_MODE,
        )
    except HCSPTypeLockAnalysisError as error:
        print(
            'Stage 3 failed: could not analyze the complete transition graph '
            f"[{error.kind.value}/{error.phase}]."
        )
        return 1
    if not report.lock_free:
        print(
            (
                'Stage 3 failed: a lock counterexample exists; deadlock_free='
                f'{report.deadlock_free}'
                ', livelock_free='
                f'{report.livelock_free}'
                '.'
            )
        )
        return 1
    print('Stage 3 passed: all reachable states are deadlock-free and livelock-free.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
