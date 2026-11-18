"""Behavioral boundaries taken from QNX SDP 8.0 documentation.

These tests exercise observable source-analysis results, not parser internals.
The specification is the mkifs reference's Script files, Environment variables,
and include sections:
https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.utilities/topic/m/mkifs.html

No test invokes QNX, executes a source command, or treats a configured timeout as
measured boot time. All input files are isolated temporary fixtures.
"""
from __future__ import annotations

import html
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bootdelta.compare import compare_configs, wait_budget
from bootdelta.model import Change, Command, Comparison, ParsedConfig, SourceRef, WaitBudget
from bootdelta.parser import parse_path


class _SourceFixtures:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / "project"
        self.root.mkdir()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def script(self, text, filename="input.script"):
        return parse_path(self.write(filename, text), root=self.root, script_mode=True)

    def build(self, text, filename="input.build"):
        return parse_path(self.write(filename, text), root=self.root)


class SourceAnalysisCases(_SourceFixtures, unittest.TestCase):
    def test_persistent_and_command_local_environment_and_modifiers(self):
        parsed = self.script(
            "MODE=base\n"
            "[pri=8 +critical]\n"
            "[pri=20 -critical] MODE=temporary alpha &\n"
            "beta\n"
            "MODE=next\n"
            "gamma\n"
        )
        self.assertEqual([c.name for c in parsed.commands], ["alpha", "beta", "gamma"])
        alpha, beta, gamma = parsed.commands
        self.assertEqual([c.env.get("MODE") for c in parsed.commands],
                         ["temporary", "base", "next"])
        self.assertEqual([str(c.modifiers.get("pri")) for c in parsed.commands],
                         ["20", "8", "8"])
        self.assertFalse(alpha.modifiers["critical"])
        self.assertTrue(beta.modifiers["critical"])
        self.assertTrue(gamma.modifiers["critical"])
        self.assertEqual([c.background for c in parsed.commands], [True, False, False])

    def test_external_modifier_local_reset_does_not_change_persistent_default(self):
        parsed = self.script(
            "[+external]\n"
            "waitfor /dev/a 2\n"
            "[-external] waitfor /dev/b 3\n"
            "waitfor /dev/c 4\n"
            "[-external]\n"
            "waitfor /dev/d 1\n"
        )
        self.assertEqual([c.external for c in parsed.commands], [True, False, True, False])
        budget = wait_budget(parsed)
        self.assertAlmostEqual(budget.total_seconds, 4.0)
        self.assertFalse(budget.complete, "External wait implementations are not inferred.")

    def test_executable_with_builtin_basename_is_not_an_internal_barrier(self):
        parsed = self.script(
            "waitfor /dev/a 1.5\n"
            "[+external] waitfor /dev/b 20 0.1\n"
            "/proc/boot/waitfor /dev/c 30\n"
        )
        budget = wait_budget(parsed)
        self.assertAlmostEqual(budget.total_seconds, 1.5)
        self.assertFalse(budget.complete)

    def test_native_wait_defaults_and_explicit_tenths(self):
        parsed = self.script(
            "waitfor /dev/a\n"
            "waitfor /dev/b 1.2\n"
            "reopen\n"
            "reopen /dev/console 3.4\n"
        )
        budget = wait_budget(parsed)
        self.assertAlmostEqual(budget.total_seconds, 14.6)
        self.assertTrue(budget.complete)

    def test_background_barrier_has_no_assumed_foreground_wait_ceiling(self):
        parsed = self.script("waitfor /dev/a 7 &\n")
        budget = wait_budget(parsed)
        self.assertEqual(budget.total_seconds, 0.0)
        self.assertFalse(budget.complete)

    def test_ordinary_inline_file_is_not_a_startup_script(self):
        parsed = self.build(
            "/etc/example = {\n"
            "waitfor /dev/not-a-command 90\n"
            "}\n"
            "[+script] .script = {\n"
            "waitfor /dev/real 1\n"
            "}\n"
        )
        self.assertEqual([c.argv for c in parsed.commands], [["waitfor", "/dev/real", "1"]])
        self.assertEqual(wait_budget(parsed).total_seconds, 1.0)

    def test_multiple_script_sections_keep_runtime_environment_and_modifier_state(self):
        parsed = self.build(
            "[+script] .first = {\n"
            "MODE=persistent\n"
            "[pri=12]\n"
            "alpha\n"
            "}\n"
            "[+script] .second = {\n"
            "beta\n"
            "}\n"
        )
        self.assertEqual([c.name for c in parsed.commands], ["alpha", "beta"])
        self.assertEqual(parsed.commands[1].env.get("MODE"), "persistent")
        self.assertEqual(str(parsed.commands[1].modifiers.get("pri")), "12")

    def test_bootstrap_standalone_environment_reaches_startup_but_local_env_does_not(self):
        parsed = self.build(
            "[virtual=x86_64,bios] .bootstrap = {\n"
            "MODE=from_bootstrap\n"
            "ONE_SHOT=only_startup startup-bios\n"
            "procnto-smp\n"
            "}\n"
            "[+script] .script = {\n"
            "alpha\n"
            "}\n"
        )
        self.assertEqual([c.name for c in parsed.commands], ["alpha"])
        self.assertEqual(parsed.commands[0].env.get("MODE"), "from_bootstrap")
        self.assertNotIn("ONE_SHOT", parsed.commands[0].env)

    def test_comment_marker_inside_double_quotes_is_literal(self):
        parsed = self.script('display_msg "startup #1" # ordinary comment\n')
        self.assertEqual(parsed.commands[0].argv, ["display_msg", "startup #1"])

    def test_unmodeled_expansion_and_shell_syntax_cannot_look_fully_analyzed(self):
        constructs = [
            'waitfor ${DEVICE} 5\n',
            'alpha | beta\n',
            'alpha > /tmp/output\n',
            'alpha $(touch SHOULD_NEVER_EXIST)\n',
        ]
        for i, text in enumerate(constructs):
            with self.subTest(text=text):
                with patch("subprocess.Popen", side_effect=AssertionError("Source was executed")), \
                     patch("os.system", side_effect=AssertionError("Source was executed")):
                    parsed = self.script(text, f"dynamic-{i}.script")
                    budget = wait_budget(parsed)
                self.assertTrue(parsed.coverage, "Unmodeled syntax must have a visible coverage gap.")
                self.assertFalse(budget.complete)
        self.assertFalse((self.root / "SHOULD_NEVER_EXIST").exists())

    def test_unterminated_quote_is_not_silently_accepted(self):
        parsed = self.script('display_msg "unfinished\n')
        self.assertTrue(parsed.coverage)
        self.assertFalse(wait_budget(parsed).complete)

    def test_nested_shell_command_is_visible_as_unmodeled_behavior(self):
        parsed = self.script('sh -c "waitfor /dev/later 99"\n')
        self.assertEqual(parsed.commands[0].name, "sh")
        self.assertEqual(wait_budget(parsed).total_seconds, 0.0)
        self.assertTrue(parsed.coverage)

    def test_include_traversal_does_not_read_outside_project(self):
        outside = self.parent / "outside.build"
        sentinel = "DO_NOT_INGEST_OUTSIDE_PROJECT"
        outside.write_text(f"[+script] .outside = {{\n{sentinel}\n}}\n", encoding="utf-8")
        parsed = self.build("[+include] ../outside.build\n")
        self.assertTrue(parsed.coverage)
        self.assertNotIn(sentinel, json.dumps(parsed.sources))
        self.assertFalse(parsed.commands)

    def test_include_symlink_escape_does_not_read_outside_project(self):
        outside = self.parent / "outside.build"
        sentinel = "DO_NOT_INGEST_SYMLINK_TARGET"
        outside.write_text(f"[+script] .outside = {{\n{sentinel}\n}}\n", encoding="utf-8")
        (self.root / "escape.build").symlink_to(outside)
        parsed = self.build("[+include] escape.build\n")
        self.assertTrue(parsed.coverage)
        self.assertNotIn(sentinel, json.dumps(parsed.sources))
        self.assertFalse(parsed.commands)

    def test_include_cycle_terminates_with_coverage_gap(self):
        self.write("child.build", "[+include] input.build\n")
        parsed = self.build("[+include] child.build\n")
        self.assertTrue(parsed.coverage)
        self.assertFalse(wait_budget(parsed).complete)

    def test_repeated_include_is_processed_only_once(self):
        self.write("child.build", "[+script] .child = {\nalpha\n}\n")
        parsed = self.build("[+include] child.build\n[+include] child.build\n")
        self.assertEqual([c.name for c in parsed.commands], ["alpha"])

    def test_include_resolution_uses_explicit_project_working_directory(self):
        self.write("nested/entry.build", "[+include] child.build\n")
        self.write("child.build", "[+script] .right = {\nfrom_project_root\n}\n")
        self.write("nested/child.build", "[+script] .wrong = {\nfrom_including_parent\n}\n")
        parsed = self.build("[+include] nested/entry.build\n")
        self.assertEqual([c.name for c in parsed.commands], ["from_project_root"])

    def test_nonfinite_timeout_cannot_enter_json_numeric_results(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token):
                parsed = self.script(f"waitfor /dev/a {token}\n", "nonfinite.script")
                comparison = compare_configs(parsed, parsed)
                self.assertFalse(comparison.wait_before.complete)
                json.dumps(comparison.to_dict(), allow_nan=False)


class SemanticComparisonCases(_SourceFixtures, unittest.TestCase):
    """Invariants independent of the comparison implementation's matching strategy."""

    def test_source_layout_changes_do_not_create_semantic_changes(self):
        before = self.script('MODE=steady\nalpha --one &\n', "before.script")
        after = self.script('# comment\n\nMODE=steady\n  alpha   --one   & # note\n', "after.script")
        self.assertEqual(compare_configs(before, after).changes, [])

    def test_reorder_is_reported_without_invented_additions_and_removals(self):
        before = self.script("alpha\nbeta\ngamma\n", "before.script")
        after = self.script("beta\nalpha\ngamma\n", "after.script")
        result = compare_configs(before, after)
        codes = {c.code for c in result.changes}
        self.assertIn("order_changed", codes)
        self.assertFalse(codes & {"launch_added", "launch_removed"})

    def test_insertion_does_not_make_unchanged_later_commands_reorders(self):
        before = self.script("alpha\nbeta\n", "before.script")
        after = self.script("newcomer\nalpha\nbeta\n", "after.script")
        codes = [c.code for c in compare_configs(before, after).changes]
        self.assertEqual(codes.count("launch_added"), 1)
        self.assertNotIn("order_changed", codes)

    def test_duplicate_cardinality_is_not_lost(self):
        before = self.script("alpha --same\nalpha --same\nbeta\n", "before.script")
        after = self.script("alpha --same\nbeta\n", "after.script")
        result = compare_configs(before, after)
        self.assertEqual(sum(c.code == "launch_removed" for c in result.changes), 1)
        self.assertFalse(any(c.code == "launch_added" for c in result.changes))
        self.assertTrue(result.notes, "Duplicate matching limitations must be visible.")

    def test_edited_duplicate_names_do_not_gain_invented_one_to_one_correspondence(self):
        before = self.script("alpha --red\nalpha --blue\n", "before.script")
        after = self.script("alpha --green\nalpha --yellow\n", "after.script")
        result = compare_configs(before, after)
        self.assertTrue(result.notes)
        self.assertFalse(any(c.code == "arguments_changed" for c in result.changes))
        self.assertEqual(sum(c.code == "launch_removed" for c in result.changes), 2)
        self.assertEqual(sum(c.code == "launch_added" for c in result.changes), 2)

    def test_builtin_external_switch_is_a_semantic_change(self):
        before = self.script("waitfor /dev/a 2\n", "before.script")
        after = self.script("[+external] waitfor /dev/a 2\n", "after.script")
        result = compare_configs(before, after)
        self.assertTrue(any(c.code == "execution_mode_changed" for c in result.changes))
        self.assertEqual(result.wait_before.total_seconds, 2.0)
        self.assertEqual(result.wait_after.total_seconds, 0.0)
        self.assertFalse(result.wait_after.complete)


class ReportEscapingCases(unittest.TestCase):
    def test_template_markers_in_source_remain_literal_source(self):
        from bootdelta.report import render_html

        raw = 'display_msg "@@NOTES@@"'
        command = Command(0, ["display_msg", "@@NOTES@@"], {}, {}, False,
                          SourceRef("input.script", 1), raw)
        config = ParsedConfig(commands=[command], sources={"input.script": raw}, input="input.script")
        rendered = render_html(Comparison(config, config, notes=["A real analysis note."]))
        self.assertTrue("@@NOTES@@" in rendered, "Template replacement must not reinterpret source content.")

    def test_source_commands_paths_and_notes_cannot_inject_report_markup(self):
        from bootdelta.report import render_html

        payload = '<img src=x onerror="HOSTILE_SOURCE_SENTINEL()">'
        command = Command(0, ["display_msg", payload], {}, {}, False,
                          SourceRef(payload, 1), payload)
        config = ParsedConfig(commands=[command], sources={payload: payload}, input=payload)
        result = Comparison(config, config, changes=[
            Change("test", "high", payload, payload, command, command)
        ], notes=[payload])
        rendered = render_html(result)
        self.assertNotIn(payload, rendered)
        self.assertIn(html.escape(payload), rendered)

        class Elements(HTMLParser):
            def __init__(self):
                super().__init__()
                self.hostile_attributes = []

            def handle_starttag(self, tag, attrs):
                for key, value in attrs:
                    if value and "HOSTILE_SOURCE_SENTINEL" in value and key.lower().startswith("on"):
                        self.hostile_attributes.append((tag, key, value))

        parsed_html = Elements()
        parsed_html.feed(rendered)
        self.assertEqual(parsed_html.hostile_attributes, [])


class PolicyBoundaryCases(unittest.TestCase):
    def test_uninterpretable_barrier_cannot_satisfy_ordering_contract(self):
        from bootdelta.policy import apply_policy

        wait = Command(0, ["waitfor", "/dev/a", "NaN"], {}, {}, False,
                       SourceRef("input.script", 1), "waitfor /dev/a NaN")
        consumer = Command(1, ["alpha"], {}, {}, False,
                           SourceRef("input.script", 2), "alpha")
        config = ParsedConfig(commands=[wait, consumer])
        comparison = Comparison(config, config, wait_after=WaitBudget(complete=False))
        failures = apply_policy(comparison, {
            "require_barriers": [{"path": "/dev/a", "before_command": "alpha"}]
        })
        self.assertTrue(failures, "An invalid or uninterpretable wait must not silently satisfy policy.")

    def test_excessive_integer_limit_is_a_controlled_policy_error(self):
        from bootdelta.policy import PolicyError, validate_policy

        with self.assertRaises(PolicyError):
            validate_policy({"max_configured_wait_seconds": 10 ** 400})


if __name__ == "__main__":
    unittest.main()
