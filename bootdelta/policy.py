"""Optional, explicit review contracts; these do not assert runtime readiness."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .model import Change, Comparison, ParsedConfig
from .compare import wait_budget


class PolicyError(ValueError):
    """The supplied review contract cannot be interpreted safely."""


def load_policy(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if source.stat().st_size > 100_000:
        raise PolicyError("Policy exceeds the 100 KB input limit.")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PolicyError(f"Invalid policy JSON: {exc}") from exc
    validate_policy(value)
    return value


def validate_policy(policy: dict[str, Any]) -> None:
    if not isinstance(policy, dict):
        raise PolicyError("Policy must be a JSON object.")
    unknown = set(policy) - {"version", "max_configured_wait_seconds", "require_barriers"}
    if unknown:
        raise PolicyError("Unknown policy keys: " + ", ".join(sorted(unknown)))
    if policy.get("version", 1) != 1 or isinstance(policy.get("version"), bool):
        raise PolicyError("Only policy version 1 is supported.")
    if "max_configured_wait_seconds" in policy:
        maximum = policy["max_configured_wait_seconds"]
        if isinstance(maximum, bool) or not isinstance(maximum, (int, float)):
            raise PolicyError("max_configured_wait_seconds must be a finite nonnegative number.")
        try:
            finite = math.isfinite(maximum)
        except OverflowError:
            finite = False
        if not finite or maximum < 0:
            raise PolicyError("max_configured_wait_seconds must be a finite nonnegative number.")
    requirements = policy.get("require_barriers", [])
    if not isinstance(requirements, list) or len(requirements) > 200:
        raise PolicyError("require_barriers must be a list of at most 200 objects.")
    for requirement in requirements:
        if not isinstance(requirement, dict) or set(requirement) != {"path", "before_command"}:
            raise PolicyError("Each barrier must contain exactly path and before_command.")
        if any(not isinstance(v, str) or not v or len(v) > 4096 for v in requirement.values()):
            raise PolicyError("Barrier path and before_command must be nonempty strings.")
        if not requirement["path"].startswith("/"):
            raise PolicyError("Barrier paths must be explicit absolute target paths.")


def apply_policy(comparison: Comparison, policy: dict[str, Any]) -> list[Change]:
    """Return current-configuration contract failures, without mutating the comparison."""
    validate_policy(policy)
    changes: list[Change] = []
    maximum = policy.get("max_configured_wait_seconds")
    if maximum is not None:
        if not comparison.wait_after.complete or comparison.after.coverage:
            changes.append(Change(
                "POLICY_WAIT_UNKNOWN", "high", "Wait-ceiling policy is not fully assessable",
                "The current input has incomplete coverage. The known configured waits are a partial sum; "
                "the maximum-wait contract cannot be certified by this report.",
            ))
        if comparison.wait_after.total_seconds > maximum:
            changes.append(Change(
                "POLICY_WAIT_LIMIT", "high", "Configured waits exceed the project limit",
                f"Known built-in waits total {comparison.wait_after.total_seconds:g} s; "
                f"the supplied policy permits {maximum:g} s. This is a configuration sum, not boot time.",
            ))
    for requirement in policy.get("require_barriers", []):
        path, name = requirement["path"], requirement["before_command"]
        targets = [c for c in comparison.after.commands if c.name == name]
        if not targets:
            changes.append(Change(
                "POLICY_COMMAND_MISSING", "high", f"Required command is absent: {name}",
                f"The supplied contract requires a launch named exactly {name!r} after a wait for {path}. "
                "No modeled launch has that name.",
            ))
            continue
        for target in targets:
            eligible = [c for c in comparison.after.commands
                        if c.index < target.index and c.name == "waitfor" and not c.external
                        and not c.background and c.args and c.args[0] == path
                        and wait_budget(ParsedConfig(commands=[c])).complete]
            if not eligible:
                changes.append(Change(
                    "POLICY_BARRIER_MISSING", "high", f"Missing earlier wait for {path}",
                    f"The supplied contract requires a foreground internal waitfor for {path} before "
                    f"every {name} launch. The current modeled sequence does not contain one. "
                    "A declared wait can time out; this contract checks order, not successful readiness.",
                    after=target,
                ))
        if comparison.after.coverage or not comparison.wait_after.complete:
            changes.append(Change(
                "POLICY_ORDER_UNKNOWN", "high", f"Ordering contract needs complete input: {name}",
                "The current input has coverage gaps. Even if the visible command order matches the contract, "
                "unmodeled configuration prevents a complete assessment.",
            ))
    return changes

