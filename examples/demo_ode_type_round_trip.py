r"""Construct an ODE's type, serialize it, and verify it with the type checker.

From the repository root: python examples/demo_ode_type_round_trip.py
Requires Python/Z3 and configured Java/KeYmaera X. Exit code 0 requires trusted
construction and checking results with identical Type ASTs.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from textwrap import dedent

# Resolve the checkout package and sibling demo when this file is run directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from examples.demo_type_construction import (
    COMPLEX_ODE_SOURCE,
    KEYMAERAX_TIMEOUT_SECONDS,
)
from hcsp_typechecker import (
    HCSPInputError,
    HCSPTypeConstructionError,
    HCSPTypeCheckingError,
    HCSPUntrustedTypeConstructionError,
    check_hcsp_type,
    construct_hcsp_type,
)
from hcsp_typechecker.frontend.type_syntax import format_type_source


OUTPUT_MODE = "result"

# Use ignored, writable checkout directories for prover configuration and retained artifacts.
KEYMAERAX_HOME_DIRECTORY = PROJECT_ROOT / ".keymaerax-home" / "type-demo"
KEYMAERAX_ARTIFACTS_DIRECTORY = (
    PROJECT_ROOT / ".keymaerax-artifacts" / "type-demo"
)


def main() -> int:
    r"""Require a trusted construction result and an identical checked Type AST."""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    if OUTPUT_MODE not in {"result", "full"}:
        print('OUTPUT_MODE must be "result" or "full".')
        return 2

    process_source = dedent(COMPLEX_ODE_SOURCE).strip()
    os.environ["KEYMAERAX_HOME"] = str(KEYMAERAX_HOME_DIRECTORY)
    os.environ["KEYMAERAX_KEEP_ARTIFACTS"] = "true"
    os.environ["KEYMAERAX_ARTIFACTS"] = str(
        KEYMAERAX_ARTIFACTS_DIRECTORY
    )
    print('HCSP TypeConstructor -> TypeChecker round-trip demo')
    print('Example: the sixth, complex ODE from examples/demo_type_construction.py')
    print(f"Output mode: {OUTPUT_MODE!r}")

    print("\n" + "=" * 76)
    print('Stage 1: construct a Type from user HCSP input')
    print("-" * 76)
    try:
        constructed_type = construct_hcsp_type(
            process_source,
            source_name="demo_ode_type_round_trip:constructor",
            output=OUTPUT_MODE,
            keymaerax_timeout_seconds=KEYMAERAX_TIMEOUT_SECONDS,
        )
    except HCSPInputError as error:

        print(
            (
                'Stage 1 stopped: invalid input ['
                f'{error.kind}'
                '], at '
                f'{error.source_name}'
                ':'
                f'{error.line}'
                ':'
                f'{error.column}'
                '.'
            )
        )
        return 1
    except HCSPUntrustedTypeConstructionError as error:
        # This round trip requires a trusted Type; unresolved candidates cannot proceed as
        # verified input.
        print(
            (
                'Stage 1 failed: only a complete, unverified, untrusted Type '
                'candidate is available ['
                f'{error.kind.value}'
                '], rule '
                f"{error.rule or '-'}"
                ', judgment location '
                f"{error.location or '-'}"
                '.'
            )
        )
        return 1
    except HCSPTypeConstructionError as error:
        print(
            (
                'Stage 1 failed: TypeConstructor did not produce a trusted Type ['
                f'{error.kind.value}'
                '/'
                f'{error.phase}'
                '], rule '
                f"{error.rule or '-'}"
                ', judgment location '
                f"{error.location or '-'}"
                '.'
            )
        )
        return 1

    type_source = format_type_source(constructed_type)
    print('\nGenerated Type section to be passed to TypeChecker:')
    print(type_source)

    typed_source = process_source + "\n" + type_source
    print("\n" + "=" * 76)
    print('Stage 2: check the generated Type with TypeChecker')
    print("-" * 76)
    try:
        checked_type = check_hcsp_type(
            typed_source,
            source_name="demo_ode_type_round_trip:checker",
            output=OUTPUT_MODE,
            keymaerax_timeout_seconds=KEYMAERAX_TIMEOUT_SECONDS,
        )
    except HCSPInputError as error:
        print(
            (
                'Stage 2 stopped: invalid input with Type ['
                f'{error.kind}'
                '], at '
                f'{error.source_name}'
                ':'
                f'{error.line}'
                ':'
                f'{error.column}'
                '.'
            )
        )
        return 1
    except HCSPTypeCheckingError as error:
        print(
            (
                'Stage 2 failed: TypeChecker rejected the constructed Type ['
                f'{error.kind.value}'
                '/'
                f'{error.phase}'
                '], rule '
                f"{error.rule or '-'}"
                ', judgment location '
                f"{error.location or '-'}"
                '.'
            )
        )
        return 1

    if checked_type != constructed_type:
        print('Round trip failed: the checked Type AST differs from the constructed Type.')
        return 1

    print("\n" + "=" * 76)
    print('Round trip succeeded: TypeChecker fully verified the constructed Type.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
