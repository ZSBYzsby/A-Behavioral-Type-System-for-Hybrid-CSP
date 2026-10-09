# Project documentation index

The root [README](../README.md) covers dependencies, installation, running demos,
and case studies. This directory contains detailed usage and implementation
references for users and readers comparing the code with the paper.

The [Public API guide](PUBLIC_API_GUIDE.md) defines the stable interface contract,
including arguments, result objects, exceptions, and end-to-end examples.
Internal data flow is described in
[Public interface inputs and outputs](PROJECT_FUNCTION_REFERENCE.md#public-interface-inputs-and-outputs).
Each syntax reference maintains its own EBNF and lowering constraints rather than
redefining the output and exception contracts.

To inspect the mathematical operations performed by the code, start with
[Implementation semantics and the paper's rules](IMPLEMENTATION_SEMANTICS.md).
It distinguishes judgments in the paper, implementation data representations, and
engineering extensions, and explains the actual Table 2/3 algorithms.

## Environment and usage

- [Environment configuration, prover setup, and diagnostics](ENVIRONMENT_SETUP.md)
- [Public API guide: calls, results, output modes, and exceptions](PUBLIC_API_GUIDE.md)

## User input

- [Shared parameters, Gamma, Theta, and complete Process syntax](GAMMA_THETA_INPUT_SYNTAX.md)
- [Supplied Type syntax and Type AST round trips](TYPE_INPUT_SYNTAX.md)
- [Process and expression syntax](HCSP_INPUT_SYNTAX.md)

## Type construction, checking, Table 3 graphs, and lock analysis

- [Detailed guide to the four public interfaces](PUBLIC_API_GUIDE.md)
- [Implementation semantics and the paper's rules](IMPLEMENTATION_SEMANTICS.md)
- [TypeConstructor: constructing a Type AST from a Process AST](TYPE_CONSTRUCTOR.md)
- [TypeChecker: checking a supplied Type against the rules](TYPE_CHECKER.md)
- [Interface 3: normalized Types, cyclic term graphs, and Table 3 transition graphs](TYPE_OPERATIONAL_SEMANTICS.md)
- [Interface 4: lock freedom, Bottom errors, and behavioral correctness](TYPE_LOCK_ANALYSIS.md)
- [Read-only normalized Type output syntax](NORMALIZED_TYPE_OUTPUT_SYNTAX.md)
- [Read-only Table 3 graph output syntax](TYPE_TRANSITION_GRAPH_OUTPUT_SYNTAX.md)
- [Complete project reference](PROJECT_FUNCTION_REFERENCE.md)

## Documentation scope

- This directory documents the current source implementation.
- `examples/` contains the runnable demos, the paper's cases, and their English
  notes. Those files supplement the general syntax and interface documentation here.
