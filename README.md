# A Behavioral Type System for Hybrid CSP

This repository provides the companion code for *A Behavioral Type System for
Hybrid CSP*. It constructs and checks behavioral types for annotated Hybrid
Communicating Sequential Processes (HCSP), builds type transition graphs, and
analyzes deadlock, livelock, and error termination.

## Dependencies

- Python 3.10–3.13.
- `z3-solver>=4.12,<5`, installed automatically with the package.
- Java 17+ and [KeYmaera X](https://keymaerax.org/download.html) for nontrivial
  ODE proofs. These are optional for the discrete demos.

See the [environment configuration guide](document/ENVIRONMENT_SETUP.md) for
KeYmaera X setup, environment variables, and dependency checks.

## Installation

Clone the repository and create a virtual environment:

```sh
git clone https://github.com/ZSBYzsby/A-Behavioral-Type-System-for-Hybrid-CSP.git
cd A-Behavioral-Type-System-for-Hybrid-CSP
python -m venv .venv
```

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m hcsp_typechecker
```

For the commands below, replace `python` with `.\.venv\Scripts\python.exe`.

**Linux / macOS**

```sh
source .venv/bin/activate
python -m pip install -e .
python -m hcsp_typechecker
```

The environment check should report `Core type engine ready : yes`.
Run the demos from the repository root.

## Quick start

### A minimal example

One process sends the integer `1` on channel `ch`; another receives it as `x`.
The tool constructs their behavioral type, builds its transition graph, and
checks for deadlocks, livelocks, and error termination. This example only needs
Python and Z3.

```python
from hcsp_typechecker import (
    construct_hcsp_type,
    build_type_transition_graph,
    analyze_type_lock_freedom,
)

source = """
gamma(x: Int)
theta(ch: channel(value: Int))
process {{ch!(1)}, {ch?(x)}}
"""

type_ast = construct_hcsp_type(source)
graph = build_type_transition_graph(type_ast)
report = analyze_type_lock_freedom(graph)

print(f"States: {len(graph.states)}, transitions: {len(graph.transitions)}")
print(f"Behavior correct: {report.behavior_correct}")
```

Expected output:

```text
States: 2, transitions: 1
Behavior correct: True
```

The processes synchronize on `ch` and then terminate. `Behavior correct: True`
means the graph is free of deadlocks, livelocks, and reachable error termination.
For detailed type output, use `construct_hcsp_type(source, output="result")`.

### Runnable demos

Run the type-construction demo:

```sh
python examples/demo_type_construction.py
```

It runs six examples, from `skip` and communication to a complex ODE, and prints
the resulting types. Without KeYmaera X, the two ODE examples report unverified
candidates; the discrete examples remain available.

For type checking and transition graphs, run:

```sh
python examples/demo_type_checking.py
python examples/demo_type_transition_graph.py
```

The checking demo accepts a correct type and rejects a deliberately incorrect
one; its final summary should report `2/2` expected results. The graph demo
prints complete graphs for parallel and recursive types with communication deadlines.

After [configuring KeYmaera X](document/ENVIRONMENT_SETUP.md#configure-keymaera-x),
run the ODE construction-and-checking demo:

```sh
python examples/demo_ode_type_round_trip.py
```

## Case studies

The Section 5 case studies from the original and revised paper versions are
provided as separate scripts. Configure KeYmaera X before running them:

```sh
python examples/case_study_original.py --d 1
python examples/case_study_revised.py --d 1
```

- `case_study_original.py` runs the original paper's case and reproduces a
  complete but unverified candidate type. This is the expected outcome. See the
  [original case notes](examples/case_study_original.txt).
- `case_study_revised.py` runs the revised paper's case with strengthened
  acceleration conditions, proves the type, builds its graph, and checks lock
  freedom. See the [revised case notes](examples/case_study_revised.txt).

`--d` sets a positive rational period, such as `1` or `3/2`; physical parameters
remain symbolic. The scripts contain the complete HCSP inputs.

## Documentation

- [Environment configuration](document/ENVIRONMENT_SETUP.md): prover setup,
  environment variables, and diagnostics.
- [Public API guide](document/PUBLIC_API_GUIDE.md): runnable examples, arguments,
  return values, output modes, and exceptions.
- Input syntax: [Gamma, Theta, and parameters](document/GAMMA_THETA_INPUT_SYNTAX.md),
  [HCSP and expressions](document/HCSP_INPUT_SYNTAX.md), and
  [supplied types](document/TYPE_INPUT_SYNTAX.md).
- [Complete documentation index](document/INDEX.md): all usage, syntax,
  algorithm, and implementation guides.

The links above are selected entry points. The complete index lists all topic guides.
