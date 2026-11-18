# Supported analysis contract

Boot Delta 0.1.0 compares startup declarations in a deliberately bounded subset of QNX 8 configuration. “Supported subset complete” refers to the scope below. It is not `mkifs` validation, image validation, or proof of target behavior.

## Two input modes

**Buildfile mode:** extracts explicitly marked inline `[+script]` bodies and supported line-local includes. Ordinary image entries and inline data files are outside the startup comparison. Standalone environment assignments in recognized bootstrap bodies are tracked; bootstrap executable launches are not compared. Local PATH/LD_LIBRARY_PATH declarations on `procnto` affect runtime search configuration outside the model and cause a coverage gap.

**Standalone mode (`--script`):** treats each input as startup script text. This is useful when a buildfile references an external script. The tool does not independently resolve the SDK's file-search environment.

## Modeled declarations

- Ordered commands with source file, physical line, raw text, parsed arguments, and foreground/background declaration.
- Supported script modifiers: `argv0`, `cpu`, `critical`, `external`, `pri`, and `session`. Standalone settings persist; command-local settings affect that command.
- Standalone and command-local environment assignments, including multiple assignments.
- Supported double-quoted arguments, comments, and literal escapes, preserving argument boundaries.
- In standalone scripts and the outer buildfile, supported backslash-newline continuation. Inline script bodies have different outer parsing; backslash-bearing inline payload lines are conservatively omitted with a gap, while following physical lines remain independent.
- Multiple supported startup bodies in declaration order.
- Line-local `[+include] path` entries, using the explicit project root as the `mkifs` working-directory assumption. Relative include paths do not silently switch to the including file's parent.
- Repeated includes are ignored after their first inclusion; cycles produce coverage gaps.

QNX's documented variable processing differs from shell intuition: double-quoted `${...}` and escaped variable markers are preserved as literals in standalone mode. Inline text additionally passes through outer brace/escape handling and has the stricter limits above. Unquoted host expansion is not evaluated. See the [mkxfs variable-processing reference](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkxfs.html).

## Wait model

Only exact internal `waitfor` and `reopen` command names, without `+external`, are modeled as built-in waits. Supported timeouts are nonnegative finite decimal literals at tenths-of-a-second precision; omitted timeouts use the documented default. `reopen`'s omitted path is modeled as `/dev/console`.

The model records a sum of configured maximums. It excludes external/path-qualified wait candidates, background-marked built-in waits, unsupported arity, and unknown/invalid timeout declarations. Each exclusion has an explanation; a partial sum is labeled incomplete. No boot-time bound, successful wait, target scheduling, service health, or launch success is inferred.

## Matching and review priorities

Matching uses exact effective command snapshots first, then unique built-in command/resource-path pairs, then unique remaining executable names. Edited duplicates that cannot be identified uniquely remain source additions/removals. They are not arbitrarily paired by row number. Pure line-number changes and shifts caused only by inserted commands do not become reorders.

High/medium/low levels are review priorities. A removed wait is a documented configuration change; it is not automatically a broken system. Optional project contracts separately express desired declarations and ordering.

## Explicit gaps

Unsupported or uncertain behavior produces coverage entries and CLI exit 2. Examples include:

- Missing, escaping, non-regular, oversized, non-UTF-8, cyclic, or over-limit input files.
- Unresolved host variable expansion, single-quote syntax, unsupported escapes, malformed delimiters, unsupported modifiers, and shell control constructs.
- Persistent global include mode, `cd`-controlled includes, and external script-file payloads encountered through a buildfile.
- Inline escape/delimiter behavior outside the supported subset.
- Filters that transform startup/bootstrap content before parsing.
- Nested shell command effects. An explicitly recognized `sh`/`ksh`-style `-c` launch remains visible, but the nested program is not interpreted.
- Bootstrap runtime search-string behavior outside the environment model.

The parser is not a general validator of image-file attributes. Attributes that do not affect the modeled startup extraction may be outside scope without implying that `mkifs` would accept them. Runtime executable dependencies and behavior are outside scope even when all supported declarations are parsed.

## File handling and output

Defaults cap each input file at 2 MiB, total file data at 8 MiB, files at 128, include nesting at 16, a logical line at 128 KiB, and parsed commands at 50,000. Paths are resolved inside the selected project boundary before reads. No commands, substitutions, or environment interpolation are executed.

Reports intentionally embed analyzed source text. Review them before sharing a report from a private project. Output destinations are checked against analyzed inputs, including existing symlink and hardlink aliases. The tool does not protect against a hostile concurrent process modifying the filesystem while analysis is running.

## Evidence basis

Implementation choices were checked against these primary references on November 18, 2026:

1. [QNX 8 mkifs](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkifs.html): inline files, script files, modifier and attribute scope, include/cd/filter behavior, built-in waits.
2. [QNX 8 mkxfs](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkxfs.html): expansion and quoting.
3. [QNX 8 script guide](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.building/topic/buildfiles/nto_script.html): startup script role.
4. [QNX 8 buildfile syntax](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.building/topic/buildfiles/buildfile_syntax.html): file structure and inline syntax.

These references establish the intended semantics. The implementation has been checked with original synthetic fixtures, not with a licensed `mkifs` differential test suite. The latter remains future validation.
