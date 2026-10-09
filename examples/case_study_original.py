r"""Run the original paper's Section 5 case and report its unverified candidate type.

From the repository root: python examples/case_study_original.py --d 1
Requires Python/Z3 and configured Java/KeYmaera X.

Expected results (--d 1; physical parameters remain symbolic):
- Construction produces a complete candidate Type AST but raises
  HCSPUntrustedTypeConstructionError with kind="proof-unknown".
- The candidate is available as error.untrusted_type. The unresolved ODE
  safety proof is reported under T-ODE-safety at K1.X.
- No transition graph or lock-freedom analysis is performed.

Exit code 0 means the expected unverified candidate was reproduced; it does
not certify safety. See case_study_original.txt for the mathematical
counterexample and interpretation of the unresolved proofs.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import os
from pathlib import Path
import sys
from typing import Sequence


# Add the checkout root so this script also runs without package installation.
_EXAMPLES_DIRECTORY = Path(__file__).resolve().parent
_PROJECT_ROOT = _EXAMPLES_DIRECTORY.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hcsp_typechecker import (  # noqa: E402 - resolve the checkout root before importing the package
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPUntrustedTypeConstructionError,
    TypeConstructionErrorKind,
    construct_hcsp_type,
)


PARAMETER_CONSTRAINT = (
    "end >= 0 and vmax >= 0 and amin < 0 and amax >= 0"
)
_KEYMAERAX_HOME = _EXAMPLES_DIRECTORY / "tmp" / "paper-case-unknown-home"
_KEYMAERAX_ARTIFACTS = (
    _EXAMPLES_DIRECTORY / "tmp" / "paper-case-unknown-artifacts"
)

# Set to "full" to include proof formulas and rule traces.
OUTPUT_MODE = "result"


def _number_text(value: Fraction) -> str:
    r"""Render an exact positive rational in the input expression syntax."""

    if value.denominator == 1:
        return str(value.numerator)
    return f"({value.numerator}/{value.denominator})"


def _position_safety(position: str) -> str:
    r"""Generate the paper's position condition phi_p."""

    return f"({position}) <= end"


def _velocity_safety(position: str, velocity: str) -> str:
    r"""Generate the three-part velocity condition without introducing division."""

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


def _acceleration_safety(
    position: str,
    velocity: str,
    acceleration: str,
    period: Fraction,
) -> str:
    r"""Generate the original one-step prediction without endpoint or turning-point position
    checks.
    """

    duration = _number_text(period)
    predicted_position = (
        f"(({position}) + ({velocity}) * {duration} + "
        f"({acceleration}) * {duration} ** 2 / 2)"
    )
    predicted_velocity = (
        f"(({velocity}) + ({acceleration}) * {duration})"
    )
    return (
        f"(amin <= ({acceleration}) and "
        f"({acceleration}) <= amax and "
        f"{_velocity_safety(predicted_position, predicted_velocity)})"
    )


def _build_original_case_source(period: Fraction) -> str:
    r"""Build the original vehicle/controller input with endpoint-only phi_a."""

    phi_p = _position_safety("p")
    phi_v = _velocity_safety("p", "v")
    phi_a = _acceleration_safety("p", "v", "a", period)
    ode_safety = f"({phi_p}) and ({phi_v})"
    loop_invariant = f"({ode_safety}) and ({phi_a})"
    received_acceleration_is_safe = _acceleration_safety(
        "p",
        "v",
        "new_acc",
        period,
    )
    maximum_acceleration_is_safe = _acceleration_safety(
        "x",
        "y",
        "amax",
        period,
    )
    zero_acceleration_is_safe = _acceleration_safety(
        "x",
        "y",
        "0",
        period,
    )
    duration = _number_text(period)

    # Double braces escape the f-string; generated HCSP uses single braces.
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
    {PARAMETER_CONSTRAINT}
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
    r"""Parse --d as a strictly positive rational ODE annotation."""

    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise argparse.ArgumentTypeError(
            f"invalid rational delay: {value!r}"
        ) from exc
    if result <= 0:
        raise argparse.ArgumentTypeError("d must be a positive rational number")
    return result


def _parse_period(argv: Sequence[str] | None = None) -> Fraction:
    r"""Read the concrete period while keeping the four physical parameters symbolic."""

    parser = argparse.ArgumentParser(
        description=(
            "Reproduce the original Section 5 dL issue for all admissible "
            "end/vmax/amin/amax; only annotation d is concrete."
        ),
    )
    parser.add_argument("--d", type=_positive_fraction, default=Fraction(1, 1))
    return parser.parse_args(argv).d


def main(argv: Sequence[str] | None = None) -> int:
    r"""Return success only for the expected complete candidate with unresolved proofs."""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    period = _parse_period(argv)
    source = _build_original_case_source(period)

    # Use the public API's environment configuration with a writable case-specific directory.
    os.environ["KEYMAERAX_HOME"] = str(_KEYMAERAX_HOME)
    os.environ["KEYMAERAX_KEEP_ARTIFACTS"] = "true"
    os.environ["KEYMAERAX_ARTIFACTS"] = str(_KEYMAERAX_ARTIFACTS)

    print(f"Original paper case study: d={period}; physical parameters remain symbolic.")
    print("Expected outcome: a complete, unverified candidate with unresolved proofs.")

    try:
        construct_hcsp_type(
            source,
            source_name=f"examples/case_study_original.py (--d={period})",
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
        if error.kind is not TypeConstructionErrorKind.PROOF_UNKNOWN:
            print('Case stopped: the untrusted-type error violates the exception contract.')
            return 1
        unresolved = sum(
            detail.category == "proof-unknown" for detail in error.details
        )
        print()
        print('=== Original case study outcome ===')
        print(
            'Expected result reproduced: unknown obligations did not stop construction; a complete, unverified candidate Type AST was produced.'
        )
        print(
            (
                'Error kind: '
                f'{error.kind.value}'
                '; unresolved proof details: '
                f'{unresolved}'
                '; primary rule: '
                f"{error.rule or '-'}"
                '; location: '
                f"{error.location or '-'}"
                '.'
            )
        )
        print('The untrusted candidate is shown above in canonical Type source syntax.')
        print("Set OUTPUT_MODE to 'full' to inspect dL formulas and the derivation trace.")
        return 0
    except HCSPTypeConstructionError as error:
        print()
        print('=== Original case study outcome ===')
        print(
            (
                'Unexpected result: construction failed with kind '
                f'{error.kind.value!r}'
                ' without producing the expected complete, untrusted candidate.'
            )
        )
        print(
            (
                'Failure phase: '
                f'{error.phase}'
                '; rule: '
                f"{error.rule or '-'}"
                '; location: '
                f"{error.location or '-'}"
                '.'
            )
        )
        return 1

    print()
    print('=== Original case study outcome ===')
    print('Unexpected result: construction returned a trusted Type AST.')
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
