# Environment configuration

Follow the [README installation steps](../README.md#installation) to install
the Python package. This guide covers dependency diagnostics and the optional
KeYmaera X backend used for nontrivial differential dynamic logic (dL) proofs.

## Check dependencies

Run from the repository root, using the installed environment's interpreter:

```sh
python -m hcsp_typechecker
```

On Windows, use `.\.venv\Scripts\python.exe` if the environment is not activated.
On Linux/macOS, activate it with `source .venv/bin/activate`.

The doctor checks Python, Z3, Java, and the KeYmaera X jar. It distinguishes:

- `Core type engine ready : yes`: Python and Z3 are available for construction,
  discrete checking, and generation of ODE proof obligations.
- `KeYmaera X ready   : yes`: Java and the configured jar are also available.

By default, missing Java or KeYmaera X is optional. To require both, run:

```sh
python -m hcsp_typechecker --require-keymaerax
```

This command returns a nonzero exit code when a required component is missing.
The doctor checks availability; it does not prove an ODE goal.

For a source-only checkout, `python -m pip install -r requirements.txt` also
installs the Python dependencies. Run source-only commands from the repository
root. Editable installation (`python -m pip install -e .`) additionally makes
the package importable from other directories.

## Configure KeYmaera X

Install Java 17+ and obtain the jar from the
[official KeYmaera X download page](https://keymaerax.org/download.html).
The repository does not bundle the jar. Set its path in the shell used to run
the demos.

**Windows PowerShell**

```powershell
$env:KEYMAERAX_JAR = "C:\tools\keymaerax.jar"
$env:KEYMAERAX_JAVA = "C:\tools\jdk-21\bin\java.exe"
$env:KEYMAERAX_TIMEOUT = "180"
.\.venv\Scripts\python.exe -m hcsp_typechecker --require-keymaerax
```

**Linux / macOS**

```sh
export KEYMAERAX_JAR=/opt/keymaerax/keymaerax.jar
export KEYMAERAX_JAVA=/opt/jdk-21/bin/java
export KEYMAERAX_TIMEOUT=180
python -m hcsp_typechecker --require-keymaerax
```

Replace the example paths with your installation paths. These settings apply
to the current shell. If Java is already discoverable through `JAVA_HOME` or
`PATH`, omit `KEYMAERAX_JAVA`.

Java lookup uses `KEYMAERAX_JAVA`, then `JAVA_HOME/bin/java`, then `PATH`.
Without `KEYMAERAX_JAR`, the adapter searches `tools/keymaerax.jar` and
`keymaerax.jar` relative to the current working directory. The adapter supports
legacy and modern CLI styles and uses Z3 as its default arithmetic backend.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `KEYMAERAX_JAR` | KeYmaera X jar path | Local jar discovery |
| `KEYMAERAX_JAVA` | Explicit Java executable | `JAVA_HOME`, then `PATH` |
| `KEYMAERAX_TIMEOUT` | Seconds per external proof | `60` |
| `KEYMAERAX_HOME` | Writable prover configuration root | Java's default home |
| `KEYMAERAX_KEEP_ARTIFACTS` | Retain generated proof files | `false` |
| `KEYMAERAX_ARTIFACTS` | Retained artifact directory | `keymaerax-artifacts` |
| `KEYMAERAX_CLI_STYLE` | `auto`, `legacy`, or `modern` | `auto` |
| `KEYMAERAX_TACTIC` | Proof tactic | `auto` |
| `KEYMAERAX_ARITHMETIC_TOOL` | Arithmetic backend | `Z3` |

`KEYMAERAX_ARTIFACTS` is used when artifact retention is enabled. Boolean
settings accept `true/false`, `yes/no`, `on/off`, or `1/0`. The
`keymaerax_timeout_seconds` argument overrides the timeout for one construction
or checking call; see the [Public API guide](PUBLIC_API_GUIDE.md).

The case-study scripts and `examples/demo_ode_type_round_trip.py` select their own writable, ignored
directories for configuration and proof artifacts and enable artifact retention.
The demos and case studies that invoke ODE proofs set a 180-second per-call timeout.

## Unresolved proofs and diagnostics

Z3 handles expression, state, and first-order logic obligations. KeYmaera X
handles nontrivial dL obligations. Discrete examples and obligations discharged
locally remain usable without the external prover.

When an external proof is required, a missing prover, a timeout, or an
unreliable translation yields `unknown`. Construction may produce a complete
unverified candidate, exposed through `HCSPUntrustedTypeConstructionError`;
checking rejects unresolved proofs. See the
[exception contract](PUBLIC_API_GUIDE.md#8-exception-handling) for structured
handling and the distinction between verified results and candidates.

If an ODE demo cannot complete its proofs:

- Run the doctor with `--require-keymaerax` and correct the reported paths.
- Ensure the prover configuration and artifact directories are writable.
- Inspect full proof output or retained artifacts. Adjust `KEYMAERAX_TIMEOUT`
  for calls that use the environment default; for `examples/demo_type_construction.py` and `examples/demo_ode_type_round_trip.py`,
  adjust `KEYMAERAX_TIMEOUT_SECONDS` in `examples/demo_type_construction.py` instead. For case studies,
  adjust the script's `keymaerax_timeout_seconds` argument.

Successful environment diagnostics establish availability, not proof success.
Return to the [quick start](../README.md#quick-start) or
[case studies](../README.md#case-studies) to run the scripts.
