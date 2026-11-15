"""`agentfiles lock` keeps the lockfile to exactly what the profiles use."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_agentfiles import Fixture, skill, write  # noqa: E402


class LockPruneTests(Fixture):
    def setUp(self):
        super().setUp()
        extra = self.tmp / "extra"
        skill(extra / "skills", "epsilon")
        for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                     ["-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "v1"]):
            subprocess.run(["git", "-C", str(extra), *args], check=True)
        self.sources = self.repo / "sources.yaml"
        self.sources_before = self.sources.read_text()
        self.sources.write_text(self.sources_before + f"  extra:\n    git: file://{extra}\n    ref: main\n")
        write(self.repo / "profiles" / "extra.yaml", """
            extends: [base]
            skills:
              - extra:skills/epsilon
            """)
        self.lockfile = self.repo / "agentfiles.lock"

    def lock(self, *args):
        return self.run_cli("lock", *args)

    def locked(self):
        return json.loads(self.lockfile.read_text())

    def drop_extra(self):
        (self.repo / "profiles" / "extra.yaml").unlink()

    def test_lock_prunes_a_source_no_profile_uses(self):
        code, out = self.lock()
        self.assertEqual(code, 0, out)
        self.assertIn("extra", self.locked()["sources"])

        self.drop_extra()
        self.sources.write_text(self.sources_before)
        code, out = self.lock()
        self.assertEqual(code, 0, out)
        self.assertNotIn("extra", self.locked()["sources"],
                         "a source removed from sources.yaml and every profile must leave the lock")
        self.assertFalse(any(":extra:" in k for k in self.locked()["items"]))

    def test_lock_keeps_a_source_still_defined_but_unused(self):
        self.assertEqual(self.lock()[0], 0)
        self.drop_extra()
        code, out = self.lock()
        self.assertEqual(code, 0, out)
        self.assertIn("extra", self.locked()["sources"],
                      "`update` pins every defined source, and a watched one keeps its reviewed "
                      "commit in the lock, so only removing it from sources.yaml may prune it")
        self.assertFalse(any(":extra:" in k for k in self.locked()["items"]))

    def test_lock_for_some_profiles_keeps_other_sources(self):
        self.assertEqual(self.lock()[0], 0)
        code, out = self.lock("base")
        self.assertEqual(code, 0, out)
        self.assertIn("extra", self.locked()["sources"],
                      "locking a subset of profiles must not prune what other profiles use")

    def test_frozen_fails_on_a_stale_lock_and_leaves_it_alone(self):
        self.assertEqual(self.lock()[0], 0)
        self.drop_extra()
        self.sources.write_text(self.sources_before)
        before = self.lockfile.read_text()
        code, out = self.lock("--frozen")
        self.assertNotEqual(code, 0, "--frozen must fail when the lock has entries no profile uses")
        self.assertIn("source extra", out)
        self.assertIn("skill:extra:skills/epsilon", out)
        self.assertEqual(self.lockfile.read_text(), before, "--frozen must never rewrite the lock")

    def test_frozen_passes_on_a_current_lock(self):
        self.assertEqual(self.lock()[0], 0)
        before = self.lockfile.read_text()
        code, out = self.lock("--frozen")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.lockfile.read_text(), before)

    # `update` moves a source; every lock item from that source must move with it.
    ITEM = "skill:extra:skills/epsilon"

    def new_upstream_commit(self) -> str:
        extra = self.tmp / "extra"
        skill(extra / "skills", "epsilon", desc="Does a thing, v2. Use when testing.")
        for args in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "v2"]):
            subprocess.run(["git", "-C", str(extra), *args], check=True)
        return subprocess.run(["git", "-C", str(extra), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_update_moves_the_items_of_the_source_it_moves(self):
        self.assertEqual(self.lock()[0], 0)
        new = self.new_upstream_commit()
        code, out = self.run_cli("update", "extra", "--yes")
        self.assertEqual(code, 0, out)
        lock = self.locked()
        self.assertEqual(lock["sources"]["extra"]["commit"], new)
        self.assertEqual(lock["items"][self.ITEM]["commit"], new,
                         "the item must be pinned to the commit its source moved to")
        before = self.lockfile.read_text()
        code, out = self.lock("--frozen")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.lockfile.read_text(), before, "after update, the lock is already current")

    def test_frozen_fails_when_an_item_lags_its_source(self):
        self.assertEqual(self.lock()[0], 0)
        new = self.new_upstream_commit()
        lock = self.locked()
        lock["sources"]["extra"]["commit"] = new  # what `update` used to leave: the source moved, the item didn't
        self.lockfile.write_text(json.dumps(lock, indent=2) + "\n")
        before = self.lockfile.read_text()
        code, out = self.lock("--frozen")
        self.assertNotEqual(code, 0, "--frozen must fail when an item is pinned to another commit than its source")
        self.assertIn(self.ITEM, out)
        self.assertEqual(self.lockfile.read_text(), before, "--frozen must never rewrite the lock")


if __name__ == "__main__":
    unittest.main()
