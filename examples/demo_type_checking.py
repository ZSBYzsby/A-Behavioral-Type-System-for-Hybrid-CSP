r"""Check a correct communication type and reject one with a missing output.

From the repository root: python examples/demo_type_checking.py
Requires Python/Z3. Exit code 0 means both examples matched their expectations,
including a type-mismatch rejection of the deliberately incorrect Type.
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
    HCSPTypeCheckingError,
    TypeCheckingErrorKind,
    check_hcsp_type,
)


OUTPUT_MODE = "result"


# The correct type receives, then sends on ch, then terminates normally.
CORRECT_TYPE_SOURCE = r"""
gamma(x: Int)
theta(ch: channel(value: Int))
process {{
    ch?(x);
    ch!(x)
}}
type forever interrupt angelic {
    ch? -> forever interrupt angelic {
        ch! -> empty
    }
}
"""


# This candidate deliberately omits the output after receiving.
WRONG_TYPE_SOURCE = r"""
gamma(x: Int)
theta(ch: channel(value: Int))
process {{
    ch?(x);
    ch!(x)
}}
type forever interrupt angelic {
    ch? -> empty
}
"""


def _run_case(
    *,
    title: str,
    purpose: str,
    source: str,
    should_pass: bool,
) -> bool:
    r"""Run a checking example and compare its outcome with the expectation."""

    source = dedent(source).strip()
    print("\n" + "=" * 76)
    print(title)
    print(purpose)
    print("-" * 76)
    print('User input:')
    print(source)
    print('\n[TypeChecker] Check the supplied Type against the Process and environments')

    try:
        check_hcsp_type(
            source,
            source_name=f"demo_type_checking:{title}",
            output=OUTPUT_MODE,
        )
    except HCSPInputError as error:

        print(
            'Script outcome: invalid input '
            f"[{error.kind}], at {error.source_name}:{error.line}:{error.column}."
        )
        return False
    except HCSPTypeCheckingError as error:
        print(
            'Script outcome: TypeChecker rejected the supplied Type '
            f"[{error.kind.value}/{error.phase}], "
            f"rule {error.rule or '-'}, judgment location {error.location or '-'}."
        )
        if should_pass:
            return False
        # Require a type-mismatch rejection; environment or proof failures would not exercise
        # this example.
        return error.kind is TypeCheckingErrorKind.TYPE_MISMATCH


    if not should_pass:
        print('Unexpected result: the deliberately incorrect Type passed checking.')
        return False
    return True


def main() -> int:
    r"""Run one positive and one negative checking example."""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    if OUTPUT_MODE not in {"result", "full"}:
        print('OUTPUT_MODE must be "result" or "full".')
        return 2

    print('HCSP TypeChecker public API demo')
    print(f"Output mode: {OUTPUT_MODE!r} (set to 'full' for the complete checking log)")

    results = (
        _run_case(
            title='1. Correct type: ch?(x); ch!(x)',
            purpose='TypeChecker should match both communication actions and accept the Type.',
            source=CORRECT_TYPE_SOURCE,
            should_pass=True,
        ),
        _run_case(
            title='2. Incorrect type: missing ch!(x)',
            purpose='TypeChecker should find a mismatch in the input continuation.',
            source=WRONG_TYPE_SOURCE,
            should_pass=False,
        ),
    )

    passed = sum(results)
    print(f"\nDemo complete: {passed}/2 examples produced the expected result.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
