"""The agent policy (`policy:`) and pinned commands (`commands:`)."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_agentfiles import Fixture, write  # noqa: E402

from agentfiles.config import Config  # noqa: E402
from agentfiles.policy import (DEFAULT_GATES, DEFAULT_POLICY, check_project_policy, merge_policy,  # noqa: E402
                               parse_policy, render_policy)
from agentfiles.util import AgentfilesError  # noqa: E402


class PolicyMergeTest(unittest.TestCase):
    def merged(self, *partials):
        out = DEFAULT_POLICY
        for p in partials:
            out = merge_policy(out, parse_policy(p, "test"))
        return out

    def test_defaults(self):
        p = self.merged({})
        self.assertEqual(p["gates"], list(DEFAULT_GATES))
        self.assertEqual(p["budgets"]["tier2"]["usd"], 50)

    def test_stricter_always_wins(self):
        p = self.merged(
            {"gates": ["prod-data"], "budgets": {"tier2": {"usd": 30, "wall_clock": "10h"}},
             "security": {"network_allow": ["github.com", "example.com"], "redact_patterns": ["acme_[0-9]{8}"],
                          "sandbox_unattended": [1]},
             "audit": {"sessions": {"lfs_over_mb": 50, "archive": False}}},
            {"gates": ["migration"], "budgets": {"tier2": {"usd": 90, "tokens": 1000}},
             "security": {"redact_patterns": ["wid-[0-9]{6}"]}})
        self.assertEqual(p["gates"], list(DEFAULT_GATES) + ["prod-data"], "gates only accumulate")
        self.assertEqual(p["budgets"]["tier2"], {"usd": 30, "tokens": 1000, "wall_clock": "8h", "max_parallel_agents": 4},
                         "every budget takes the lowest value it was given")
        self.assertEqual(p["security"]["network_allow"], ["github.com"], "a later profile narrows, never widens")
        self.assertEqual(p["security"]["redact_patterns"], ["acme_[0-9]{8}", "wid-[0-9]{6}"])
        self.assertEqual(p["security"]["sandbox_unattended"], [1, 2, 3])
        self.assertEqual(p["audit"]["sessions"], {"archive": True, "lfs_over_mb": 20}, "archiving can't be turned off")

    def test_identity_is_the_last_word_not_the_strictest(self):
        p = self.merged({"identity": {"human": "a@github"}}, {"identity": {"human": "b@github"}})
        self.assertEqual(p["identity"], {"human": "b@github", "scheduled_owner": "creator"})

    def test_bad_policies_are_named(self):
        cases = [({"version": True}, "version"), ({"budgets": [1]}, "must map"),
                 ({"audit": {"sinks": [[1]]}}, "M0"),
                 ({"security": {"redact_patterns": ["secret #[0-9]+"]}}, "can't read those back"),
                 ({"security": {"redact_patterns": ["a\x0bb"]}}, "control characters"),
                 ({"security": {"redact_patterns": ["redact_patterns"]}}, "redact_patterns"),
                 ({"gate": []}, "unknown keys"), ({"gates": "spend"}, "list of gate ids"),
                 ({"budgets": {"tier9": {}}}, "unknown tier"), ({"budgets": {"tier2": {"usd": 0}}}, "positive"),
                 ({"budgets": {"tier2": {"usd": True}}}, "positive"),
                 ({"budgets": {"tier2": {"wall_clock": "soon"}}}, "duration"),
                 ({"security": {"redact_patterns": ["("]}}, "not a valid regex"),
                 ({"security": {"network_allow": ["bad host!"]}}, "host names"),
                 ({"audit": {"sinks": ["s3-object-lock"]}}, "M0"),
                 ({"identity": {"human": "lyddonb"}}, "<login>@github"),
                 ({"approvers": {"deploy": ["sre"]}}, "reserved"), ({"version": 2}, "version")]
        for raw, expect in cases:
            with self.subTest(raw=raw), self.assertRaisesRegex(AgentfilesError, expect):
                parse_policy(raw, "test")


class PolicyRenderTest(unittest.TestCase):
    def test_render_reads_back_and_quotes_patterns_for_agent_ledger(self):
        p = merge_policy(DEFAULT_POLICY, parse_policy(
            {"security": {"redact_patterns": [r"\bacme_[a-z0-9]{32}\b", "it's"]},
             "identity": {"human": "lyddonb@github"}}, "test"))
        text = render_policy(["builder"], p)
        self.assertEqual(yaml.safe_load(text), p)
        # agent-ledger's reader takes `redact_patterns:` then `    - '<pattern>'` lines only.
        self.assertIn("  redact_patterns:\n    - '\\bacme_[a-z0-9]{32}\\b'\n    - 'it''s'\n", text)

    def test_an_identity_that_would_confuse_agent_ledger_is_refused(self):
        p = merge_policy(DEFAULT_POLICY, parse_policy({"identity": {"human": "redact_patterns@github"}}, "t"))
        with self.assertRaisesRegex(AgentfilesError, "outside its own key"):
            render_policy(["t"], p)

    def test_tricky_values_still_read_back(self):
        p = merge_policy(DEFAULT_POLICY, parse_policy(
            {"gates": ["no", "on", "null"], "security": {"redact_patterns": ["#x", "a: b", "- y", "0x1f"]}}, "t"))
        self.assertEqual(yaml.safe_load(render_policy(["t"], p)), p)


class ProjectPolicyCheckTest(Fixture):
    def check(self, text, user=None):
        path = self.tmp / "proj" / ".agents" / "policy.yaml"
        write(path, text)
        return check_project_policy(path, user)

    def test_a_project_can_add_gates_but_not_remove_one(self):
        self.assertEqual(self.check("gates: [" + ", ".join(DEFAULT_GATES) + ", prod-data]\n"), [])
        problems = self.check("gates: [migration, spend]\n")
        self.assertEqual(len(problems), 1)
        self.assertIn("missing delete-data", problems[0])

    def test_a_user_gate_the_project_omits_is_still_required(self):
        user = merge_policy(DEFAULT_POLICY, {"gates": ["prod-data"]})
        problems = self.check("gates: [" + ", ".join(DEFAULT_GATES) + "]\n", user)
        self.assertIn("missing prod-data", problems[0])

    def test_a_project_can_only_tighten_the_rest_too(self):
        cases = [("budgets:\n  tier2: {usd: 9999}\n", "above yours"),
                 ("budgets:\n  tier3: {wall_clock: 30d}\n", "above yours"),
                 ("security:\n  network_allow: [evil.example.com]\n", "adds evil.example.com"),
                 ("security:\n  sandbox_unattended: [3]\n", "drops tier 2"),
                 ("audit:\n  sessions: {archive: false}\n", "can't be turned off"),
                 ("audit:\n  sessions: {lfs_over_mb: 500}\n", "lfs_over_mb")]
        for text, expect in cases:
            with self.subTest(text=text):
                problems = self.check(text)
                self.assertTrue(any(expect in p for p in problems), problems)
        self.assertEqual(self.check("budgets:\n  tier2: {usd: 10}\nsecurity:\n  network_allow: [github.com]\n"), [])

    def test_no_gate_list_keeps_every_gate(self):
        self.assertEqual(self.check("budgets:\n  tier2: {usd: 20}\n"), [])

    def test_broken_files_are_problems(self):
        self.assertIn("can't read it as YAML", self.check("gates: [a\n")[0])
        self.assertIn("unknown keys", self.check("gatez: []\n")[0])

    def test_cli_exit_codes(self):
        path = self.tmp / "p.yaml"
        write(path, "gates: [spend]\n")
        code, out = self.run_cli("policy", "check", str(path))
        self.assertEqual(code, 1)
        self.assertIn("gates can be added, not removed", out)
        write(path, "gates: [" + ", ".join(DEFAULT_GATES) + "]\n")
        self.assertEqual(self.run_cli("policy", "check", str(path))[0], 0)
        self.assertEqual(self.run_cli("policy", "check", str(self.tmp / "missing.yaml"))[0], 2)


class PolicySyncTest(Fixture):
    def setUp(self):
        super().setUp()
        write(self.repo / "profiles" / "governed.yaml", """
            extends: [base]
            policy:
              gates: [prod-data]
              budgets: {tier2: {usd: 40}}
            """)
        self.policy = self.home / ".agents" / "policy.yaml"

    def sync(self, *profiles):
        code, out = self.run_cli("sync", *profiles, "--targets", "codex")
        self.assertEqual(code, 0, out)
        return out

    def test_sync_writes_the_merged_policy_and_uninstall_removes_it(self):
        self.sync("governed")
        p = yaml.safe_load(self.policy.read_text())
        self.assertEqual(p["gates"], list(DEFAULT_GATES) + ["prod-data"])
        self.assertEqual(p["budgets"]["tier2"]["usd"], 40)
        self.assertNotIn("+ policy", self.sync("governed"), "a second sync changes nothing")
        code, out = self.run_cli("status")
        self.assertIn("Policy: 11 gates", out)
        self.assertEqual(self.run_cli("uninstall", "--yes")[0], 0)
        self.assertFalse(self.policy.exists())

    def test_profiles_without_policy_write_none(self):
        self.sync("base")
        self.assertFalse(self.policy.exists())

    def test_local_yaml_can_lower_a_budget_but_not_raise_one(self):
        write(self.repo / "local.yaml", "policy:\n  budgets: {tier2: {usd: 10, tokens: 999999999}}\n")
        self.sync("governed")
        b = yaml.safe_load(self.policy.read_text())["budgets"]["tier2"]
        self.assertEqual((b["usd"], b["tokens"]), (10, 8000000))

    def test_agentfiles_yaml_and_local_yaml_policies_combine(self):
        committed = (self.repo / "agentfiles.yaml").read_text()
        (self.repo / "agentfiles.yaml").write_text(committed + "policy:\n  gates: [extra-gate]\n  budgets: {tier2: {usd: 5}}\n")
        write(self.repo / "local.yaml", "policy:\n  budgets: {tier3: {usd: 100}}\n")
        self.sync("base")
        p = yaml.safe_load(self.policy.read_text())
        self.assertIn("extra-gate", p["gates"], "local.yaml can't drop what agentfiles.yaml tightened")
        self.assertEqual((p["budgets"]["tier2"]["usd"], p["budgets"]["tier3"]["usd"]), (5, 100))

    def test_dropping_policy_removes_the_file_unless_edited(self):
        self.sync("governed")
        self.sync("base")
        self.assertFalse(self.policy.exists())
        self.sync("governed")
        self.policy.write_text(self.policy.read_text() + "# mine\n")
        out = self.sync("base")
        self.assertTrue(self.policy.exists())
        self.assertIn("edited by hand", out)

    def test_a_policy_file_agentfiles_didnt_write_is_left_alone(self):
        write(self.policy, "gates: [spend]\n")
        out = self.sync("governed")
        self.assertEqual(self.policy.read_text(), "gates: [spend]\n")
        self.assertIn("not written by agentfiles", out)

    def test_project_sync_leaves_policy_to_the_project(self):
        proj = self.tmp / "proj"
        write(proj / ".agentfiles.yaml", "extends: [governed]\n")
        subprocess.run(["git", "init", "-q", str(proj)], check=True)
        cwd = os.getcwd()
        os.chdir(proj)
        try:
            code, out = self.run_cli("sync", "--project", "--targets", "codex")
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 0, out)
        self.assertIn("agentfiles policy check", out)
        self.assertFalse((proj / ".agents" / "policy.yaml").exists())


class CommandTest(Fixture):
    def setUp(self):
        super().setUp()
        # A git source holding a stdlib Python CLI, pinned like any other source.
        tool = self.tmp / "tool"
        write(tool / "ci" / "run.py", "import os, sys\n"
              "sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))\n"
              "import pkg\n"
              "print('tool ran with', sys.argv[1:], 'isolated', sys.flags.isolated)\n")
        write(tool / "src" / "pkg.py", "VERSION = 1\n")
        for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                     ["-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "v1"]):
            subprocess.run(["git", "-C", str(tool), *args], check=True)
        self.tool = tool
        sources = (self.repo / "sources.yaml").read_text()
        (self.repo / "sources.yaml").write_text(sources + f"  tool:\n    git: file://{tool}\n    ref: main\n")
        write(self.repo / "profiles" / "cli.yaml", """
            extends: [base]
            commands:
              mytool: tool:ci/run.py
            """)
        self.bin = self.home / ".local" / "bin"
        self.shim = self.bin / "mytool"

    def sync(self, *profiles):
        code, out = self.run_cli("sync", *profiles, "--targets", "codex")
        self.assertEqual(code, 0, out)
        return out

    def run_shim(self, *args):
        return subprocess.run([str(self.shim), *args], capture_output=True, text=True,
                              env=dict(os.environ, PATH=f"{os.path.dirname(sys.executable)}:/usr/bin:/bin"))

    def test_sync_installs_a_shim_that_runs_the_pinned_tree_isolated(self):
        out = self.sync("cli")
        self.assertTrue(os.access(self.shim, os.X_OK))
        commit = subprocess.run(["git", "-C", str(self.tool), "rev-parse", "HEAD"], capture_output=True,
                                text=True).stdout.strip()
        text = self.shim.read_text()
        self.assertIn(f"commit {commit[:12]}", text)
        self.assertIn(f"/trees/tool/{commit}/ci/run.py", text)
        proc = self.run_shim("a b", "c")
        self.assertEqual(proc.stdout.strip(), "tool ran with ['a b', 'c'] isolated 1")
        lock = (self.repo / "agentfiles.lock").read_text()
        self.assertIn('"command:mytool"', lock, "the tree's hash is pinned in the lock")
        self.assertIn("not on your PATH", out)

    def test_a_cleared_cache_gives_a_clear_message_and_sync_restores_it(self):
        import shutil
        self.sync("cli")
        tree = next((self.home / ".cache" / "agentfiles" / "trees" / "tool").iterdir())
        shutil.rmtree(tree)
        proc = self.run_shim()
        self.assertEqual(proc.returncode, 127)
        self.assertIn("run `agentfiles sync` to restore it", proc.stderr)
        self.sync("cli")
        self.assertIn("tool ran with", self.run_shim().stdout)

    def test_running_the_command_doesnt_make_the_next_sync_cry_tamper(self):
        self.sync("cli")
        self.assertEqual(self.run_shim().returncode, 0)
        tree = next((self.home / ".cache" / "agentfiles" / "trees" / "tool").iterdir())
        self.assertFalse(list(tree.rglob("__pycache__")), "-B keeps bytecode out of the pinned tree")
        cache = tree / "src" / "__pycache__"
        os.chmod(tree / "src", 0o755)
        cache.mkdir()
        (cache / "pkg.cpython-312.pyc").write_bytes(b"\x00junk")  # as another interpreter might leave
        code, out = self.run_cli("lock", "--frozen")
        self.assertEqual(code, 0, out)
        self.sync("cli")

    def test_the_pinned_tree_is_read_only_and_python_is_an_absolute_path(self):
        self.sync("cli")
        tree = next((self.home / ".cache" / "agentfiles" / "trees" / "tool").iterdir())
        self.assertFalse(os.access(tree / "ci" / "run.py", os.W_OK))
        exec_line = self.shim.read_text().splitlines()[-1]
        self.assertTrue(exec_line.startswith("exec '/"), exec_line)
        self.assertIn(" -I -B ", exec_line)

    def test_a_sitecustomize_on_pythonpath_is_ignored(self):
        self.sync("cli")
        evil = self.tmp / "evil"
        write(evil / "sitecustomize.py", "print('HIJACKED')\n")
        write(evil / "pkg.py", "print('HIJACKED')\n")
        proc = subprocess.run([str(self.shim)], capture_output=True, text=True, cwd=evil,
                              env=dict(os.environ, PYTHONPATH=str(evil)))
        self.assertNotIn("HIJACKED", proc.stdout + proc.stderr)
        self.assertIn("tool ran with", proc.stdout)

    def test_a_command_that_would_shadow_a_program_is_refused(self):
        other = self.tmp / "otherbin"
        write(other / "mytool", "#!/bin/sh\n")
        os.chmod(other / "mytool", 0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{other}:{old}"
        try:
            code, out = self.run_cli("sync", "cli", "--targets", "codex")
        finally:
            os.environ["PATH"] = old
        self.assertEqual(code, 2)
        self.assertIn("would shadow", out)
        for name in ("python3", "git", "sh"):
            write(self.repo / "profiles" / "bad.yaml", f"extends: [base]\ncommands: {{{name}: tool:ci/run.py}}\n")
            with self.subTest(name=name):
                self.assertIn("would shadow a basic tool", self.run_cli("sync", "bad", "--targets", "codex")[1])

    def test_a_binary_or_symlink_already_in_bin_dir_is_left_alone(self):
        self.bin.mkdir(parents=True)
        self.shim.write_bytes(b"\x7fELF\xff\xfe")
        out = self.sync("cli")
        self.assertEqual(self.shim.read_bytes(), b"\x7fELF\xff\xfe")
        self.assertIn("leaving it alone", out)
        self.shim.unlink()
        target = self.tmp / "elsewhere"
        self.shim.symlink_to(target)
        self.sync("cli")
        self.assertFalse(target.exists(), "a dangling symlink isn't followed")

    def test_a_relative_bin_dir_is_refused(self):
        write(self.repo / "local.yaml", "bin_dir: relbin\n")
        code, out = self.run_cli("sync", "cli", "--targets", "codex")
        self.assertEqual(code, 2)
        self.assertIn("absolute path", out)

    def test_a_new_upstream_commit_doesnt_change_the_command_until_update(self):
        self.sync("cli")
        before = self.shim.read_text()
        write(self.tool / "ci" / "run.py", "print('v2')\n")
        subprocess.run(["git", "-C", str(self.tool), "-c", "user.name=t", "-c", "user.email=t@e",
                        "commit", "-qam", "v2"], check=True)
        self.sync("cli")
        self.assertEqual(self.shim.read_text(), before, "the lock keeps the old commit")
        self.assertIn("tool ran with", self.run_shim().stdout)

    def test_dropping_the_command_removes_the_shim_and_uninstall_too(self):
        self.sync("cli")
        self.sync("base")
        self.assertFalse(self.shim.exists())
        self.sync("cli")
        self.assertEqual(self.run_cli("uninstall", "--yes")[0], 0)
        self.assertFalse(self.shim.exists())

    def test_an_existing_command_agentfiles_didnt_write_is_left_alone(self):
        write(self.shim, "#!/bin/sh\necho mine\n")
        out = self.sync("cli")
        self.assertEqual(self.shim.read_text(), "#!/bin/sh\necho mine\n")
        self.assertIn("not written by agentfiles", out)

    def test_bad_command_entries_are_refused(self):
        for text, expect in [("commands: {Bad: tool:ci/run.py}\n", "lowercase"),
                             ("commands: {x: tool:ci}\n", ".py script"),
                             ("commands: {x: tool:@entry}\n", "only valid for plugins"),
                             ("commands: {x: nope:ci/run.py}\n", "unknown source"),
                             ("commands: {x: tool:../etc/run.py}\n", "not allowed")]:
            write(self.repo / "profiles" / "bad.yaml", "extends: [base]\n" + text)
            with self.subTest(text=text):
                code, out = self.run_cli("sync", "bad", "--targets", "codex")
                self.assertEqual(code, 2, out)
                self.assertIn(expect, out)

    def test_a_missing_script_is_named(self):
        write(self.repo / "profiles" / "bad.yaml", "extends: [base]\ncommands: {x: tool:ci/nope.py}\n")
        code, out = self.run_cli("sync", "bad", "--targets", "codex")
        self.assertEqual(code, 2)
        self.assertIn("ci/nope.py not found in source tool", out)

    def test_update_reviews_the_whole_tree_of_a_command_source(self):
        from agentfiles.cli import _paths_used
        self.assertEqual(_paths_used(Config(self.repo), "tool"), ["."])


if __name__ == "__main__":
    unittest.main()
