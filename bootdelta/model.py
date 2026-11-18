"""Shared, serializable data contract for QNX Boot Delta.

All observations describe source configuration, never target execution.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceRef:
    file: str
    line: int
    end_line: int | None = None


@dataclass
class Coverage:
    code: str
    message: str
    source: SourceRef | None = None


@dataclass
class Command:
    index: int
    argv: list[str]
    modifiers: dict[str, str | bool]
    env: dict[str, str]
    background: bool
    source: SourceRef
    raw: str
    section: str = "startup"

    @property
    def name(self) -> str:
        return self.argv[0] if self.argv else ""

    @property
    def args(self) -> list[str]:
        return self.argv[1:]

    @property
    def external(self) -> bool:
        return self.modifiers.get("external", False) in (True, "true", "+", "1")


@dataclass
class ParsedConfig:
    commands: list[Command] = field(default_factory=list)
    coverage: list[Coverage] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    input: str = ""
    root: str = ""
    mode: str = "buildfile"


@dataclass
class Change:
    code: str
    level: str
    title: str
    detail: str
    before: Command | None = None
    after: Command | None = None
    documentation: str = "https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkifs.html"


@dataclass
class WaitBudget:
    total_seconds: float = 0.0
    complete: bool = True
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Comparison:
    before: ParsedConfig
    after: ParsedConfig
    changes: list[Change] = field(default_factory=list)
    wait_before: WaitBudget = field(default_factory=WaitBudget)
    wait_after: WaitBudget = field(default_factory=WaitBudget)
    notes: list[str] = field(default_factory=list)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

