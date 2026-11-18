"""Focused behavior checks for the conservative source comparison contract."""
from __future__ import annotations

import json
import unittest

from bootdelta.compare import compare_configs, wait_budget
from bootdelta.model import Command, Coverage, ParsedConfig, SourceRef


def command(index: int, name: str, *args: str, env=None, modifiers=None, background=False, raw=None, line=None) -> Command:
    return Command(
        index=index,
        argv=[name, *args],
        modifiers=dict(modifiers or {}),
        env=dict(env or {}),
        background=background,
        source=SourceRef("sample.build", line if line is not None else index + 1),
        raw=raw if raw is not None else " ".join((name, *args)),
    )


def config(*commands: Command, coverage=None) -> ParsedConfig:
    return ParsedConfig(commands=list(commands), coverage=list(coverage or []))


class WaitBudgetTests(unittest.TestCase):
    def test_defaults_and_explicit_timeout_sum(self):
        result = wait_budget(config(
            command(0, "waitfor", "/dev/a"),
            command(1, "reopen"),
            command(2, "waitfor", "/dev/b", "1.2"),
            command(3, "reopen", "/dev/ser1", "0.3"),
        ))
        self.assertEqual(11.5, result.total_seconds)
        self.assertTrue(result.complete)
        self.assertEqual("/dev/console", result.items[1]["path"])
        self.assertTrue(result.items[0]["default_timeout"])
        self.assertFalse(result.items[2]["default_timeout"])

    def test_externals_are_unknown_not_standard_utility_assumptions(self):
        result = wait_budget(config(
            command(0, "waitfor", "/dev/a", "2.0", "50", modifiers={"external": True}),
            command(1, "reopen", "/dev/b", "3", modifiers={"external": True}),
            command(2, "/proc/boot/waitfor", "/dev/c", "4"),
            command(3, "waitfor", "/dev/d", "1"),
        ))
        self.assertEqual(1.0, result.total_seconds)
        self.assertFalse(result.complete)
        self.assertEqual([False, False, False, True], [item["included"] for item in result.items])
        self.assertIsNone(result.items[0]["seconds"])

    def test_background_builtin_and_invalid_literals_reduce_coverage(self):
        result = wait_budget(config(
            command(0, "waitfor", "/dev/a", background=True),
            command(1, "waitfor", "/dev/b", "${TIMEOUT}"),
            command(2, "waitfor", "/dev/c", "-1"),
            command(3, "waitfor", "/dev/d", "0.25"),
            command(4, "waitfor", "/dev/e", "1.0", "100"),
            command(5, "waitfor"),
            command(6, "reopen", "/dev/f", "1", "extra"),
        ))
        self.assertFalse(result.complete)
        self.assertEqual(0.0, result.total_seconds)
        self.assertTrue(all(item["reason"] for item in result.items))

    def test_zero_is_known_and_not_replaced_with_default(self):
        result = wait_budget(config(command(0, "waitfor", "/dev/a", "0")))
        self.assertEqual(0.0, result.total_seconds)
        self.assertTrue(result.complete)
        self.assertFalse(result.items[0]["default_timeout"])

    def test_parser_gap_marks_total_partial_even_without_visible_waits(self):
        result = wait_budget(config(coverage=[Coverage("unknown", "external script unavailable")]))
        self.assertEqual(0.0, result.total_seconds)
        self.assertFalse(result.complete)

    def test_huge_timeout_never_serializes_infinity(self):
        result = wait_budget(config(command(0, "waitfor", "/dev/a", "9" * 400)))
        self.assertFalse(result.complete)
        json.dumps(result.__dict__, allow_nan=False)


class CompareTests(unittest.TestCase):
    def test_whitespace_and_source_line_changes_are_not_semantic(self):
        before = config(command(0, "service", "--one", raw="service   --one", line=3))
        after = config(command(0, "service", "--one", raw="  service --one # note", line=8))
        self.assertEqual([], compare_configs(before, after).changes)

    def test_insertions_do_not_turn_following_launches_into_moves(self):
        before = config(command(0, "a"), command(1, "b"))
        after = config(command(0, "new"), command(1, "a"), command(2, "b"))
        result = compare_configs(before, after)
        self.assertEqual(["launch_added"], [change.code for change in result.changes])
        self.assertEqual("low", result.changes[0].level)

    def test_barrier_crossing_has_high_review_priority(self):
        before = config(command(0, "driver", background=True), command(1, "waitfor", "/dev/a"))
        after = config(command(0, "waitfor", "/dev/a"), command(1, "driver", background=True))
        changes = compare_configs(before, after).changes
        self.assertEqual(["order_changed", "order_changed"], [change.code for change in changes])
        barrier = next(change for change in changes if change.before.name == "waitfor")
        self.assertEqual("high", barrier.level)
        self.assertEqual(2, barrier.before.source.line)
        self.assertEqual(1, barrier.after.source.line)

    def test_effective_edit_fields_are_reported(self):
        before = config(command(0, "service", "--old", env={"A": "old"}, modifiers={"pri": "10r"}))
        after = config(command(0, "service", "--new", env={"A": "new"}, modifiers={"pri": "11f"}, background=True))
        result = compare_configs(before, after)
        self.assertEqual(
            {"arguments_changed", "environment_changed", "modifiers_changed", "background_changed"},
            {change.code for change in result.changes},
        )
        self.assertTrue(all(change.before is before.commands[0] and change.after is after.commands[0] for change in result.changes))

    def test_documented_defaults_are_semantically_equal(self):
        before = config(command(0, "service"), command(1, "waitfor", "/dev/a"), command(2, "reopen"))
        after = config(
            command(0, "service", modifiers={"external": True, "critical": False, "session": False, "argv0": "service"}),
            command(1, "waitfor", "/dev/a", "5.0"),
            command(2, "reopen", "/dev/console", "5"),
        )
        self.assertEqual([], compare_configs(before, after).changes)

    def test_internal_external_switch_does_not_inherit_wait_semantics(self):
        before = config(command(0, "waitfor", "/dev/a", "2"))
        after = config(command(0, "waitfor", "/dev/a", "2", modifiers={"external": True}))
        result = compare_configs(before, after)
        mode = next(change for change in result.changes if change.code == "execution_mode_changed")
        self.assertEqual("high", mode.level)
        self.assertFalse(any(change.code == "arguments_changed" for change in result.changes))
        self.assertEqual(2.0, result.wait_before.total_seconds)
        self.assertEqual(0.0, result.wait_after.total_seconds)
        self.assertFalse(result.wait_after.complete)
        self.assertTrue(any("recognized subtotals" in note for note in result.notes))

    def test_wait_edit_removed_and_added_barrier(self):
        result = compare_configs(
            config(command(0, "waitfor", "/dev/a", "1"), command(1, "reopen")),
            config(command(0, "waitfor", "/dev/b", "3")),
        )
        self.assertEqual({"wait_configuration_changed", "barrier_removed"}, {c.code for c in result.changes})
        removed = next(change for change in result.changes if change.code == "barrier_removed")
        self.assertEqual("high", removed.level)
        self.assertEqual(6.0, result.wait_before.total_seconds)
        self.assertEqual(3.0, result.wait_after.total_seconds)

    def test_exact_duplicates_preserve_cardinality_and_explain_uncertainty(self):
        result = compare_configs(
            config(command(0, "worker", "a"), command(1, "worker", "a")),
            config(command(0, "worker", "a")),
        )
        self.assertEqual(["launch_removed"], [change.code for change in result.changes])
        self.assertTrue(any("identity" in note and "occurrence" in note for note in result.notes))

    def test_exact_duplicate_name_variants_match_before_edit_pairing(self):
        result = compare_configs(
            config(command(0, "worker", "a"), command(1, "worker", "b")),
            config(command(0, "worker", "b"), command(1, "worker", "changed-a")),
        )
        edited = [change for change in result.changes if change.code == "arguments_changed"]
        self.assertEqual(1, len(edited))
        self.assertEqual(["a"], edited[0].before.args)
        self.assertEqual(["changed-a"], edited[0].after.args)
        self.assertFalse(any(change.code in ("launch_added", "launch_removed") for change in result.changes))

    def test_unique_wait_path_matches_timeout_and_environment_change(self):
        result = compare_configs(
            config(
                command(0, "waitfor", "/dev/ser1", env={"MODE": "old"}),
                command(1, "waitfor", "/dev/telemetry", "3", env={"MODE": "old"}),
            ),
            config(command(0, "waitfor", "/dev/telemetry", "15", env={"MODE": "new"})),
        )
        self.assertEqual(
            {"barrier_removed", "wait_configuration_changed", "environment_changed"},
            {change.code for change in result.changes},
        )
        timeout = next(change for change in result.changes if change.code == "wait_configuration_changed")
        self.assertEqual(["/dev/telemetry", "3"], timeout.before.args)
        self.assertEqual(["/dev/telemetry", "15"], timeout.after.args)
        removed = next(change for change in result.changes if change.code == "barrier_removed")
        self.assertEqual(["/dev/ser1"], removed.before.args)

    def test_repeated_edited_same_resource_waits_remain_ambiguous(self):
        result = compare_configs(
            config(command(0, "waitfor", "/dev/a", "1"), command(1, "waitfor", "/dev/a", "2")),
            config(command(0, "waitfor", "/dev/a", "3"), command(1, "waitfor", "/dev/a", "4")),
        )
        self.assertEqual(2, sum(change.code == "barrier_removed" for change in result.changes))
        self.assertEqual(2, sum(change.code == "barrier_added" for change in result.changes))
        self.assertFalse(any(change.code == "wait_configuration_changed" for change in result.changes))
        self.assertTrue(any("cannot be matched uniquely" in note for note in result.notes))

    def test_multiple_edited_duplicates_do_not_get_arbitrary_pairings(self):
        result = compare_configs(
            config(command(0, "worker", "a"), command(1, "worker", "b")),
            config(command(0, "worker", "c"), command(1, "worker", "d")),
        )
        self.assertEqual(2, sum(change.code == "launch_added" for change in result.changes))
        self.assertEqual(2, sum(change.code == "launch_removed" for change in result.changes))
        self.assertFalse(any(change.code == "arguments_changed" for change in result.changes))
        self.assertTrue(any("cannot be matched uniquely" in note for note in result.notes))

    def test_serialization_retains_source_and_never_claims_total_boot_bound(self):
        result = compare_configs(config(), config(command(0, "waitfor", "/dev/a")))
        payload = result.to_dict()
        self.assertEqual("sample.build", payload["changes"][0]["after"]["source"]["file"])
        self.assertTrue(any("not measured boot time or a total boot-time bound" in note for note in result.notes))
        json.dumps(payload, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
