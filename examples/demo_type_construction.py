r"""Construct behavioral types for six HCSP examples, from skip to timed ODEs.

From the repository root: python examples/demo_type_construction.py
Examples 1-4 need Python/Z3; examples 5-6 need KeYmaera X for ODE proofs.
Exit code 0 allows explicitly reported unverified candidates, but no failures.
Lock-freedom analysis is a separate stage.
"""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

# Resolve the checkout package when this file is run directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPUntrustedTypeConstructionError,
    construct_hcsp_type,
)


# Use "result" or "full" to select display verbosity.
OUTPUT_MODE = "result"

# Examples 5-6 require dL proofs; set the timeout for each external obligation.
KEYMAERAX_TIMEOUT_SECONDS = 180.0


# Share example 6 with the Constructor-to-Checker round-trip demo.
COMPLEX_ODE_SOURCE = r"""
gamma(
    p: Real,
    v: Real,
    new_p: Real,
    new_v: Real,
    motion: continuous(p, v)
)
theta(
    reset: channel(rp: Real, rv: Real)
        where(rp >= 0 and rv >= 0),
    report: channel(out_p: Real, out_v: Real)
        where(out_p >= 0 and out_v >= 0)
)
process {{
    p := 0;
    v := 0;
    ode(
        flow(
            dot p = v,
            dot v = 2
        ),
        domain(t < 3 / 2),
        safety(
            p == t ** 2 and
            v == 2 * t and
            p >= 0 and
            v >= 0
        ),
        delay(3 / 2),
        interrupt(
            on reset?(new_p, new_v) {
                p := new_p;
                v := new_v
            }
        )
    );
    report!(p, v)
}}
"""


EXAMPLES = (
    (
        '1. Minimal program: skip',
        'Empty environments and a process with no actions; the expected Type is empty.',
        """
        gamma()
        theta()
        process {{skip}}
        """,
    ),
    (
        '2. Sequential communication: ch?(x); ch!(x)',
        'Input binding followed by a scalar output on the same channel.',
        """
        gamma(x: Int)
        theta(ch: channel(value: Int))
        process {{ch?(x); ch!(x)}}
        """,
    ),
    (
        '3. Parameters, assignment, conditionals, and refinement',
        'Read-only parameter constraints support assignment, branching, and output refinement proofs.',
        """
        gamma(x: Int)
        parameters(limit: Int) where(limit >= 0)
        theta(out: channel(value: Int) where(value <= limit))
        process {{
            x := limit;
            if (x == limit) {
                out!(x)
            } else {
                skip
            }
        }}
        """,
    ),
    (
        '4. Two independent parallel components',
        'Partition Gamma state ownership and combine two component types into a parallel Type AST.',
        """
        gamma(left_state: Int, right_state: Int)
        theta(
            left: channel(value: Int),
            right: channel(value: Int)
        )
        process {
            {left_state := 1; left!(left_state)},
            {right_state := 2; right!(right_state)}
        }
        """,
    ),
    (
        '5. Finite delay with a communication interrupt',
        'Wait for input for one time unit; t < 1 stops the ODE exactly at the deadline.',
        """
        gamma(x: Int)
        theta(ch: channel(value: Int))
        process {{
            ode(
                flow(),
                domain(t < 1),
                safety(true),
                delay(1),
                interrupt(
                    on ch?(x) {
                        skip
                    }
                )
            );
            skip
        }}
        """,
    ),
    (
        '6. Second-order ODE, multiple payloads, and a timeout continuation',
        "Combine p'=v, v'=2, an implicit clock t, nonlinear safety, delay(3/2), and timed choice.",
        COMPLEX_ODE_SOURCE,
    ),
)


def _run_example(index: int, title: str, purpose: str, source: str) -> str:
    r"""Run one example and classify it as trusted, untrusted, or failed."""

    source = dedent(source).strip()
    separator = "=" * 76
    print(f"\n{separator}")
    print(title)
    print(purpose)
    print("-" * 76)
    print('User input:')
    print(source)

    print('\n[Type construction] User input -> Type AST')
    try:
        construct_hcsp_type(
            source,
            source_name=f"demo-example-{index}.hcsp",
            output=OUTPUT_MODE,
            keymaerax_timeout_seconds=KEYMAERAX_TIMEOUT_SECONDS,
        )
    except HCSPInputError as error:

        print(
            'Script outcome: invalid input '
            f"[{error.kind}], at {error.source_name}:{error.line}:{error.column}."
        )
        return "failed"
    except HCSPUntrustedTypeConstructionError as error:
        # Read structured error fields instead of parsing rendered logs.
        print(
            'Script outcome: type structure is complete but proofs are unresolved '
            f"[{error.kind.value}], {_error_site(error.rule, error.location)}."
        )
        return "untrusted"
    except HCSPTypeConstructionError as error:
        print(
            'Script outcome: type construction failed '
            f"[{error.kind.value}/{error.phase}], "
            f"{_error_site(error.rule, error.location)}."
        )
        return "failed"
    return "trusted"


def _error_site(rule: str, location: str) -> str:
    r"""Summarize the rule and judgment location from structured error fields."""

    return f"rule {rule or '-'}, judgment location {location or '-'}"


def main() -> int:
    r"""Run all examples; invalid input or construction failure gives a nonzero exit code."""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    if OUTPUT_MODE not in {"result", "full"}:
        print('OUTPUT_MODE must be "result" or "full".')
        return 2

    print('HCSP TypeConstructor public API demo')
    print(f"Output mode: {OUTPUT_MODE!r} (set to 'full' for the complete construction log)")

    outcomes = {"trusted": 0, "untrusted": 0, "failed": 0}
    for index, (title, purpose, source) in enumerate(EXAMPLES, start=1):
        outcome = _run_example(index, title, purpose, source)
        outcomes[outcome] += 1

    print(
        (
            '\nDemo complete: trusted types: '
            f"{outcomes['trusted']}"
            ', complete unverified candidates: '
            f"{outcomes['untrusted']}"
            ', construction failures: '
            f"{outcomes['failed']}"
            '.'
        )
    )
    return 0 if outcomes["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
