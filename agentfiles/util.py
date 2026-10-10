"""Small shared helpers: paths, output, YAML/JSON IO, hashing."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class AgentfilesError(Exception):
    """A user-facing error: printed without a traceback."""


# --------------------------------------------------------------------------- locations

def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / "agentfiles"


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "agentfiles"


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "agentfiles"


def repo_root() -> Path:
    """The agentfiles repo holding sources.yaml and profiles/."""
    env = os.environ.get("AGENTFILES_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- output

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def short(path) -> str:
    """Display a path with $HOME shortened to ~."""
    s, home = str(path), str(Path.home())
    return "~" + s[len(home):] if s == home or s.startswith(home + os.sep) else s


def info(msg: str) -> None:
    print(msg)


def step(msg: str) -> None:
    print(_c("1;34", "==> ") + _c("1", msg))


def ok(msg: str) -> None:
    print("  " + _c("32", "+") + " " + msg)


def removed(msg: str) -> None:
    print("  " + _c("31", "-") + " " + msg)


def same(msg: str) -> None:
    print("  " + _c("2", "= " + msg))


def warn(msg: str) -> None:
    print(_c("33", "warning: ") + msg, file=sys.stderr)


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        warn(f"{question} -> no (not a terminal; pass --yes to accept)")
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


# --------------------------------------------------------------------------- IO

def read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise AgentfilesError(f"{path}: invalid YAML: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise AgentfilesError(f"{path}: expected a mapping at the top level")
    return data


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def parse_frontmatter(skill_md: Path) -> dict:
    text = skill_md.read_text(errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        fm = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return fm if isinstance(fm, dict) else {}


def tree_hash(path: Path) -> str:
    """Deterministic sha256 over a directory's relative paths and contents."""
    h = hashlib.sha256()
    if path.is_file():
        h.update(path.read_bytes())
        return "sha256:" + h.hexdigest()
    for p in sorted(path.rglob("*")):
        rel = p.relative_to(path).as_posix()
        if ".git" in p.relative_to(path).parts:
            continue
        if p.is_symlink():
            h.update(f"L {rel} -> {os.readlink(p)}\n".encode())
        elif p.is_file():
            h.update(f"F {rel}\n".encode())
            h.update(p.read_bytes())
    return "sha256:" + h.hexdigest()


# --------------------------------------------------------------------------- subprocess

def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True,
        capture: bool = True) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture)
    except FileNotFoundError as e:
        raise AgentfilesError(f"command not found: {cmd[0]}") from e
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise AgentfilesError(f"command failed ({proc.returncode}): {shlex.join(cmd)}\n{detail}")
    return proc
