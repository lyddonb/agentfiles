"""Offline tests for agentfiles. Run with:  python3 -m unittest discover -s tests

They build a throwaway agentfiles repo whose only source is a local directory, so no
network or agent CLIs are needed. Claude Code steps are exercised in dry-run mode.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agentfiles import cli
from agentfiles.config import Config, parse_ref
from agentfiles.resolve import resolve_plugin
from agentfiles.config import Item
from agentfiles.targets import mcp_snippets, to_claude_mcp
from agentfiles.util import AgentfilesError


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip())


def skill(root: Path, name: str, desc: str = "Does a thing. Use when testing.") -> None:
    write(root / name / "SKILL.md", f"""
        ---
        name: {name}
        description: {desc}
        ---
        Body of {name}.
        """)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()
        self._env = {k: os.environ.get(k) for k in ("HOME", "AGENTFILES_HOME", "XDG_CACHE_HOME",
                                                     "XDG_DATA_HOME", "XDG_STATE_HOME", "PATH")}
        os.environ["HOME"] = str(self.home)
        for k in ("XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            os.environ.pop(k, None)
        os.environ["PATH"] = "/usr/bin:/bin"          # hide any real `claude` binary

        # upstream "repo": two loose skills, a skills folder, and a Claude marketplace
        up = self.tmp / "upstream"
        skill(up / "skills", "alpha")
        skill(up / "skills", "beta")
        skill(up / "plugins" / "kit" / "skills", "gamma")
        write(up / "plugins" / "kit" / ".claude-plugin" / "plugin.json", '{"name": "kit"}')
        write(up / "plugins" / "hooky" / "hooks" / "hooks.json", '{"hooks": {}}')
        skill(up / "plugins" / "hooky" / "skills", "delta")
        write(up / ".claude-plugin" / "marketplace.json", json.dumps({
            "name": "upstream", "owner": {"name": "x"},
            "plugins": [{"name": "kit", "source": "./plugins/kit"},
                        {"name": "hooky", "source": "./plugins/hooky"},
                        {"name": "bundle", "source": "./", "strict": False,
                         "skills": ["./skills/alpha"]}]}))
        self.up = up

        repo = self.tmp / "repo"
        write(repo / "sources.yaml", f"""
            sources:
              up:
                path: {up}
            """)
        write(repo / "agentfiles.yaml", """
            targets: [codex, claude-code]
            default_profiles: [base]
            """)
        write(repo / "profiles" / "base.yaml", """
            description: base
            skills:
              - up:skills/alpha
            plugins:
              - up:@kit
            """)
        write(repo / "profiles" / "more.yaml", """
            description: more
            extends: [base]
            skills:
              - up:skills
            plugins:
              - up:plugins/hooky
            mcp:
              docs: {type: streamable-http, url: https://example.com/mcp}
            exclude:
              plugins: [up:@kit]
            """)
        self.repo = repo
        os.environ["AGENTFILES_HOME"] = str(repo)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def run_cli(self, *argv) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue() + err.getvalue()


class ConfigTests(Fixture):
    def test_parse_ref(self):
        self.assertEqual(parse_ref("a:b/c", "skill"), ("a", "b/c", None))
        self.assertEqual(parse_ref("a:@x", "plugin"), ("a", None, "x"))
        with self.assertRaises(AgentfilesError):
            parse_ref("a:@x", "skill")
        with self.assertRaises(AgentfilesError):
            parse_ref("a:../etc", "skill")

    def test_extends_and_exclude(self):
        r = Config(self.repo).resolve(["more"])
        self.assertEqual(r.profiles, ["base", "more"])
        self.assertEqual([p.ref for p in r.plugins], ["up:plugins/hooky"])
        self.assertIn("docs", r.mcp)

    def test_cycle_detected(self):
        write(self.repo / "profiles" / "a.yaml", "extends: [b]\n")
        write(self.repo / "profiles" / "b.yaml", "extends: [a]\n")
        with self.assertRaisesRegex(AgentfilesError, "cycle"):
            Config(self.repo).resolve(["a"])

    def test_unknown_source(self):
        write(self.repo / "profiles" / "bad.yaml", "skills: [nope:x]\n")
        with self.assertRaisesRegex(AgentfilesError, "unknown source"):
            Config(self.repo).resolve(["bad"])


class ResolveTests(Fixture):
    def test_plugin_by_entry_with_explicit_skills(self):
        item = Item(kind="plugin", ref="up:@bundle", source="up", entry="bundle")
        p = resolve_plugin(item, self.up)
        self.assertEqual([s.name for s in p.skills], ["alpha"])
        self.assertIsNotNone(p.claude)
        self.assertEqual([x.name for x in p.claude.skills], ["alpha"])

    def test_hooks_need_allow(self):
        item = Item(kind="plugin", ref="up:plugins/hooky", source="up", path="plugins/hooky")
        p = resolve_plugin(item, self.up)
        self.assertEqual(p.blocked, {"hooks"})


class McpTests(unittest.TestCase):
    def test_claude_translation(self):
        self.assertEqual(to_claude_mcp("x", {"type": "streamable-http", "url": "https://a"}),
                         {"type": "http", "url": "https://a"})
        self.assertEqual(to_claude_mcp("y", {"type": "stdio", "command": "npx", "args": ["z"]}),
                         {"type": "stdio", "command": "npx", "args": ["z"]})

    def test_snippets(self):
        snip = mcp_snippets({"x": {"type": "streamable-http", "url": "https://a"},
                             "y": {"type": "stdio", "command": "npx", "args": ["z"]}})
        self.assertIn('[mcp_servers.x]\nurl = "https://a"', snip["codex.toml"])
        oc = json.loads(snip["opencode.json"])["mcp"]
        self.assertEqual(oc["y"], {"type": "local", "command": ["npx", "z"]})


class SyncTests(Fixture):
    def test_sync_links_and_prunes(self):
        code, out = self.run_cli("sync", "more", "--targets", "codex")
        self.assertEqual(code, 0, out)
        shared = self.home / ".agents" / "skills"
        self.assertEqual(sorted(p.name for p in shared.iterdir()), ["alpha", "beta", "delta"])
        self.assertTrue((shared / "alpha").is_symlink())

        code, out = self.run_cli("sync", "base", "--targets", "codex")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in shared.iterdir()), ["alpha", "gamma"])

    def test_never_clobbers_unmanaged(self):
        shared = self.home / ".agents" / "skills"
        (shared / "alpha").mkdir(parents=True)
        code, out = self.run_cli("sync", "base", "--targets", "codex")
        self.assertEqual(code, 0, out)
        self.assertIn("not managed by agentfiles", out)
        self.assertFalse((shared / "alpha").is_symlink())

    def test_claude_dry_run_plan(self):
        code, out = self.run_cli("plan", "more", "--targets", "claude-code")
        self.assertEqual(code, 0, out)
        self.assertIn("claude plugin marketplace add", out)
        self.assertIn("ships hooks", out)               # hooky is blocked without allow
        self.assertIn("claude mcp add-json -s user docs", out)

    def test_project_scope(self):
        proj = self.tmp / "proj"
        write(proj / ".agentfiles.yaml", "extends: [base]\ntargets: [codex]\n")
        code, out = self.run_cli("sync", "--project", str(proj))
        self.assertEqual(code, 0, out)
        self.assertTrue((proj / ".agents" / "skills" / "alpha").is_symlink())
        self.assertTrue((proj / ".agentfiles" / "state.json").exists())

    def test_collision_is_an_error(self):
        skill(self.up / "other", "alpha")
        write(self.repo / "profiles" / "clash.yaml", "skills: [up:skills/alpha, up:other/alpha]\n")
        code, out = self.run_cli("sync", "clash", "--targets", "codex")
        self.assertEqual(code, 2)
        self.assertIn("collision", out)

    def test_requires_reports_manual_setup(self):
        os.environ.pop("AF_TEST_KEY", None)
        os.environ.pop("AF_TEST_SET", None)
        write(self.repo / "profiles" / "needs.yaml", """
            skills:
              - ref: up:skills/alpha
                requires:
                  commands: [sh, af-no-such-command]
                  env: [AF_TEST_KEY]
                  note: Get a key from example.com.
              - ref: up:skills/beta
                requires: {commands: [sh], env: [AF_TEST_SET]}
            """)
        os.environ["AF_TEST_SET"] = "1"
        try:
            code, out = self.run_cli("plan", "needs", "--targets", "codex")
        finally:
            os.environ.pop("AF_TEST_SET", None)
        self.assertEqual(code, 0, out)
        self.assertIn("Manual setup", out)
        self.assertIn("!!  up:skills/alpha", out)
        self.assertIn("not on PATH: af-no-such-command", out)
        self.assertIn("not set in this shell: AF_TEST_KEY", out)
        self.assertIn("Get a key from example.com.", out)
        self.assertIn("ok  up:skills/beta", out)

    def test_requires_rejects_unknown_keys(self):
        write(self.repo / "profiles" / "bad.yaml", """
            skills:
              - ref: up:skills/alpha
                requires: {packages: [x]}
            """)
        code, out = self.run_cli("list", "bad")
        self.assertEqual(code, 2)
        self.assertIn("unknown keys ['packages'] in requires", out)


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------- modes, roles, instructions

from agentfiles import instructions as ins  # noqa: E402
from agentfiles.cli import _paths_used  # noqa: E402


class ModedFixture(Fixture):
    def setUp(self):
        super().setUp()
        for k in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR"):
            self._env.setdefault(k, os.environ.get(k))
            os.environ.pop(k, None)
        write(self.repo / "profiles" / "moded.yaml", """
            description: with a mode
            extends: [base]
            mode: alpha
            instructions:
              - Prefer small PRs.
            roles:
              judgment: {claude-code: opus}
              reviewers: {claude-code: [opus, sonnet]}
            """)


class ModeAndRolesTests(ModedFixture):
    def test_roles_merge_and_machine_override(self):
        write(self.repo / "local.yaml", "roles:\n  judgment: {claude-code: sonnet, cursor: x-model}\n")
        r = Config(self.repo).resolve(["moded"])
        self.assertEqual(r.mode, "alpha")
        self.assertEqual(r.roles["judgment"], {"claude-code": "sonnet", "cursor": "x-model"})
        self.assertEqual(r.roles["reviewers"], {"claude-code": ["opus", "sonnet"]})
        self.assertEqual(r.instructions, ["Prefer small PRs."])

    def test_bad_role_and_tool_rejected(self):
        write(self.repo / "profiles" / "bad.yaml", "roles: {wizard: {claude-code: opus}}\n")
        with self.assertRaisesRegex(AgentfilesError, "unknown role"):
            Config(self.repo).resolve(["bad"])
        write(self.repo / "profiles" / "bad.yaml", "roles: {code: {vim: opus}}\n")
        with self.assertRaisesRegex(AgentfilesError, "unknown tool"):
            Config(self.repo).resolve(["bad"])

    def test_mode_must_be_installed(self):
        write(self.repo / "profiles" / "ghost.yaml", "extends: [base]\nmode: nope\n")
        code, out = self.run_cli("sync", "ghost", "--targets", "codex")
        self.assertEqual(code, 2)
        self.assertIn("mode 'nope' is not a skill", out)

    def test_mode_can_be_cleared(self):
        write(self.repo / "profiles" / "plain.yaml", "extends: [moded]\nmode: none\n")
        self.assertIsNone(Config(self.repo).resolve(["plain"]).mode)

    def test_block_upsert_is_idempotent_and_reversible(self):
        original = "# Mine\n\nKeep this.\n"
        once = ins.upsert_block(original, "Body one.\n")
        self.assertEqual(ins.upsert_block(once, "Body one.\n"), once)
        twice = ins.upsert_block(once, "Body two.\n")
        self.assertIn("Body two.", twice)
        self.assertNotIn("Body one.", twice)
        self.assertEqual(ins.remove_block(twice), original)
        self.assertEqual(ins.remove_block(ins.upsert_block("", "x\n")), "")

    def test_sync_writes_instructions_and_roles_then_uninstall_restores(self):
        codex_md = self.home / ".codex" / "AGENTS.md"
        write(codex_md, "# My notes\n")
        code, out = self.run_cli("sync", "moded", "--targets", "codex,claude-code,pi")
        self.assertEqual(code, 0, out)
        rules = self.home / ".claude" / "rules" / "agentfiles.md"
        self.assertIn("load the `alpha` skill", rules.read_text())
        self.assertIn("Prefer small PRs.", codex_md.read_text())
        self.assertTrue(codex_md.read_text().startswith("# My notes"))
        self.assertIn("reviewers", (self.home / ".agents" / "roles.yaml").read_text())
        self.assertTrue((self.home / ".pi" / "agent" / "AGENTS.md").exists())

        code, out = self.run_cli("sync", "moded", "--targets", "codex,claude-code,pi")
        self.assertNotIn("+ instructions", out)          # second run changes nothing

        code, out = self.run_cli("uninstall", "--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(codex_md.read_text(), "# My notes\n")
        self.assertFalse(rules.exists())
        self.assertFalse((self.home / ".agents" / "roles.yaml").exists())
        self.assertFalse((self.home / ".pi" / "agent" / "AGENTS.md").exists())

    def test_hand_edited_owned_file_is_left_alone(self):
        self.run_cli("sync", "moded", "--targets", "claude-code")
        rules = self.home / ".claude" / "rules" / "agentfiles.md"
        rules.write_text(rules.read_text() + "my edit\n")
        code, out = self.run_cli("uninstall", "--yes")
        self.assertIn("edited by hand", out)
        self.assertTrue(rules.exists())

    def test_opencode_never_hides_claude_md(self):
        write(self.home / ".claude" / "CLAUDE.md", "# global claude notes\n")
        code, out = self.run_cli("sync", "moded", "--targets", "opencode")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.home / ".config" / "opencode" / "AGENTS.md").exists())
        self.assertIn("instructions` list", out)

    def test_project_gets_only_differences(self):
        self.run_cli("sync", "moded", "--targets", "claude-code")
        proj = self.tmp / "proj"
        write(proj / ".agentfiles.yaml", "extends: [moded]\ntargets: [claude-code]\n")
        code, out = self.run_cli("sync", "--project", str(proj))
        self.assertIn("match your global sync", out)
        self.assertFalse((proj / ".claude" / "rules" / "agentfiles.md").exists())

        write(proj / ".agentfiles.yaml",
              "extends: [moded]\ntargets: [claude-code]\ninstructions: [Use pnpm here.]\n")
        code, out = self.run_cli("sync", "--project", str(proj))
        text = (proj / ".claude" / "rules" / "agentfiles.md").read_text()
        self.assertIn("Use pnpm here.", text)
        self.assertNotIn("alpha", text)                  # the mode line is already global

    def test_watch_paths_used_for_unused_sources(self):
        write(self.repo / "sources.yaml", f"""
            sources:
              up:
                path: {self.up}
              upstream-only:
                git: https://example.com/x.git
                watch: [pkg]
            """)
        self.assertEqual(_paths_used(Config(self.repo), "upstream-only"), ["pkg"])


class ReviewRegressionTests(ModedFixture):
    """Cases found in review: never lose user text, never strand Cursor, never forget ownership."""

    def test_unbalanced_markers_are_left_alone(self):
        codex_md = self.home / ".codex" / "AGENTS.md"
        self.run_cli("sync", "moded", "--targets", "codex")
        broken = codex_md.read_text().replace(ins.END + "\n", "") + "\nMy precious notes.\n"
        codex_md.write_text(broken)
        for _ in range(2):
            code, out = self.run_cli("sync", "moded", "--targets", "codex")
            self.assertIn("agentfiles markers", out)
            self.assertEqual(codex_md.read_text(), broken)

    def test_remove_block_keeps_paragraph_spacing(self):
        text = ins.upsert_block("A\n", "x\n") + "\nB\n"
        self.assertEqual(ins.remove_block(text), "A\n\nB\n")

    def test_cursor_project_copy_is_always_complete(self):
        self.run_cli("sync", "moded", "--targets", "cursor,claude-code")
        proj = self.tmp / "proj"
        write(proj / ".agentfiles.yaml", "extends: [moded]\ntargets: [cursor, claude-code]\n")
        code, out = self.run_cli("sync", "--project", str(proj))
        self.assertEqual(code, 0, out)
        mdc = (proj / ".cursor" / "rules" / "agentfiles.mdc").read_text()
        self.assertIn("load the `alpha` skill", mdc)
        self.assertIn("Prefer small PRs.", mdc)
        self.assertFalse((proj / ".claude" / "rules" / "agentfiles.md").exists())

    def test_edited_roles_file_keeps_ownership_and_warns_once(self):
        self.run_cli("sync", "moded", "--targets", "claude-code")
        roles = self.home / ".agents" / "roles.yaml"
        roles.write_text(roles.read_text() + "# mine\n")
        code, out = self.run_cli("sync", "moded", "--targets", "claude-code")
        self.assertEqual(out.count("edited by hand"), 1)
        self.assertIn("`roles:`", out)
        code, out = self.run_cli("sync", "moded", "--targets", "claude-code")
        self.assertNotIn("not written by agentfiles", out)
        self.assertIn("edited by hand", out)
