"""What Claude Code loaded, against what the last `agentfiles sync` installed (ROADMAP R16).

Claude Code reports its plugins and skills in the `init` event of `claude -p --output-format
stream-json --verbose`, before any model call. It names a plugin skill `<plugin>:<folder>`, and it
lists a skill as a slash command but not as a skill when it finds no usable `description`.
agentfiles installs such a skill without complaint, so only this check sees it.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .util import AgentfilesError, parse_frontmatter, short

INIT_TIMEOUT_S = 60


@dataclass(frozen=True)
class Expected:
    marketplace: str
    plugins: dict[str, frozenset[str]]
    hidden: frozenset[str] = frozenset()
    own_layout: frozenset[str] = frozenset()


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def expected_from_state(claude_state: dict) -> Expected | None:
    root = claude_state.get("marketplace")
    plugin_ids = claude_state.get("plugins") or []
    if not root or not plugin_ids:
        return None
    root = Path(root)
    manifest_path = root / ".claude-plugin" / "marketplace.json"
    if not manifest_path.is_file():
        raise AgentfilesError(f"the last sync's Claude marketplace {short(manifest_path)} is gone; "
                              f"run `agentfiles sync`")
    manifest = json.loads(manifest_path.read_text())
    plugins: dict[str, frozenset[str]] = {}
    hidden: set[str] = set()
    own_layout: set[str] = set()
    for pid in plugin_ids:
        name = pid.split("@", 1)[0]
        plugin_json = root / "plugins" / name / ".claude-plugin" / "plugin.json"
        if plugin_json.is_file() and "skills" in json.loads(plugin_json.read_text()):
            own_layout.add(name)
        skills_dir = root / "plugins" / name / "skills"
        folders = sorted(p.parent for p in skills_dir.glob("*/SKILL.md")) if skills_dir.is_dir() else []
        plugins[name] = frozenset(f.name for f in folders)
        hidden |= {f"{name}:{f.name}" for f in folders
                   if parse_frontmatter(f / "SKILL.md").get("user-invocable") is False}
    return Expected(manifest["name"], plugins, frozenset(hidden), frozenset(own_layout))


def compare(expected: Expected, init: dict) -> Report:
    r = Report()
    by_name: dict[str, list[str]] = {}
    for p in init.get("plugins") or []:
        by_name.setdefault(p.get("name", ""), []).append(p.get("source", ""))
    ours = {n for n, sources in by_name.items() if f"{n}@{expected.marketplace}" in sources}
    skills = set(init.get("skills") or [])
    commands = set(init.get("slash_commands") or [])

    for name in sorted(expected.plugins):
        if name in ours:
            continue
        others = by_name.get(name)
        if others:
            r.problems.append(f"plugin {name}: Claude Code loaded it from {', '.join(sorted(others))}, "
                              f"not {expected.marketplace}; uninstall the other copy")
        else:
            r.problems.append(f"plugin {name}@{expected.marketplace} is installed but Claude Code did not load it")

    for name in sorted(set(expected.plugins) & ours):
        if name in expected.own_layout:
            r.notes.append(f"plugin {name} sets its own skills paths in plugin.json; its skills are not checked")
            continue
        for folder in sorted(expected.plugins[name]):
            sid = f"{name}:{folder}"
            if sid in skills:
                continue
            if sid in expected.hidden:
                r.notes.append(f"skill {sid} sets user-invocable: false, so Claude Code does not list it")
            elif sid in commands:
                r.problems.append(f"skill {sid} loaded only as a slash command: Claude Code found no usable "
                                  f"description in its SKILL.md header, so it does not list it as a skill")
            else:
                r.problems.append(f"skill {sid} is installed but Claude Code did not load it")
        for sid in sorted(s for s in skills if s.split(":", 1)[0] == name):
            if sid.split(":", 1)[1] not in expected.plugins[name]:
                r.problems.append(f"skill {sid} is loaded but the last sync did not install it; "
                                  f"run `agentfiles sync`")
    return r


def claude_init(timeout: float = INIT_TIMEOUT_S) -> dict | None:
    """Claude Code's init event, read from an empty folder so only user-scope plugins load.

    The process is killed once the event arrives, before it sends anything to the model.
    """
    cmd = ["claude", "-p", "agentfiles doctor", "--output-format", "stream-json", "--verbose",
           "--no-session-persistence"]
    with tempfile.TemporaryDirectory(prefix="agentfiles-doctor-") as cwd:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, text=True)
        timer = _kill_after(proc, timeout)
        try:
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "system" and event.get("subtype") == "init":
                    return event
            return None
        finally:
            timer.cancel()
            _stop(proc)


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _kill_after(proc: subprocess.Popen, seconds: float) -> threading.Timer:
    timer = threading.Timer(seconds, proc.kill)
    timer.daemon = True
    timer.start()
    return timer
