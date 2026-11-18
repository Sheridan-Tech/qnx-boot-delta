"""Conservative, offline parser for a documented subset of QNX 8 buildfiles.

Only startup declarations are modeled.  The selected project root is the
mkifs working directory for relative includes; SDK/search-path fallbacks are
not consulted.  No command, substitution, or ambient environment is used.

References: QNX 8 ``mkifs``, ``mkxfs``, Buildfile syntax, and Environment
variables documentation.  This is an independent implementation, not a
replacement for mkifs or a claim that an image will build or boot.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Callable, Iterator

from .model import Command, Coverage, ParsedConfig, SourceRef


MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_INCLUDE_DEPTH = 16
MAX_FILES = 128
MAX_LOGICAL_LINE = 128 * 1024
MAX_COMMANDS = 50_000

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
_BOOL_MODIFIERS = {"critical", "external", "session"}
_VALUE_MODIFIERS = {"argv0", "cpu", "pri"}
_CONTROL_WORDS = {"if", "then", "else", "elif", "fi", "for", "while", "until",
                  "do", "done", "case", "esac", "function"}


@dataclass
class _Line:
    text: str
    raw: str
    start: int
    end: int


@dataclass
class _Token:
    value: str
    raw: str
    unquoted: str
    unresolved: bool = False
    single_quote: bool = False
    odd_escape: bool = False


class _LexError(ValueError):
    pass


def _lex(text: str, *, structural: bool = False, attribute: bool = False) -> list[_Token]:
    """Tokenize without treating quoted operators as shell syntax.

    Double quotes and escaped characters preserve a single argument.  Single
    quotes are retained as a recognizable, explicitly unsupported construct;
    accepting POSIX single-quote semantics silently would overstate coverage.
    """
    tokens: list[_Token] = []
    i = 0
    size = len(text)
    # Square brackets are handled separately as an initial modifier block.
    punctuation = "={}" if structural else "&|;<>()"
    while i < size:
        if text[i].isspace():
            i += 1
            continue
        if text[i] == "#":
            break
        start = i
        value: list[str] = []
        plain: list[str] = []
        quote: str | None = None
        unresolved = single = odd_escape = False
        started = False
        while i < size:
            ch = text[i]
            if quote is None and ch.isspace():
                break
            if ch == "\\":
                if i + 1 >= size:
                    raise _LexError("Trailing escape without a continuation line.")
                escaped = text[i + 1]
                if escaped == "$" and text[i + 2:i + 3] == "{":
                    end = text.find("}", i + 3)
                    if end < 0:
                        raise _LexError("Unclosed escaped variable literal.")
                    value.append(text[i + 1:end + 1])
                    started = True
                    i = end + 1
                    continue
                permitted = '\\"$' + ("]" if attribute else "")
                if escaped not in permitted:
                    odd_escape = True
                    value.append("\\")
                value.append(escaped)
                started = True
                i += 2
                continue
            if quote is not None:
                if ch == quote:
                    quote = None
                else:
                    value.append(ch)
                started = True
                i += 1
                continue
            if ch in ('"', "'"):
                quote = ch
                single = single or ch == "'"
                started = True
                i += 1
                continue
            if ch == "$" and i + 1 < size and text[i + 1] == "{":
                end = text.find("}", i + 2)
                if end < 0:
                    raise _LexError("Unclosed variable reference.")
                piece = text[i:end + 1]
                value.append(piece)
                plain.append(piece)
                unresolved = True
                started = True
                i = end + 1
                continue
            if ch in punctuation:
                if started:
                    break
                value.append(ch)
                plain.append(ch)
                started = True
                i += 1
                break
            # A comment must be separated from the preceding command/token.
            # A # inside a token is retained rather than silently truncating it.
            value.append(ch)
            plain.append(ch)
            started = True
            i += 1
        if quote is not None:
            raise _LexError("Unterminated quotation.")
        tokens.append(_Token("".join(value), text[start:i], "".join(plain),
                             unresolved, single, odd_escape))
    return tokens


def _without_comment(text: str) -> str:
    """Locate a whitespace-delimited comment without stripping quoted #."""
    quote: str | None = None
    escaped = False
    for i, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
        elif quote is not None:
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1].isspace()):
            return text[:i]
    return text


def _continuation(text: str) -> bool:
    content = _without_comment(text)
    if len(content) != len(text) or not text.endswith("\\"):
        return False
    count = len(text) - len(text.rstrip("\\"))
    return bool(count % 2)


def _logical_lines(text: str, *, inline_state: Callable[[], bool] | None = None) -> Iterator[_Line]:
    pending: list[str] = []
    raw: list[str] = []
    start = 1
    for number, physical in enumerate(text.splitlines(), 1):
        # mkifs copies an escaped newline inside an inline payload. It does
        # not join that payload's physical lines. Consult the consumer's
        # current block state after each yield, rather than prejoining input.
        if inline_state is not None and inline_state():
            yield _Line(physical, physical, number, number)
            continue
        if not raw:
            start = number
        raw.append(physical)
        more = _continuation(physical)
        pending.append(physical[:-1] if more else physical)
        if not more:
            yield _Line("".join(pending), "\n".join(raw), start, number)
            pending, raw = [], []
    if raw:
        # Retain the escape so normal lexing reports the incomplete line.
        yield _Line("".join(pending) + "\\", "\n".join(raw), start,
                    start + len(raw) - 1)


class _Parser:
    def __init__(self, path: Path, root: Path, script_mode: bool) -> None:
        self.root = root.resolve()
        self.result = ParsedConfig(input=str(path), root=str(self.root),
                                   mode="script" if script_mode else "buildfile")
        self.total_bytes = 0
        self.seen: set[Path] = set()
        self.active: set[Path] = set()
        self.attributes: dict[str, str | bool] = {}
        self.modifiers: dict[str, str | bool] = {
            "critical": False, "external": False, "session": False,
        }
        self.environment: dict[str, str] = {}
        self.script_count = 0

    def coverage(self, code: str, message: str, source: SourceRef | None = None) -> None:
        self.result.coverage.append(Coverage(code, message, source))

    def _source(self, file: str, line: _Line) -> SourceRef:
        return SourceRef(file, line.start, line.end if line.end != line.start else None)

    def _read(self, path: Path, source: SourceRef | None, depth: int) -> tuple[Path, str, str] | None:
        if depth > MAX_INCLUDE_DEPTH:
            self.coverage("include_depth", f"Include depth exceeds {MAX_INCLUDE_DEPTH}.", source)
            return None
        try:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(self.root).as_posix()
        except ValueError:
            self.coverage("path_outside_root", "Input or include resolves outside the project root; it was not read.", source)
            return None
        except (OSError, RuntimeError) as exc:
            self.coverage("file_unavailable", f"Input or include could not be resolved: {type(exc).__name__}.", source)
            return None
        if resolved in self.active:
            self.coverage("include_cycle", f"Circular buildfile include: {relative}.", source)
            return None
        if resolved in self.seen:
            # mkifs ignores a repeated include.  This known behavior is not a
            # coverage gap and must not duplicate startup commands.
            return None
        if len(self.seen) >= MAX_FILES:
            self.coverage("file_limit", f"Input tree exceeds {MAX_FILES} files.", source)
            return None
        fd: int | None = None
        try:
            # Nonblocking opening plus fstat also excludes FIFOs/devices.
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            fd = os.open(resolved, flags)
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                self.coverage("not_regular_file", f"Not a regular text file: {relative}.", source)
                return None
            if metadata.st_size > MAX_FILE_BYTES:
                self.coverage("file_size_limit", f"File exceeds {MAX_FILE_BYTES} bytes: {relative}.", source)
                return None
            with os.fdopen(fd, "rb") as stream:
                fd = None
                data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES or self.total_bytes + len(data) > MAX_TOTAL_BYTES:
                self.coverage("total_size_limit", "Input exceeds the bounded file/tree byte budget.", source)
                return None
            content = data.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            self.coverage("file_read_error", f"Could not read UTF-8 input {relative}: {type(exc).__name__}.", source)
            return None
        finally:
            if fd is not None:
                os.close(fd)
        if "\x00" in content:
            self.coverage("binary_input", f"Input contains NUL bytes: {relative}.", source)
            return None
        self.total_bytes += len(data)
        self.seen.add(resolved)
        self.result.sources[relative] = content
        return resolved, relative, content

    def _tokens(self, text: str, source: SourceRef, *, structural: bool = False,
                attribute: bool = False) -> list[_Token] | None:
        try:
            tokens = _lex(text, structural=structural, attribute=attribute)
        except _LexError as exc:
            self.coverage("syntax_unmodeled", str(exc), source)
            return None
        if any(t.single_quote for t in tokens):
            self.coverage("single_quotes_unmodeled", "Single-quote parsing is outside the documented double-quoted subset; this line is not modeled.", source)
            return None
        if any(t.odd_escape for t in tokens):
            self.coverage("escape_unmodeled", "An unsupported escape sequence prevents reliable token interpretation.", source)
            return None
        if any(t.unresolved for t in tokens):
            self.coverage("unresolved_variable", "Unquoted ${...} expansion is not resolved; no host environment is read and this line is not modeled.", source)
            return None
        return tokens

    def _bracket(self, text: str, source: SourceRef, *, script: bool) -> tuple[dict[str, str | bool], str] | None:
        text = text.lstrip()
        if not text.startswith("["):
            return {}, text
        quote: str | None = None
        escaped = False
        end: int | None = None
        for i in range(1, len(text)):
            ch = text[i]
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
            elif quote is not None:
                if ch == quote:
                    quote = None
            elif ch in ('"', "'"):
                quote = ch
            elif ch == "]":
                end = i
                break
        if end is None:
            self.coverage("attribute_syntax", "Unclosed attribute/modifier block.", source)
            return None
        remainder = text[end + 1:].lstrip()
        if remainder.startswith("["):
            self.coverage("multiple_attribute_blocks", "QNX requires attributes/modifiers on one line to share one bracket block.", source)
            return None
        tokens = self._tokens(text[1:end], source, attribute=True)
        if tokens is None:
            return None
        attributes: dict[str, str | bool] = {}
        for token in tokens:
            value = token.value
            if value.startswith(("+", "-")):
                name, setting = value[1:], value[0] == "+"
                if not _NAME.fullmatch(name) or (script and name not in _BOOL_MODIFIERS):
                    self.coverage("unsupported_modifier" if script else "attribute_syntax",
                                  f"Unsupported {'modifier' if script else 'attribute'}: {value}.", source)
                    return None
            elif "=" in value:
                name, setting = value.split("=", 1)
                if not _NAME.fullmatch(name) or (script and name not in _VALUE_MODIFIERS):
                    self.coverage("unsupported_modifier" if script else "attribute_syntax",
                                  f"Unsupported {'modifier' if script else 'attribute'}: {name}.", source)
                    return None
                if script and name == "cpu" and not (setting == "*" or re.fullmatch(r"[0-9]+", setting)):
                    self.coverage("modifier_value", "cpu requires a nonnegative index or *.", source)
                    return None
                if script and name == "pri" and not re.fullmatch(r"[0-9]+[fro]?", setting):
                    self.coverage("modifier_value", "pri requires digits and an optional f, r, or o policy.", source)
                    return None
            else:
                self.coverage("attribute_syntax", "Attribute/modifier lacks a boolean sign or name=value form.", source)
                return None
            if name in attributes:
                self.coverage("duplicate_attribute", f"Repeated attribute/modifier {name} is not modeled.", source)
                return None
            attributes[name] = setting
        return attributes, remainder

    def _script_line(self, line: _Line, file: str, *, bootstrap: bool = False) -> None:
        source = self._source(file, line)
        bracket = self._bracket(line.text, source, script=True)
        if bracket is None:
            return
        local_modifiers, remainder = bracket
        tokens = self._tokens(remainder, source)
        if tokens is None:
            return
        if not tokens:
            if not bootstrap:
                self.modifiers.update(local_modifiers)
            return
        if any(any(ch in t.unquoted for ch in "|;<>()`") for t in tokens):
            self.coverage("shell_syntax", "Shell control operators, substitutions, and redirections are not modeled or executed.", source)
            return
        if any(any(ch in t.unquoted for ch in "{}") for t in tokens):
            self.coverage("inline_brace", "Unescaped inline braces are outside the supported startup syntax.", source)
            return
        if any(any(ch in t.unquoted for ch in "*?") for t in tokens):
            self.coverage("wildcard_syntax", "Unquoted wildcard syntax is not expanded; this line is not modeled.", source)
            return
        background = False
        if tokens and tokens[-1].value == "&" and tokens[-1].unquoted == "&":
            tokens = tokens[:-1]
            background = True
        if any("&" in t.unquoted for t in tokens):
            self.coverage("shell_syntax", "Only one final unquoted background marker is supported.", source)
            return
        assignments: dict[str, str] = {}
        cursor = 0
        while cursor < len(tokens):
            token = tokens[cursor]
            # The assignment name itself must not be quoted.
            if not _ASSIGNMENT.match(token.raw):
                break
            key, value = token.value.split("=", 1)
            assignments[key] = value
            cursor += 1
        command_tokens = tokens[cursor:]
        if not command_tokens:
            if background:
                self.coverage("assignment_background", "An environment-only declaration cannot be modeled with a background marker.", source)
                return
            self.environment.update(assignments)
            if not bootstrap:
                self.modifiers.update(local_modifiers)
            return
        if command_tokens[0].value in _CONTROL_WORDS:
            self.coverage("shell_syntax", "Shell branches, loops, and functions are outside QNX startup-script syntax.", source)
            return
        if bootstrap:
            if command_tokens[0].value.rsplit("/", 1)[-1].startswith("procnto") and any(
                key in assignments for key in ("PATH", "LD_LIBRARY_PATH")
            ):
                self.coverage("bootstrap_search_paths", "Local PATH/LD_LIBRARY_PATH on procnto configures runtime search strings; these are not inherited target environment and are not modeled.", source)
            return
        executable = command_tokens[0].value.rsplit("/", 1)[-1]
        if executable in {"sh", "ksh", "bash", "dash", "esh"} and any(
            token.value.startswith("-") and "c" in token.value[1:]
            for token in command_tokens[1:]
        ):
            self.coverage("nested_shell", "A shell command is recorded as one launch; its nested startup effects are not interpreted.", source)
        if len(self.result.commands) >= MAX_COMMANDS:
            if not any(c.code == "command_limit" for c in self.result.coverage):
                self.coverage("command_limit", f"More than {MAX_COMMANDS} startup commands; remaining commands are omitted.", source)
            return
        self.result.commands.append(Command(
            index=len(self.result.commands), argv=[t.value for t in command_tokens],
            modifiers={**self.modifiers, **local_modifiers},
            env={**self.environment, **assignments}, background=background,
            source=source, raw=line.raw,
        ))

    def parse_file(self, path: Path, *, script_mode: bool = False,
                   source: SourceRef | None = None, depth: int = 0) -> None:
        loaded = self._read(path, source, depth)
        if loaded is None:
            return
        resolved, file, text = loaded
        self.active.add(resolved)
        if source is None:
            self.result.input = file
        if script_mode:
            self.script_count += 1
        block: str | None = None
        block_source: SourceRef | None = None
        for line in _logical_lines(text, inline_state=lambda: block is not None):
            ref = self._source(file, line)
            if len(line.text) > MAX_LOGICAL_LINE:
                self.coverage("line_limit", f"Logical line exceeds {MAX_LOGICAL_LINE} characters.", ref)
                continue
            if script_mode:
                self._script_line(line, file)
                continue
            stripped = _without_comment(line.text).strip()
            if block is not None:
                if stripped == "}":
                    block = None
                    block_source = None
                else:
                    # The outer inline-file reader sees closing braces even
                    # within quotes/comments. Do not invent the resulting
                    # script structure after an embedded unescaped delimiter.
                    unescaped_close = False
                    escaped = False
                    for ch in line.text:
                        if escaped:
                            escaped = False
                        elif ch == "\\":
                            escaped = True
                        elif ch == "}":
                            unescaped_close = True
                            break
                    if unescaped_close:
                        self.coverage("inline_delimiter", "An embedded unescaped closing brace changes the inline-file boundary; the remaining body is not modeled.", ref)
                        block = "ignored"
                    elif block in ("script", "bootstrap"):
                        if "\\" in line.text:
                            self.coverage("inline_escape", "Inline-file escapes are a separate parsing layer; this physical line is skipped. A backslash-newline inside inline data is not a line continuation.", ref)
                        else:
                            self._script_line(line, file, bootstrap=block == "bootstrap")
                continue
            if not stripped:
                continue
            if stripped == "}":
                self.coverage("unexpected_close", "Closing inline brace has no opening declaration.", ref)
                continue
            bracket = self._bracket(line.text, ref, script=False)
            if bracket is None:
                # Recover an unmistakable opening inline block conservatively:
                # never accidentally interpret its payload as another buildfile.
                if stripped.endswith("{"):
                    block, block_source = "ignored", ref
                continue
            local, remainder = bracket
            tokens = self._tokens(remainder, ref, structural=True)
            if tokens is None:
                if stripped.endswith("{"):
                    block, block_source = "ignored", ref
                continue
            if not tokens:
                self.attributes.update(local)
                continue
            effective = {**self.attributes, **local}
            values = [t.value for t in tokens]
            if "{" in values:
                if len(values) != 3 or values[1:] != ["=", "{"]:
                    self.coverage("inline_syntax", "Inline payload must begin on the line after a filename = { declaration.", ref)
                    block, block_source = "ignored", ref
                    continue
                if effective.get("include") is True:
                    self.coverage("inline_include", "An inline include is outside the supported include subset.", ref)
                    block = "ignored"
                elif (effective.get("script") is True or "virtual" in effective or "physical" in effective) and effective.get("filter") not in (None, "", "none"):
                    self.coverage("script_filter", "A host filter can transform this startup/bootstrap payload. Filters are never executed and the affected body is not modeled.", ref)
                    block = "ignored"
                elif effective.get("script") is True:
                    if "virtual" in effective or "physical" in effective:
                        self.coverage("conflicting_section", "A section is marked both bootstrap and startup; its body is not modeled.", ref)
                        block = "ignored"
                    else:
                        block = "script"
                        self.script_count += 1
                elif "virtual" in effective or "physical" in effective:
                    block = "bootstrap"
                else:
                    block = "ignored"
                block_source = ref
                continue
            if effective.get("include") is True:
                if len(tokens) != 1 or "=" in tokens[0].value:
                    self.coverage("include_syntax", "Include needs one path, without target=host notation.", ref)
                    continue
                if self.attributes.get("include") is True:
                    # The public docs describe global include mode but its
                    # recursive flag restoration is outside our verified subset.
                    self.coverage("global_include_mode", "Persistent +include mode is outside the verified subset; use a line-local [+include] declaration.", ref)
                    continue
                if effective.get("cd") not in (None, ""):
                    self.coverage("include_cd", "The cd attribute changes host include lookup and is outside the verified subset; this include is not read using the project-root default.", ref)
                    continue
                include_path = Path(tokens[0].value)
                if not include_path.is_absolute():
                    include_path = self.root / include_path
                self.parse_file(include_path, source=ref, depth=depth + 1)
                continue
            if effective.get("script") is True:
                self.coverage("external_script", "External script payload is not followed in buildfile mode; provide it directly with --script or use an inline [+script] body.", ref)
                continue
            # Ordinary image entries are deliberately outside startup scope.
        if block is not None:
            self.coverage("unclosed_inline", "Inline section has no closing brace; parsed observations are incomplete.", block_source)
        self.active.remove(resolved)


def parse_path(path: str | Path, *, root: str | Path | None = None,
               script_mode: bool = False) -> ParsedConfig:
    """Parse a UTF-8 file under a bounded, explicit project root.

    ``path`` follows normal filesystem path semantics.  ``root`` defaults to
    its parent directory.  Relative includes are resolved against ``root``,
    never the process's environment or an SDK installation.  Unsupported or
    inaccessible input returns coverage entries rather than executing input.
    """
    input_path = Path(path).absolute()
    project_root = Path(root).absolute() if root is not None else input_path.parent
    parser = _Parser(input_path, project_root, script_mode)
    parser.parse_file(input_path, script_mode=script_mode)
    if not parser.script_count:
        parser.coverage("no_startup_script", "No supported startup script was found; inventory and target execution are outside scope.")
    return parser.result
