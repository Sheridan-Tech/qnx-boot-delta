"""Conservative source comparisons for QNX 8 startup command streams.

The model contains parsed configuration, not target observations.  In particular,
the timeout sum below is neither measured boot duration nor a boot-time bound.

Semantics checked against QNX SDP 8.0 documentation:
https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkifs.html
https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/w/waitfor.html
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import math
import posixpath
import re
from typing import Any

from .model import Change, Command, Comparison, ParsedConfig, WaitBudget


MKIFS_DOC = (
    "https://www.qnx.com/developers/docs/8.0/"
    "com.qnx.doc.neutrino.utilities/topic/m/mkifs.html"
)
WAITFOR_DOC = (
    "https://www.qnx.com/developers/docs/8.0/"
    "com.qnx.doc.neutrino.utilities/topic/w/waitfor.html"
)
_INTERNAL = frozenset(("display_msg", "procmgr_symlink", "waitfor", "reopen"))
_WAITS = frozenset(("waitfor", "reopen"))
_TIMEOUT = re.compile(r"(?:[0-9]+(?:\.[0-9])?|\.[0-9])\Z")
_TRUE = (True, "true", "+", "1")
_FALSE = (False, "false", "-", "0")


def _builtin(command: Command) -> bool:
    return command.name in _INTERNAL and not command.external


def _barrier(command: Command) -> bool:
    return command.name in _WAITS and not command.external


def _modifiers(command: Command) -> tuple[tuple[str, str], ...]:
    """Normalize documented defaults, without guessing priority/CPU defaults."""
    result: dict[str, str] = {}
    for key, value in command.modifiers.items():
        if key in ("external", "critical", "session"):
            if value in _FALSE:
                continue
            if value in _TRUE:
                value = True
        # +external is documented as redundant for non-internal names.
        if key == "external" and command.name not in _INTERNAL:
            continue
        # QNX explicitly says critical does not affect internal commands.
        if key == "critical" and _builtin(command):
            continue
        if key == "argv0" and value == command.name:
            continue
        result[key] = str(value)
    return tuple(sorted(result.items()))


def _wait_values(command: Command) -> tuple[str | None, Decimal | None, bool, str]:
    """Read only the documented built-in grammar; do not emulate mkifs."""
    args = command.args
    if command.name == "waitfor":
        if len(args) not in (1, 2) or not args[0]:
            return None, None, False, "Built-in waitfor requires a path and optional timeout; a polling argument is not supported."
        path = args[0]
    elif command.name == "reopen":
        if len(args) > 2 or (args and not args[0]):
            return None, None, False, "Built-in reopen accepts an optional device path and optional timeout."
        path = args[0] if args else "/dev/console"
    else:
        return None, None, False, "Not a recognized built-in wait."
    defaulted = len(args) < 2
    literal = "5.0" if defaulted else args[1]
    if not _TIMEOUT.fullmatch(literal):
        return path, None, defaulted, "Timeout is outside the supported nonnegative, tenths-of-a-second literal syntax."
    try:
        seconds = Decimal(literal)
        if not math.isfinite(float(seconds)):
            raise ValueError("nonfinite")
    except (InvalidOperation, ValueError, OverflowError):
        return path, None, defaulted, "Timeout cannot be represented as a finite number of seconds."
    return path, seconds, defaulted, ""


def _args_key(command: Command) -> tuple[Any, ...]:
    if _barrier(command):
        path, seconds, _, reason = _wait_values(command)
        if not reason:
            return ("builtin-wait", path, seconds)
    return ("literal", *command.args)


def _signature(command: Command) -> tuple[Any, ...]:
    return (
        command.name,
        _args_key(command),
        _modifiers(command),
        tuple(sorted(command.env.items())),
        command.background,
    )


def wait_budget(config: ParsedConfig) -> WaitBudget:
    """Sum recognized built-in configured wait ceilings, including defaults.

External executables can be shadowed, so even ``[+external] waitfor`` is
excluded.  A background marker on a built-in wait is outside our supported
semantics and is excluded as well.  ``complete`` describes this source-level
inventory only, never overall boot readiness or elapsed startup time.
    """
    result = WaitBudget(complete=not bool(config.coverage))
    total = Decimal("0")
    for command in config.commands:
        name = command.name
        candidate = posixpath.basename(name) in _WAITS
        if not candidate:
            continue
        item: dict[str, Any] = {
            "command_index": command.index,
            "command": name,
            "source": asdict(command.source),
            "path": None,
            "seconds": None,
            "default_timeout": False,
            "included": False,
            "implementation": "builtin" if _barrier(command) else "external",
            "reason": "",
            "documentation": MKIFS_DOC,
        }
        if not _barrier(command):
            item["reason"] = (
                "External executable semantics are unknown from this source; "
                "the resolved target may differ from a standard QNX utility."
            )
            if posixpath.basename(name) == "waitfor":
                item["documentation"] = WAITFOR_DOC
        elif command.background:
            item["reason"] = (
                "A background marker on a built-in wait is outside the supported "
                "semantics; its timeout is excluded from this inventory."
            )
        else:
            path, seconds, defaulted, reason = _wait_values(command)
            item.update(path=path, default_timeout=defaulted, reason=reason)
            if seconds is not None:
                candidate_total = total + seconds
                if math.isfinite(float(candidate_total)):
                    total = candidate_total
                    item.update(seconds=float(seconds), included=True)
                else:
                    item["reason"] = "Adding this timeout would exceed the finite numeric range of the report."
        if not item["included"]:
            result.complete = False
        result.items.append(item)
    result.total_seconds = float(total)
    return result


def _wait_identity(command: Command) -> tuple[str, str] | None:
    """A built-in wait's exact resource path identifies its declaration.

Only the documented reopen default is normalized.  Filesystem paths are not
collapsed or resolved: symlinks can make textual path normalization unsafe.
    """
    if not _barrier(command):
        return None
    path, _, _, _ = _wait_values(command)
    return (command.name, path) if path is not None else None


def _match_commands(
    before: list[Command], after: list[Command]
) -> tuple[dict[int, int], list[str]]:
    """Match exact snapshots, unique built-in wait paths, then edited names.

Repeated identical snapshots use occurrence order.  Multiple unmatched edits
of the same name are deliberately left unpaired: matching those by position
would invent identities when launches have been added, removed, or reordered.
    """
    old: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    new: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for index, command in enumerate(before):
        old[_signature(command)].append(index)
    for index, command in enumerate(after):
        new[_signature(command)].append(index)
    matched: dict[int, int] = {}
    notes: list[str] = []
    for signature, old_positions in old.items():
        new_positions = new.get(signature, [])
        for old_position, new_position in zip(old_positions, new_positions):
            matched[old_position] = new_position
        if max(len(old_positions), len(new_positions)) > 1 and len(old_positions) != len(new_positions):
            notes.append(
                f"Identical occurrences of {before[old_positions[0]].name!r} changed "
                "in count. Occurrences are matched in source order; the identity "
                "of the added or removed occurrence cannot be established."
            )
    # Also explain a new repeated signature with no original occurrences.
    for signature, positions in new.items():
        if signature not in old and len(positions) > 1:
            notes.append(
                f"The new source contains {len(positions)} identical occurrences "
                f"of {after[positions[0]].name!r}; each is retained in the comparison."
            )
    # A changed timeout or inherited environment should not obscure a stable
    # resource check when other waitfor commands have been added or removed.
    # Multiple unmatched checks of the same resource remain ambiguous.
    paired_new = set(matched.values())
    old_waits: dict[tuple[str, str], list[int]] = defaultdict(list)
    new_waits: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, command in enumerate(before):
        identity = _wait_identity(command)
        if index not in matched and identity is not None:
            old_waits[identity].append(index)
    for index, command in enumerate(after):
        identity = _wait_identity(command)
        if index not in paired_new and identity is not None:
            new_waits[identity].append(index)
    for identity, old_positions in old_waits.items():
        new_positions = new_waits.get(identity, [])
        if len(old_positions) == 1 and len(new_positions) == 1:
            matched[old_positions[0]] = new_positions[0]
    paired_new = set(matched.values())
    unmatched_old: dict[str, list[int]] = defaultdict(list)
    unmatched_new: dict[str, list[int]] = defaultdict(list)
    for index, command in enumerate(before):
        if index not in matched:
            unmatched_old[command.name].append(index)
    for index, command in enumerate(after):
        if index not in paired_new:
            unmatched_new[command.name].append(index)
    for name, old_positions in unmatched_old.items():
        new_positions = unmatched_new.get(name, [])
        if len(old_positions) == 1 and len(new_positions) == 1:
            matched[old_positions[0]] = new_positions[0]
        elif old_positions and new_positions:
            notes.append(
                f"Edited occurrences of {name!r} cannot be matched uniquely "
                f"({len(old_positions)} before, {len(new_positions)} after). "
                "They are shown as unmatched source removals/additions; no "
                "one-to-one replacement identity is asserted."
            )
    return matched, notes


def _reordered(matched: dict[int, int]) -> set[int]:
    """Find participants in order inversions, ignoring insert/delete offsets."""
    pairs = sorted(matched.items())
    result: set[int] = set()
    highest = -1
    for old_position, new_position in pairs:
        if new_position < highest:
            result.add(old_position)
        highest = max(highest, new_position)
    lowest = math.inf
    for old_position, new_position in reversed(pairs):
        if new_position > lowest:
            result.add(old_position)
        lowest = min(lowest, new_position)
    return result


def _changed_keys(before: dict[str, Any], after: dict[str, Any]) -> str:
    changes: list[str] = []
    for key in sorted(before.keys() | after.keys()):
        if key not in before:
            changes.append(f"{key} (added)")
        elif key not in after:
            changes.append(f"{key} (removed)")
        elif before[key] != after[key]:
            changes.append(f"{key} (changed)")
    return ", ".join(changes)


def compare_configs(before: ParsedConfig, after: ParsedConfig) -> Comparison:
    """Compare ordered source observations; priority levels are review hints."""
    result = Comparison(
        before=before,
        after=after,
        wait_before=wait_budget(before),
        wait_after=wait_budget(after),
    )
    result.notes.extend([
        "High, medium, and low are review priorities, not proven faults or safety ratings.",
        "The configured wait ceiling sums recognized built-in timeout settings, including the 5.0-second default. It is not measured boot time or a total boot-time bound.",
        "A successful stat() does not establish that a service is fully ready. After a wait timeout, a dependency may still be unavailable.",
        "External executable behavior, foreground process termination, and target hardware state are not established by this source comparison.",
    ])
    matched, matching_notes = _match_commands(before.commands, after.commands)
    result.notes.extend(matching_notes)
    if before.coverage or after.coverage:
        result.notes.append(
            f"Parser coverage gaps: {len(before.coverage)} before and {len(after.coverage)} after. "
            "Changes and configured wait ceilings describe only the recognized source subset."
        )
    if not result.wait_before.complete or not result.wait_after.complete:
        result.notes.append(
            "The wait inventory is incomplete for at least one input. Excluded entries "
            "and parser coverage gaps may hide additional configured waits; the numeric "
            "delta compares recognized subtotals only."
        )
    moved = _reordered(matched)

    def add(code: str, level: str, title: str, detail: str, old: Command | None, new: Command | None) -> None:
        result.changes.append(Change(code, level, title, detail, old, new, MKIFS_DOC))

    for old_position, old in enumerate(before.commands):
        if old_position not in matched:
            if _barrier(old):
                add("barrier_removed", "high", f"Built-in {old.name} removed from recognized source", "Review the lost path check or console reopen. Its removal does not by itself prove a startup fault.", old, None)
            elif _builtin(old):
                add("command_removed", "medium", f"Internal {old.name} removed from recognized source", "The internal command has no matched occurrence in the new recognized source.", old, None)
            else:
                add("launch_removed", "medium", f"Launch of {old.name} removed from recognized source", "This executable has no matched occurrence in the new recognized source; target runtime behavior is unverified.", old, None)
            continue

        new = after.commands[matched[old_position]]
        if old_position in moved:
            barrier_moved = _barrier(old) or _barrier(new)
            add(
                "order_changed", "high" if barrier_moved else "medium",
                f"Relative command order changed for {old.name}",
                "This command reverses order with another matched command. "
                + ("Review which launches occur before and after this path check. " if barrier_moved else "")
                + "Line-number shifts caused only by insertions or deletions are not treated as reordering.",
                old, new,
            )
        mode_changed = old.name in _INTERNAL and old.external != new.external
        if mode_changed:
            add(
                "execution_mode_changed", "high", f"Internal/external interpretation changed for {old.name}",
                "+external resolves an executable on the target filesystem instead of using the built-in command. "
                "External executable semantics are not inferred from its name; built-in wait ceilings cannot be transferred to it.",
                old, new,
            )
        args_changed = old.args != new.args if mode_changed else _args_key(old) != _args_key(new)
        if args_changed:
            if _barrier(old) and _barrier(new):
                add(
                    "wait_configuration_changed", "medium", f"Built-in {old.name} path or timeout changed",
                    "Review the path and configured maximum wait in the before/after source. "
                    "The default timeout is 5.0 seconds; reopen defaults to /dev/console. "
                    "A timeout does not establish that the dependency became ready.",
                    old, new,
                )
            else:
                add("arguments_changed", "medium", f"Arguments changed for {old.name}", "The parsed command arguments differ. Their target-specific behavior has not been executed or validated.", old, new)
        if old.background != new.background:
            add(
                "background_changed", "medium", f"Foreground/background configuration changed for {old.name}",
                "Review the trailing ampersand. An external foreground process that never exits can prevent later commands from running; background launch does not imply readiness.",
                old, new,
            )
        if old.env != new.env:
            add("environment_changed", "medium", f"Effective environment changed for {old.name}", "Changed parsed environment keys: " + _changed_keys(old.env, new.env) + ". Unresolved host or target values are not inferred.", old, new)
        old_modifiers = dict(_modifiers(old))
        new_modifiers = dict(_modifiers(new))
        if mode_changed:
            old_modifiers.pop("external", None)
            new_modifiers.pop("external", None)
        if old_modifiers != new_modifiers:
            add("modifiers_changed", "medium", f"Effective modifiers changed for {old.name}", "Changed parsed modifiers: " + _changed_keys(old_modifiers, new_modifiers) + ". Documented defaults are normalized; unspecified priority and CPU settings are not guessed.", old, new)

    matched_after = set(matched.values())
    for new_position, new in enumerate(after.commands):
        if new_position in matched_after:
            continue
        if _barrier(new):
            add("barrier_added", "medium", f"Built-in {new.name} added to recognized source", "This adds a configured path check or console reopen. It may return before its ceiling; path presence alone does not prove service readiness.", None, new)
        elif _builtin(new):
            add("command_added", "low", f"Internal {new.name} added to recognized source", "The new recognized source contains an unmatched internal command.", None, new)
        else:
            add("launch_added", "low", f"Launch of {new.name} added to recognized source", "The new recognized source contains an unmatched executable launch; successful startup is not established.", None, new)
    return result
