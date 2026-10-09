# Backend code style

These conventions apply to `hcsp_typechecker/backend`. They provide a consistent
reading structure for shared rules, TypeConstructor, TypeChecker, and Table 3
operational semantics while preserving their separate responsibilities.

## Module structure

Organize each backend module in this order:

1. Module docstring describing responsibilities, inputs, outputs, and dependency boundaries.
2. Future annotations.
3. Standard-library imports, domain data structures, and relative backend imports.
4. Private helper records.
5. Core classes or pure function entry points, with public entries before private implementation.
6. Low-level helpers and an explicit `__all__`.

`data_structures` must not import backends. `backend/common` must not import either
business backend, and the construction and checking backends must not import each other.

`type_operational_semantics` consumes existing Type, normalized Type, and graph data
structures. It must not call construction, checking, Gamma/Theta preparation, or
provers. Internal state identity uses cyclic term graphs; normalized ASTs serve as
readable display representatives.

## Naming and type annotations

- Use `construct`/`check` for business entry points and action-based names such as
  `rule_t_*` and `_decide_proof` in the shared layer.
- In Table 3, use `normalize/build/derive/minimize` to distinguish normalization,
  graph construction, one-step derivation, and equi-recursive minimization.
  Data structures themselves do not traverse the rules.
- Annotate function and method parameters and returns; `__init__` explicitly returns `None`.
- Backend dataclasses use `slots=True`. Read-only requests, results, and premises
  also use `frozen=True`; explicitly mutable records such as symbolic contexts may remain mutable.
- Place business-specific requests and reports in `backend/<business>/model.py`
  and shared proof evidence in `backend/common/model.py`.

## Comments and layout

- Give modules, classes, and functions concise docstrings. For complex rules,
  explain their paper references, inputs, outputs, normalization boundaries, and
  failure conditions. Avoid restating obvious assignments.
- Use English to explain functions, rule premises, and non-obvious implementation
  choices. Avoid
  duplicating definition templates and docstrings. Preserve formal rule names,
  Python identifiers, and FOL/dL terminology. Errors, proof reports, and demo output use English.
- Keep source lines within 100 characters and avoid wildcard imports.
- `result/full` reports belong to the presentation layer. Table 2 rules and Table 3
  transition functions accumulate structured evidence without printing directly.

`tests/backend/test_backend_style.py` and
`tests/backend/test_backend_boundaries.py` enforce these conventions.
