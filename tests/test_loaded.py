"""doctor's Claude Code load check (ROADMAP R16), with a fake `claude` that replays an init event."""
from __future__ import annotations

import json
import os
import stat
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_agentfiles import Fixture, skill, write  # noqa: E402

from agentfiles.loaded import Expected, compare  # noqa: E402

FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if "--json" in args:
    print("[]")
elif "-p" in args:
    print(json.dumps({"type": "system", "subtype": "hook_started"}))
    init = os.environ.get("FAKE_INIT")
    if init:
        print(open(init).read().strip())
"""


def init_event(plugins: dict[str, str], skills: list[str], commands: list[str] = ()) -> dict:
    return {"type": "system", "subtype": "init", "claude_code_version": "test",
            "plugins": [{"name": n, "source": s} for n, s in plugins.items()],
            "skills": list(skills), "slash_commands": list(skills) + list(commands)}


class CompareTests(unittest.TestCase):
    expected = Expected("agentfiles-local", {"agentfiles": frozenset({"alpha"}), "kit": frozenset({"gamma"})})
    ours = {"agentfiles": "agentfiles@agentfiles-local", "kit": "kit@agentfiles-local"}

    def test_everything_loaded_is_clean(self):
        r = compare(self.expected, init_event(self.ours, ["agentfiles:alpha", "kit:gamma", "other:x"]))
        self.assertEqual((r.problems, r.notes), ([], []), "skills from other marketplaces are not ours to judge")

    def test_a_skill_dropped_to_a_command_is_named_with_its_cause(self):
        r = compare(self.expected, init_event(self.ours, ["kit:gamma"], ["agentfiles:alpha"]))
        self.assertEqual(len(r.problems), 1, r.problems)
        self.assertIn("agentfiles:alpha loaded only as a slash command", r.problems[0])

    def test_a_skill_missing_everywhere(self):
        r = compare(self.expected, init_event(self.ours, ["kit:gamma"]))
        self.assertEqual(r.problems, ["skill agentfiles:alpha is installed but Claude Code did not load it"])

    def test_a_plugin_shadowed_by_another_marketplace(self):
        plugins = {"agentfiles": "agentfiles@agentfiles-local", "kit": "kit@elsewhere"}
        r = compare(self.expected, init_event(plugins, ["agentfiles:alpha", "kit:gamma"]))
        self.assertEqual(len(r.problems), 1, r.problems)
        self.assertIn("plugin kit: Claude Code loaded it from kit@elsewhere", r.problems[0])

    def test_a_plugin_not_loaded(self):
        r = compare(self.expected, init_event({"agentfiles": "agentfiles@agentfiles-local"}, ["agentfiles:alpha"]))
        self.assertEqual(r.problems, ["plugin kit@agentfiles-local is installed but Claude Code did not load it"])

    def test_a_stale_skill_in_our_plugin(self):
        r = compare(self.expected, init_event(self.ours, ["agentfiles:alpha", "agentfiles:old", "kit:gamma"]))
        self.assertEqual(len(r.problems), 1, r.problems)
        self.assertIn("agentfiles:old is loaded but the last sync did not install it", r.problems[0])

    def test_user_invocable_false_is_a_note(self):
        expected = Expected(self.expected.marketplace, self.expected.plugins, frozenset({"agentfiles:alpha"}))
        r = compare(expected, init_event(self.ours, ["kit:gamma"]))
        self.assertEqual(r.problems, [], "a skill hidden on purpose is not a failure")
        self.assertEqual(len(r.notes), 1, r.notes)


class DoctorLoadCheckTests(Fixture):
    def setUp(self):
        super().setUp()
        bin_dir = self.tmp / "bin"
        fake = bin_dir / "claude"
        write(fake, FAKE_CLAUDE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        os.environ["PATH"] = f"{bin_dir}:/usr/bin:/bin"
        self._env.setdefault("FAKE_INIT", os.environ.get("FAKE_INIT"))
        self.init_file = self.tmp / "init.json"
        os.environ["FAKE_INIT"] = str(self.init_file)

    def claude_reports(self, skills: list[str], commands: list[str] = ()) -> None:
        plugins = {"agentfiles": "agentfiles@agentfiles-local", "kit": "kit@agentfiles-local"}
        self.init_file.write_text(json.dumps(init_event(plugins, skills, commands)))

    def test_passes_after_a_clean_sync(self):
        code, out = self.run_cli("sync", "base", "--targets", "claude-code")
        self.assertEqual(code, 0, out)
        self.claude_reports(["agentfiles:alpha", "kit:gamma"])
        code, out = self.run_cli("doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("loaded all 2 agentfiles plugins and 2 skills from the last sync", out)

    def test_fails_on_a_skill_with_no_description(self):
        write(self.up / "skills" / "alpha" / "SKILL.md", """
            ---
            name: alpha
            ---
            Body with no description in the header.
            """)
        code, out = self.run_cli("sync", "base", "--targets", "claude-code")
        self.assertEqual(code, 0, f"sync installs the skill without a complaint, which is why doctor checks:\n{out}")
        self.claude_reports(["kit:gamma"], ["agentfiles:alpha"])
        code, out = self.run_cli("doctor")
        self.assertEqual(code, 1, out)
        self.assertIn("agentfiles:alpha loaded only as a slash command", out)

    def test_no_init_event_is_a_problem(self):
        code, out = self.run_cli("sync", "base", "--targets", "claude-code")
        self.assertEqual(code, 0, out)
        code, out = self.run_cli("doctor")
        self.assertEqual(code, 1, out)
        self.assertIn("gave no init event", out)

    def test_skipped_without_a_claude_sync(self):
        os.environ["PATH"] = "/usr/bin:/bin"
        code, out = self.run_cli("doctor")
        self.assertIn("Claude Code load check: the last sync installed no Claude Code plugins", out)
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
