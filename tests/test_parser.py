"""Behavioral tests for declared QNX startup syntax and parser boundaries."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bootdelta.parser import parse_path


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def parse(self, text, **kwargs):
        return parse_path(self.write("input.build", text), root=self.root, **kwargs)

    def test_extracts_only_explicit_script_and_carries_bootstrap_environment(self):
        parsed = self.parse('''[virtual=x86_64,bios] .boot = {
startup-x86
PATH=/proc/boot
LOCAL=only procnto-smp-instr
}
/etc/example = {
waitfor /not-a-script 99
}
[+script] .script = {
waitfor /dev/ready 5.0
}
''')
        self.assertEqual([c.argv for c in parsed.commands], [["waitfor", "/dev/ready", "5.0"]])
        self.assertEqual(parsed.commands[0].env, {"PATH": "/proc/boot"})
        self.assertFalse(parsed.coverage)

    def test_modifier_and_environment_scope_and_multiple_scripts(self):
        parsed = self.parse('''[+script] first = {
[pri=10f +external]
MODE=steady
[pri=20r -external] MODE=once waitfor /a 2
tool &
}
[+script] second = {
other
}
''')
        first, second, third = parsed.commands
        self.assertEqual(first.modifiers["pri"], "20r")
        self.assertFalse(first.external)
        self.assertEqual(first.env["MODE"], "once")
        for command in (second, third):
            self.assertEqual(command.modifiers["pri"], "10f")
            self.assertTrue(command.external)
            self.assertEqual(command.env["MODE"], "steady")
        self.assertTrue(second.background)
        self.assertFalse(third.background)

    def test_quotes_comments_escapes_and_continuation_preserve_arguments(self):
        parsed = self.parse('display_msg "hello # world" "&" "a | b" \\\n  "tail value" # ignored\n', script_mode=True)
        self.assertFalse(parsed.coverage)
        self.assertEqual(parsed.commands[0].argv,
                         ["display_msg", "hello # world", "&", "a | b", "tail value"])
        self.assertFalse(parsed.commands[0].background)
        self.assertEqual(parsed.commands[0].source.line, 1)
        self.assertEqual(parsed.commands[0].source.end_line, 2)

    def test_quoted_and_escaped_variables_are_literal_but_unquoted_is_unknown(self):
        with patch.dict("os.environ", {"BOOTDELTA_PROBE": "must-not-appear"}):
            parsed = self.parse('display_msg "${BOOTDELTA_PROBE}" \\${BOOTDELTA_PROBE}\n'
                                'run ${BOOTDELTA_PROBE}\n', script_mode=True)
        self.assertEqual(parsed.commands[0].argv,
                         ["display_msg", "${BOOTDELTA_PROBE}", "${BOOTDELTA_PROBE}"])
        self.assertEqual(len(parsed.commands), 1)
        self.assertIn("unresolved_variable", [c.code for c in parsed.coverage])
        self.assertNotIn("must-not-appear", repr(parsed))

    def test_includes_use_root_and_stream_order(self):
        main = self.write("sub/main.build", '[+include] child.build\n[+script] end = {\nlast\n}\n')
        self.write("child.build", '[+script] child = {\nMODE=inside\nfirst\n}\n')
        parsed = parse_path(main, root=self.root)
        self.assertEqual([c.name for c in parsed.commands], ["first", "last"])
        self.assertEqual(parsed.commands[-1].env, {"MODE": "inside"})
        self.assertEqual(parsed.commands[0].source.file, "child.build")

    def test_duplicate_includes_are_ignored_and_cycles_reported(self):
        main = self.write("input.build", '[+include] child.build\n[+include] child.build\n')
        self.write("child.build", '[+include] input.build\n[+script] child = {\nfirst\n}\n')
        parsed = parse_path(main, root=self.root)
        self.assertEqual([c.name for c in parsed.commands], ["first"])
        self.assertIn("include_cycle", [c.code for c in parsed.coverage])

    def test_missing_external_and_global_include_are_explicit(self):
        parsed = self.parse('[+include] absent.build\n[+include]\nchild.build\n[-include]\n[+script] .script=external.bsh\n')
        codes = [c.code for c in parsed.coverage]
        self.assertIn("file_unavailable", codes)
        self.assertIn("global_include_mode", codes)
        self.assertIn("external_script", codes)

    def test_unsupported_syntax_is_never_interpreted_as_commands(self):
        parsed = self.parse('one | two\nrun $(touch bad)\nif okay\n[uid=0] thing\n'
                            '[cpu=0] [pri=10] other\nvalid\n', script_mode=True)
        self.assertEqual([c.name for c in parsed.commands], ["valid"])
        self.assertIn("unsupported_modifier", [c.code for c in parsed.coverage])
        self.assertIn("multiple_attribute_blocks", [c.code for c in parsed.coverage])

    def test_path_escape_and_symlink_escape_are_not_read(self):
        outside = self.root.parent / (self.root.name + "-outside.bsh")
        outside.write_text("secret_command\n", encoding="utf-8")
        self.addCleanup(outside.unlink)
        (self.root / "escape.build").symlink_to(outside)
        parsed = self.parse('[+include] escape.build\n')
        self.assertFalse(parsed.commands)
        self.assertEqual(list(parsed.sources), ["input.build"])
        self.assertIn("path_outside_root", [c.code for c in parsed.coverage])

    def test_bounded_files_and_unclosed_inline(self):
        with patch("bootdelta.parser.MAX_FILE_BYTES", 5):
            parsed = self.parse("a-long-command\n", script_mode=True)
        self.assertIn("file_size_limit", [c.code for c in parsed.coverage])
        parsed = self.parse('[+script] boot = {\ncommand\n')
        self.assertIn("unclosed_inline", [c.code for c in parsed.coverage])

    def test_file_attributes_do_not_become_process_modifiers(self):
        parsed = self.parse('[uid=42 gid=43]\n[+script] .script = {\nlaunch\n}\n')
        self.assertNotIn("uid", parsed.commands[0].modifiers)
        self.assertNotIn("gid", parsed.commands[0].modifiers)
        self.assertFalse(parsed.coverage)

    def test_explicit_external_name_remains_distinct(self):
        parsed = self.parse('[+external] waitfor /x\n/proc/boot/waitfor /y\nwaitfor /z\n', script_mode=True)
        self.assertTrue(parsed.commands[0].external)
        self.assertEqual(parsed.commands[1].name, "/proc/boot/waitfor")
        self.assertFalse(parsed.commands[2].external)

    def test_inline_backslash_newline_does_not_consume_the_next_wait(self):
        text = '[+script] .script = {\nservice ' + '\\' + '\nwaitfor /dev/a 2\n}\n'
        parsed = self.parse(text)
        self.assertEqual([c.argv for c in parsed.commands], [["waitfor", "/dev/a", "2"]])
        self.assertEqual(parsed.commands[0].source.line, 3)
        self.assertIn("inline_escape", [c.code for c in parsed.coverage])

    def test_ordinary_inline_data_escapes_do_not_join_closing_line(self):
        text = '/etc/data = {\npayload' + '\\' + '\n}\n[+script] .script = {\nlaunch\n}\n'
        parsed = self.parse(text)
        self.assertEqual([c.name for c in parsed.commands], ["launch"])
        self.assertFalse(parsed.coverage)

    def test_inline_outer_brace_is_structural_even_inside_quotes(self):
        parsed = self.parse('[+script] .script = {\ndisplay_msg "${LITERAL}"\nwaitfor /dev/a 2\n}\n')
        self.assertFalse(parsed.commands)
        self.assertIn("inline_delimiter", [c.code for c in parsed.coverage])

    def test_include_cd_does_not_silently_read_from_default_root(self):
        self.write("child.build", '[+script] .wrong = {\nwrong\n}\n')
        self.write("sub/child.build", '[+script] .right = {\nright\n}\n')
        for declaration in ('[cd=sub +include] child.build\n',
                            '[cd=sub]\n[+include] child.build\n'):
            with self.subTest(declaration=declaration):
                parsed = self.parse(declaration)
                self.assertFalse(parsed.commands)
                self.assertEqual(list(parsed.sources), ["input.build"])
                self.assertIn("include_cd", [c.code for c in parsed.coverage])

    def test_shell_style_escaped_space_is_not_assumed_to_be_qnx_escape(self):
        parsed = self.parse('tool tail' + '\\' + ' value\nwaitfor /dev/a 2\n', script_mode=True)
        self.assertEqual([c.name for c in parsed.commands], ["waitfor"])
        self.assertIn("escape_unmodeled", [c.code for c in parsed.coverage])

    def test_filtered_startup_or_bootstrap_payload_is_not_guessed(self):
        for attributes in ('+script filter="custom-filter"',
                           'virtual=x86_64,bios filter="custom-filter"'):
            with self.subTest(attributes=attributes):
                parsed = self.parse(f'[{attributes}] .filtered = {{\nMODE=hidden\nlaunch\n}}\n'
                                    '[+script filter=none] .visible = {\nvisible\n}\n')
                self.assertEqual([c.name for c in parsed.commands], ["visible"])
                self.assertNotIn("MODE", parsed.commands[0].env)
                self.assertIn("script_filter", [c.code for c in parsed.coverage])


if __name__ == "__main__":
    unittest.main()
