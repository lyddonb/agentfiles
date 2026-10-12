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
