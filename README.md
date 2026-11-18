# QNX Boot Delta

**Review what a change does to the declared QNX 8 startup sequence.**

Boot Delta is a working host-side Python tool that compares two startup configurations. It surfaces changed command order, readiness waits, timeout declarations, inherited environment, execution modifiers, and foreground/background settings. Command-level findings retain the original source locations and before/after declarations.

Its focus is change review. A line diff can show that a global setting moved; Boot Delta shows the modeled launches affected by that setting. Optional project contracts make specific requirements executable in CI, such as retaining a serial-device wait before a consumer launch.

The project was created on November 18, 2026. It uses Python's standard library and requires no QNX SDK, target hardware, paid service, or network access to run.

## Try the working example

Requirements: Python 3.10 or newer. From this directory, run:

```bash
python -m bootdelta examples/baseline.build examples/changed.build --policy examples/review-policy.json --html reports/changed.html --json reports/changed.json
```

Open `reports/changed.html` in a browser. The report has priority filters, text search, an ordered startup comparison, source links, effective command settings, and visible coverage limits. JSON carries the same configuration observations for other tools.

The command returns **1**, because the changed fixture violates the supplied review policy. Its recognized built-in wait ceilings change from **10 to 17 seconds**. That number is a sum of configured timeout declarations, **not measured boot time**.

Now compare the corrected configuration:

```bash
python -m bootdelta examples/baseline.build examples/corrected.build --policy examples/review-policy.json --html reports/corrected.html --json reports/corrected.json
```

This returns **0**, with no modeled startup differences or contract failures. The example deliberately restores the baseline's declared behavior; it is not evidence that a QNX target boots.

To see incomplete coverage handled explicitly:

```bash
python -m bootdelta examples/baseline.build examples/incomplete.build --html reports/incomplete.html
```

This returns **2**. The external `waitfor` executable is not assumed to have internal-command semantics.

## What the tool does

- Reads a documented subset of inline `[+script]` buildfile bodies or standalone startup script text.
- Keeps declaration order and effective environment/modifier settings across supported sections.
- Matches unchanged commands, uniquely identifiable changed waits, and uniquely identifiable changed command names. Ambiguous duplicate edits remain explicit additions/removals with explanatory notes.
- Distinguishes internal `waitfor`/`reopen` from commands using `+external` or executable paths.
- Adds recognized internal timeout ceilings, including documented defaults, while identifying excluded commands.
- Evaluates explicit project contracts for a maximum configured wait sum and an earlier internal `waitfor` before a named consumer.
- Produces terminal, JSON, and interactive offline HTML reports.

## Input and project roots

Buildfile mode is the default. For bare startup scripts:

```bash
python -m bootdelta old.bsh new.bsh --script
```

Relative line-local `[+include]` paths resolve against an explicit project root, which represents the `mkifs` working directory. Each input defaults to its own parent directory. Set separate roots when comparing two checkouts:

```bash
python -m bootdelta old/board.build new/board.build --before-root old --after-root new
```

No ambient environment variables or SDK search paths are imported. Included files must resolve inside their project boundary. Input bytes, file count, include depth, line length, and command count are bounded. The analyzer never executes source commands or substitutions.

## Explicit review contracts

```json
{
  "version": 1,
  "max_configured_wait_seconds": 12,
  "require_barriers": [
    {"path": "/dev/ser1", "before_command": "telemetry-agent"}
  ]
}
```

`before_command` matches the exact parsed command name. Every occurrence must have an earlier foreground internal `waitfor` for the stated path, with a supported timeout. An external or background wait does not satisfy that contract. A required command that is absent is reported. A wait may time out; this contract checks declarations and order, not successful readiness or runtime enforcement.

## CI behavior

| Exit | Meaning |
|---|---|
| `0` | No finding reaches the chosen priority threshold; supported analysis coverage is complete. |
| `1` | A finding reaches the chosen threshold. This requests review; it is not a proven runtime defect. |
| `2` | Input, policy, output, or coverage problem prevents a complete supported analysis. |

The default threshold is `--fail-on high`. Use `medium`, `low`, or `never` to change the finding threshold. `never` still returns 2 for incomplete coverage. Reports are written even when findings return 1 or coverage returns 2, provided output paths are valid.

The optional install path is `python -m pip install --no-build-isolation .`; running from the checkout needs no installation. Installation tooling may need locally available setuptools. The runtime has no third-party dependencies.

## Validation and limits

```bash
python -m unittest discover -s tests
```

Tests exercise actual parser, comparison, policy, reporting, and CLI behavior. They include independent adversarial cases for scope, includes, ambiguous duplicates, unsupported input, nonfinite timeouts, source-text escaping, and output/input aliasing. The packaged validation report records the executed suite, environment, and integration outputs.

Validation used a Linux host and original synthetic configuration fixtures. **No QNX SDP compilation, `mkifs` acceptance, QEMU run, hardware execution, or measured boot improvement is claimed.** The supplied buildfiles are illustrative startup fragments, not complete BSPs or executable images. Referenced QNX binaries are not distributed.

The tool intentionally excludes image-file inventory, executable resolution, runtime behavior, and unsupported syntax. External script payloads, unresolved host expansions, opaque nested shell behavior, and other unsupported constructs produce coverage markers. Read [the supported-syntax contract](docs/SUPPORTED_SYNTAX.md) before relying on a report. “Complete” always means complete within this documented subset.

## Project contents

| Path | Purpose |
|---|---|
| `bootdelta/` | Original parser, semantic comparator, policies, CLI, and report renderer. |
| `examples/` | Baseline, changed, corrected, and incomplete synthetic fixtures. |
| `tests/` | Behavioral and adversarial tests. |
| `reports/` | Generated examples and executed validation evidence. |
| `docs/` | Supported syntax and a reproducible review tutorial. |
| `demo/` | Demonstration video, captions, and a record of what was shown. |

## QNX connection and sources

The tool specifically models the QNX 8 startup language, not a general POSIX shell. The relevant implementation is in `parser.py`, `compare.py`, and `policy.py`; the fixtures and their reports expose that behavior for review.

- [QNX 8 mkifs reference](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkifs.html)
- [QNX 8 mkxfs variable processing](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkxfs.html)
- [QNX 8 startup script guide](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.building/topic/buildfiles/nto_script.html)
- [QNX 8 buildfile syntax](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.building/topic/buildfiles/buildfile_syntax.html)

The code and illustrative fixtures are original work prepared with substantial AI assistance at the user's direction. No competitor implementation was copied. No personal hand-coding by the entrant is asserted. The MIT license covers this project's original code and documentation; QNX marks and linked vendor documentation belong to their respective owners. This is an independent project, not an endorsed QNX product.
