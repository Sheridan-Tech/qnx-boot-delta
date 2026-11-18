"""Command-line entry point. Input paths are never executed."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .compare import compare_configs
from .parser import parse_path
from .policy import PolicyError, apply_policy, load_policy
from .report import is_complete, render_html, render_text


def _same_file(first: Path, second: Path) -> bool:
    if first == second:
        return True
    return first.exists() and second.exists() and first.samefile(second)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bootdelta", description="Review semantic changes in QNX 8 startup configuration. No commands are executed.")
    parser.add_argument("before", type=Path, help="baseline QNX buildfile")
    parser.add_argument("after", type=Path, help="current QNX buildfile")
    parser.add_argument("--script", action="store_true", help="both inputs are standalone startup scripts")
    parser.add_argument("--before-root", type=Path, help="baseline project / mkifs working directory; defaults to input parent")
    parser.add_argument("--after-root", type=Path, help="current project / mkifs working directory; defaults to input parent")
    parser.add_argument("--json", dest="json_path", type=Path, help="write machine-readable report")
    parser.add_argument("--html", dest="html_path", type=Path, help="write a self-contained interactive report")
    parser.add_argument("--policy", type=Path, help="optional JSON review contract")
    parser.add_argument("--fail-on", choices=["high", "medium", "low", "never"], default="high",
                        help="review priority causing exit 1 (default high); coverage gaps always exit 2")
    parser.add_argument("--version", action="version", version=f"QNX Boot Delta {__version__}")
    args = parser.parse_args(argv)
    try:
        before = parse_path(args.before, root=args.before_root, script_mode=args.script)
        after = parse_path(args.after, root=args.after_root, script_mode=args.script)
        comparison = compare_configs(before, after)
        if args.policy:
            comparison.changes.extend(apply_policy(comparison, load_policy(args.policy)))
            comparison.notes.append("Project review contracts were supplied explicitly for this comparison.")
        outputs = [p.resolve() for p in (args.json_path, args.html_path) if p is not None]
        if any(_same_file(first, second) for i, first in enumerate(outputs) for second in outputs[i + 1:]):
            raise ValueError("HTML and JSON outputs must be different paths.")
        # Never overwrite an input or an included source, even via symlinks.
        input_paths = {args.before.resolve(), args.after.resolve()}
        for config in (before, after):
            input_paths.update((Path(config.root) / name).resolve() for name in config.sources)
        if args.policy:
            input_paths.add(args.policy.resolve())
        if any(_same_file(path, source) for path in outputs for source in input_paths):
            raise ValueError("A report output would overwrite analyzed input. Choose another path.")
        if args.json_path:
            args.json_path.parent.mkdir(parents=True, exist_ok=True)
            args.json_path.write_text(json.dumps(comparison.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.html_path:
            args.html_path.parent.mkdir(parents=True, exist_ok=True)
            args.html_path.write_text(render_html(comparison), encoding="utf-8")
        sys.stdout.write(render_text(comparison))
        if not is_complete(comparison):
            return 2
        priorities = {"high": 3, "medium": 2, "low": 1, "never": 4}
        return int(any(priorities.get(change.level, 0) >= priorities[args.fail_on] for change in comparison.changes))
    except (OSError, UnicodeError, PolicyError, ValueError) as exc:
        sys.stderr.write(f"bootdelta: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

