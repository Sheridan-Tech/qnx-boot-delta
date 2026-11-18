"""Behavioral checks of project contracts and CI output boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bootdelta.model import Command, Comparison, Coverage, ParsedConfig, SourceRef, WaitBudget
from bootdelta.policy import PolicyError, apply_policy, validate_policy


ROOT = Path(__file__).resolve().parents[1]


def command(index, name, *args, external=False, background=False):
    return Command(index, [name, *args], {"external": external}, {}, background,
                   SourceRef("test.bsh", index + 1), " ".join([name, *args]))


class PolicyTests(unittest.TestCase):
    def comparison(self, commands, seconds=0, complete=True):
        return Comparison(ParsedConfig(), ParsedConfig(commands=commands), wait_after=WaitBudget(seconds, complete))

    def test_barrier_after_consumer_fails(self):
        value = self.comparison([command(0, "consumer"), command(1, "waitfor", "/dev/data")])
        changes = apply_policy(value, {"require_barriers": [{"path": "/dev/data", "before_command": "consumer"}]})
        self.assertIn("POLICY_BARRIER_MISSING", [c.code for c in changes])

    def test_barrier_must_precede_every_occurrence(self):
        value = self.comparison([command(0, "consumer"), command(1, "waitfor", "/dev/data"), command(2, "consumer")])
        changes = apply_policy(value, {"require_barriers": [{"path": "/dev/data", "before_command": "consumer"}]})
        self.assertEqual(1, len(changes))
        self.assertEqual(0, changes[0].after.index)

    def test_external_and_background_waits_do_not_satisfy_contract(self):
        for kwargs in ({"external": True}, {"background": True}):
            with self.subTest(kwargs=kwargs):
                value = self.comparison([command(0, "waitfor", "/dev/data", **kwargs), command(1, "consumer")])
                self.assertEqual("POLICY_BARRIER_MISSING", apply_policy(value, {
                    "require_barriers": [{"path": "/dev/data", "before_command": "consumer"}]})[0].code)

    def test_valid_declared_order_and_ceiling_pass(self):
        value = self.comparison([command(0, "waitfor", "/dev/data"), command(1, "consumer")], seconds=5)
        self.assertEqual([], apply_policy(value, {"max_configured_wait_seconds": 5,
            "require_barriers": [{"path": "/dev/data", "before_command": "consumer"}]}))

    def test_incomplete_budget_is_not_a_pass(self):
        value = self.comparison([], seconds=3, complete=False)
        self.assertEqual("POLICY_WAIT_UNKNOWN", apply_policy(value, {"max_configured_wait_seconds": 6})[0].code)

    def test_no_matching_launch_is_a_contract_failure(self):
        value = self.comparison([])
        self.assertEqual("POLICY_COMMAND_MISSING", apply_policy(value, {
            "require_barriers": [{"path": "/dev/data", "before_command": "consumer"}]})[0].code)

    def test_unknown_keys_and_invalid_number_rejected(self):
        for policy in ({"max_configured_wait_seconds": True}, {"max_configured_wait_seconds": float("nan")},
                       {"max_configured_wait_seconds": -1}, {"wrong_option": 5}, {"require_barriers": "bad"}):
            with self.subTest(policy=policy), self.assertRaises(PolicyError):
                validate_policy(policy)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "bootdelta", *map(str, args)], cwd=ROOT, capture_output=True, text=True)

    def test_real_examples_exit_review_and_fixed(self):
        changed = self.run_cli("examples/baseline.build", "examples/changed.build", "--policy", "examples/review-policy.json")
        self.assertEqual(1, changed.returncode, changed.stderr + changed.stdout)
        self.assertIn("POLICY_BARRIER_MISSING", changed.stdout)
        self.assertIn("POLICY_WAIT_LIMIT", changed.stdout)
        corrected = self.run_cli("examples/baseline.build", "examples/corrected.build", "--policy", "examples/review-policy.json")
        self.assertEqual(0, corrected.returncode, corrected.stderr + corrected.stdout)
        self.assertIn("No modeled startup changes", corrected.stdout)

    def test_json_html_exports_and_nonfinite_free_json(self):
        with tempfile.TemporaryDirectory() as directory:
            json_path, html_path = Path(directory) / "report.json", Path(directory) / "report.html"
            result = self.run_cli("examples/baseline.build", "examples/changed.build", "--json", json_path, "--html", html_path)
            self.assertEqual(1, result.returncode, result.stderr + result.stdout)
            data = json.loads(json_path.read_text(), parse_constant=lambda value: self.fail(value))
            self.assertEqual("1.0", data["schema_version"])
            self.assertIn("<!doctype html>", html_path.read_text())

    def test_reports_cannot_overwrite_source_or_each_other(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.bsh"
            source.write_text("waitfor /dev/data\n")
            result = self.run_cli(source, source, "--script", "--html", source)
            self.assertEqual(2, result.returncode)
            self.assertEqual("waitfor /dev/data\n", source.read_text())
            output = Path(directory) / "report.txt"
            result = self.run_cli(source, source, "--script", "--html", output, "--json", output)
            self.assertEqual(2, result.returncode)
            self.assertFalse(output.exists())

    def test_missing_file_and_incomplete_input_fail_closed(self):
        missing = self.run_cli("not-present.build", "examples/baseline.build")
        self.assertEqual(2, missing.returncode)
        incomplete = self.run_cli("examples/baseline.build", "examples/incomplete.build", "--fail-on", "never")
        self.assertEqual(2, incomplete.returncode, incomplete.stderr + incomplete.stdout)

    def test_existing_hardlink_alias_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.bsh"
            output = Path(directory) / "report.html"
            source.write_text("waitfor /dev/data\n")
            os.link(source, output)
            result = self.run_cli(source, source, "--script", "--html", output)
            self.assertEqual(2, result.returncode)
            self.assertEqual("waitfor /dev/data\n", source.read_text())


if __name__ == "__main__":
    unittest.main()

