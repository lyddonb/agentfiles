"""Git cache, immutable source trees, and the lockfile."""
from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .config import Config, Source
from .util import AgentfilesError, cache_dir, read_json, run, step, write_json

LOCK_NAME = "agentfiles.lock"


class Lock:
    def __init__(self, path: Path):
        self.path = path
        data = read_json(path, default=None) or {}
        self.sources: dict = data.get("sources", {})
        self.items: dict = data.get("items", {})
        self.dirty = False

    def set_source(self, src: Source, commit: str) -> None:
        entry = {"git": src.git, "ref": src.ref, "commit": commit,
                 "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        old = self.sources.get(src.name, {})
        if {k: old.get(k) for k in ("git", "ref", "commit")} != {k: entry[k] for k in ("git", "ref", "commit")}:
            self.sources[src.name] = entry
            self.dirty = True

    def set_item(self, key: str, commit: str, digest: str) -> None:
        new = {"commit": commit, "hash": digest}
        if self.items.get(key) != new:
            self.items[key] = new
            self.dirty = True

    def stale(self, keep_items: set[str], keep_sources: set[str]) -> list[str]:
        """Lock entries that nothing in the profiles uses any more."""
        return ([f"source {n}" for n in sorted(self.sources) if n not in keep_sources]
                + [k for k in sorted(self.items) if k not in keep_items])

    def prune(self, keep_items: set[str], keep_sources: set[str]) -> None:
        for name in [n for n in self.sources if n not in keep_sources]:
            del self.sources[name]
            self.dirty = True
        for key in [k for k in self.items if k not in keep_items]:
            del self.items[key]
            self.dirty = True

    def save(self) -> None:
        if self.dirty:
            write_json(self.path, {"version": 1, "sources": dict(sorted(self.sources.items())),
                                   "items": dict(sorted(self.items.items()))})
            self.dirty = False


class Store:
    def __init__(self, config: Config, *, offline: bool = False):
        self.config = config
        self.offline = offline
        self.lock = Lock(config.root / LOCK_NAME)
        self.base = cache_dir()
        self._fetched: set[str] = set()

    # ----------------------------------------------------------------------- git

    def _mirror(self, src: Source) -> Path:
        m = self.base / "git" / f"{src.name}.git"
        if not m.exists():
            if self.offline:
                raise AgentfilesError(f"source {src.name} is not cached and --offline was given")
            step(f"cloning {src.name} ({src.git})")
            m.parent.mkdir(parents=True, exist_ok=True)
            run(["git", "clone", "--quiet", "--bare", src.git, str(m)])
            self._fetched.add(src.name)
        return m

    def fetch(self, src: Source) -> None:
        if src.name in self._fetched or self.offline:
            return
        m = self._mirror(src)
        if src.name not in self._fetched:
            run(["git", "-C", str(m), "fetch", "--quiet", "--prune", "--tags", "origin",
                 "+refs/heads/*:refs/heads/*"])
            self._fetched.add(src.name)

    def resolve_ref(self, src: Source, ref: str) -> str:
        m = self._mirror(src)
        for candidate in (ref, f"refs/tags/{ref}", f"refs/heads/{ref}"):
            p = run(["git", "-C", str(m), "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
                    check=False)
            if p.returncode == 0:
                return p.stdout.strip()
        if not self.offline:  # maybe a commit sha that is not on a branch tip
            run(["git", "-C", str(m), "fetch", "--quiet", "origin", ref], check=False)
            p = run(["git", "-C", str(m), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                    check=False)
            if p.returncode == 0:
                return p.stdout.strip()
        raise AgentfilesError(f"source {src.name}: cannot resolve ref {ref!r}")

    # ----------------------------------------------------------------------- trees

    def locked_commit(self, name: str, *, frozen: bool = False) -> str:
        src = self.config.sources[name]
        if src.is_local:
            return "local"
        locked = self.lock.sources.get(name)
        if locked and locked.get("git") == src.git and locked.get("ref") == src.ref:
            return locked["commit"]
        if frozen:
            raise AgentfilesError(
                f"source {name} is not locked (or its git/ref changed) and --frozen was given; "
                "run `agentfiles update` or `agentfiles sync` without --frozen")
        self.fetch(src)
        commit = self.resolve_ref(src, src.ref)
        step(f"locking {name} at {commit[:12]} ({src.ref})")
        self.lock.set_source(src, commit)
        return commit

    def tree(self, name: str, *, frozen: bool = False) -> Path:
        src = self.config.sources[name]
        if src.is_local:
            if not src.path.is_dir():
                raise AgentfilesError(f"source {name}: local path {src.path} does not exist")
            return src.path
        return self.tree_at(name, self.locked_commit(name, frozen=frozen))

    def tree_at(self, name: str, commit: str) -> Path:
        """The source's files at `commit`, extracted once into the cache and read-only."""
        src = self.config.sources[name]
        dest = self.base / "trees" / name / commit
        if (dest / ".agentfiles-complete").exists():
            return dest
        m = self._mirror(src)
        have = run(["git", "-C", str(m), "cat-file", "-e", f"{commit}^{{commit}}"], check=False)
        if have.returncode != 0:
            self.fetch(src)
            run(["git", "-C", str(m), "fetch", "--quiet", "origin", commit], check=False)
        proc = subprocess.run(["git", "-C", str(m), "archive", "--format=tar", commit],
                              capture_output=True)
        if proc.returncode != 0:
            raise AgentfilesError(f"source {name}: git archive {commit[:12]} failed: "
                                  f"{proc.stderr.decode(errors='replace').strip()}")
        data = proc.stdout
        tmp = Path(tempfile.mkdtemp(prefix=f".{commit[:12]}-", dir=self._ensure(dest.parent)))
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            try:
                tf.extractall(tmp, filter="data")
            except TypeError:  # Python without extraction filters
                tf.extractall(tmp)
        (tmp / ".agentfiles-complete").write_text(commit + "\n")
        # Files read-only: a command runs straight from this tree, so an edit takes a deliberate
        # chmod (and the next sync's hash check still catches it). Folders stay writable so the
        # cache can be deleted.
        for f in tmp.rglob("*"):
            if f.is_file() and not f.is_symlink():
                f.chmod(f.stat().st_mode & ~0o222)
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
        return dest

    @staticmethod
    def _ensure(p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ----------------------------------------------------------------------- update

    def check_update(self, name: str) -> tuple[str | None, str]:
        """Return (old_commit, new_commit) for the source's configured ref."""
        src = self.config.sources[name]
        self.fetch(src)
        new = self.resolve_ref(src, src.ref)
        old = (self.lock.sources.get(name) or {}).get("commit")
        return old, new

    def changes(self, name: str, old: str, new: str, paths: list[str]) -> tuple[str, str]:
        m = self._mirror(self.config.sources[name])
        scope = ["--"] + paths if paths and "." not in paths else []
        log = run(["git", "-C", str(m), "log", "--oneline", "--no-decorate", f"{old}..{new}"] + scope,
                  check=False).stdout.strip()
        stat = run(["git", "-C", str(m), "diff", "--stat", old, new] + scope, check=False).stdout.strip()
        return log, stat

    def changed_files(self, name: str, old: str, new: str, paths: list[str]) -> list[str]:
        m = self._mirror(self.config.sources[name])
        scope = ["--"] + paths if paths and "." not in paths else []
        out = run(["git", "-C", str(m), "diff", "--name-only", "--no-renames", old, new] + scope).stdout
        return [l for l in out.splitlines() if l]

    def commits_touching(self, name: str, old: str, new: str, paths: list[str]) -> list[str]:
        """The commits in old..new that touched `paths`, oldest first."""
        m = self._mirror(self.config.sources[name])
        out = run(["git", "-C", str(m), "log", "--reverse", "--format=%H", f"{old}..{new}", "--", *paths]).stdout
        return out.split()

    def files_at(self, name: str, commit: str) -> frozenset[str]:
        """Every file path in the source at `commit`."""
        m = self._mirror(self.config.sources[name])
        return frozenset(l for l in run(["git", "-C", str(m), "ls-tree", "-r", "--name-only", commit]).stdout.splitlines() if l)

    def extract(self, name: str, commit: str, paths: list[str], dest: Path) -> Path:
        """Write `paths` of the source at `commit` under `dest`, for a read that the cache needn't keep.
        A path the commit doesn't have is left out."""
        m = self._mirror(self.config.sources[name])
        dest.mkdir(parents=True, exist_ok=True)
        present = run(["git", "-C", str(m), "ls-tree", "--name-only", commit, "--", *paths]).stdout.split("\n")
        present = [p for p in present if p]
        if not present:
            return dest
        proc = subprocess.run(["git", "-C", str(m), "archive", "--format=tar", commit, "--", *present],
                              capture_output=True)
        if proc.returncode != 0:
            raise AgentfilesError(f"source {name}: git archive {commit[:12]} failed: "
                                  f"{proc.stderr.decode(errors='replace').strip()}")
        with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tf:
            try:
                tf.extractall(dest, filter="data")
            except TypeError:
                tf.extractall(dest)
        return dest

    def diff(self, name: str, old: str, new: str, paths: list[str]) -> str:
        m = self._mirror(self.config.sources[name])
        scope = ["--"] + paths if paths and "." not in paths else []
        return run(["git", "-C", str(m), "diff", old, new] + scope, check=False).stdout
