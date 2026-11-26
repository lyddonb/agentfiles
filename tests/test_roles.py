"""`cli:<agent>:<model>` role entries, which agent-kit's second_opinion.py runs."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_agentfiles import ModedFixture, write  # noqa: E402

from agentfiles.config import CLI_AGENTS, Config, parse_roles  # noqa: E402
from agentfiles.util import AgentfilesError, cache_dir  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AGENT_KIT_GIT = "https://github.com/lyddonb/agent-kit"
SECOND_OPINION = "plugins/bstack/skills/beau-mode/scripts/second_opinion.py"


def roles(model):
    return parse_roles({"reviewers": {"claude-code": model}}, "profile p")


class CliRoleShapeTests(unittest.TestCase):
    def test_good_entries_pass_unchanged(self):
        for model in ("cli:cursor-agent:gpt-5.6-sol-high", "cli:claude:opus", "cli:claude:a:b",
                      ["opus", "cli:cursor-agent:gpt-5.6-sol-high"], "opus", "inherit", "client:x"):
            with self.subTest(model=model):
                self.assertEqual(roles(model), {"reviewers": {"claude-code": model}})

    def test_each_bad_shape_fails_and_names_the_entry(self):
        cases = {
            "CLI:cursor-agent:gpt-5": "bad CLI entry",
            " cli:cursor-agent:gpt-5": "bad CLI entry",
            "cli:": "bad CLI entry",
            "cli:cursor-agent": "bad CLI entry",
            "cli::gpt-5": "unknown CLI agent ''",
            "cli:codex:gpt-5": "unknown CLI agent 'codex'",
            "cli:cursor-agent:": "has no model",
            "cli:cursor-agent:  ": "has no model",
        }
        for model, why in cases.items():
            for shape in (model, ["opus", model]):
                with self.subTest(model=shape):
                    with self.assertRaises(AgentfilesError) as e:
                        roles(shape)
                    msg = str(e.exception)
                    self.assertIn(why, msg)
                    self.assertIn(repr(model), msg, "the error quotes the entry as written")
                    self.assertIn("roles.reviewers.claude-code", msg, "the error names where it is")
                    self.assertIn("claude, cursor-agent", msg, "the error lists the agents that run")

    def test_documented_flow_form_parses_unquoted(self):
        raw = yaml.safe_load("reviewers: {claude-code: [opus, cli:cursor-agent:gpt-5.6-sol-high]}\n")
        self.assertEqual(parse_roles(raw, "doc")["reviewers"]["claude-code"],
                         ["opus", "cli:cursor-agent:gpt-5.6-sol-high"])


class CliRoleSyncTests(ModedFixture):
    def test_sync_writes_a_good_entry_verbatim(self):
        write(self.repo / "profiles" / "xmodel.yaml",
              "extends: [moded]\nroles:\n  reviewers: {claude-code: [opus, cli:cursor-agent:gpt-5.6-sol-high]}\n")
        code, out = self.run_cli("sync", "xmodel", "--targets", "claude-code")
        self.assertEqual(code, 0, out)
        written = yaml.safe_load((self.home / ".agents" / "roles.yaml").read_text())
        self.assertEqual(written["roles"]["reviewers"], {"claude-code": ["opus", "cli:cursor-agent:gpt-5.6-sol-high"]},
                         out)

    def test_sync_and_plan_refuse_a_bad_entry_and_write_nothing(self):
        write(self.repo / "profiles" / "bad.yaml",
              "extends: [moded]\nroles:\n  reviewers: {claude-code: [opus, cli:codex:gpt-5]}\n")
        for cmd in ("sync", "plan"):
            with self.subTest(cmd=cmd):
                code, out = self.run_cli(cmd, "bad", "--targets", "claude-code")
                self.assertEqual(code, 2, out)
                self.assertIn("unknown CLI agent 'codex' in 'cli:codex:gpt-5'", out)
        self.assertFalse((self.home / ".agents" / "roles.yaml").exists())

    def test_machine_roles_are_checked_too(self):
        write(self.repo / "local.yaml", "roles:\n  judgment: {cursor: 'cli:cursor-agent:'}\n")
        with self.assertRaisesRegex(AgentfilesError, "settings: roles.judgment.cursor: CLI entry .* has no model"):
            Config(self.repo).resolve(["moded"])


class CliAgentsMatchAgentKitTest(unittest.TestCase):
    """CLI_AGENTS copies the ADAPTERS keys of the second_opinion.py that agentfiles.lock installs.
    The source must be in the cache (any `agentfiles sync` or `lock` puts it there); CI sets
    AGENTFILES_REQUIRE_AGENT_KIT so a missing cache fails instead of skipping."""

    def locked_script(self) -> str:
        lock = json.loads((ROOT / "agentfiles.lock").read_text())
        name, entry = next((n, s) for n, s in lock["sources"].items() if s["git"] == AGENT_KIT_GIT)
        mirror = cache_dir() / "git" / f"{name}.git"
        p = subprocess.run(["git", "-C", str(mirror), "show", f"{entry['commit']}:{SECOND_OPINION}"],
                           capture_output=True, text=True)
        if p.returncode != 0:
            reason = f"agent-kit {entry['commit'][:12]} is not cached at {mirror}: {p.stderr.strip()}"
            if os.environ.get("AGENTFILES_REQUIRE_AGENT_KIT"):
                self.fail(reason)
            self.skipTest(reason)
        return p.stdout

    def test_known_agents_equal_second_opinion_adapters(self):
        tree = ast.parse(self.locked_script())
        adapters = next(node.value for node in tree.body
                        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "ADAPTERS")
        upstream = tuple(ast.literal_eval(k) for k in adapters.keys)
        self.assertEqual(CLI_AGENTS, upstream,
                         "agentfiles.config.CLI_AGENTS must list second_opinion.py's ADAPTERS in the locked agent-kit")


if __name__ == "__main__":
    unittest.main()
