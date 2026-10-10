"""Turn a Plan into desired on-disk / in-tool state, diff it against the last sync, apply it.

Channels:
  shared dir   ~/.agents/skills (or <project>/.agents/skills). One copy of every skill,
               read by Codex, Cursor, OpenCode and pi. Entries are symlinks into the
               immutable source cache.
  claude-code  Claude Code does not read ~/.agents/skills, and linking skills into
               ~/.claude/skills would duplicate them in Cursor/OpenCode (which read both).
               So agentfiles generates ONE local marketplace ("agentfiles-local") holding:
                 - plugin "agentfiles": standalone profile skills (symlinks)
                 - every plugin installed natively, as a symlink to its pinned tree
               Using our own marketplace keeps installs pinned to agentfiles.lock, avoids
               marketplace-name clashes, and works for upstream marketplaces whose names
               Claude Code reserves (anthropics/*).
  MCP          Claude Code via `claude mcp add-json`; Codex, Cursor and OpenCode get
               ready-to-paste snippets (automatic merge is on the roadmap).
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .resolve import Plan, Skill
from .util import (AgentfilesError, data_dir, info, ok, read_json, removed, run, same, short,
                   state_dir, step, warn, write_json)

SHARED_DIR_TARGETS = {"codex", "cursor", "opencode", "pi"}
GEN_MARKETPLACE = "agentfiles-local"
GEN_PLUGIN = "agentfiles"


@dataclass
class Scope:
    project: Path | None = None

    @property
    def is_project(self) -> bool:
        return self.project is not None

    @property
    def shared_skills_dir(self) -> Path:
        return (self.project / ".agents" / "skills") if self.project else Path.home() / ".agents" / "skills"

    @property
    def generated_dir(self) -> Path:
        return (self.project / ".agentfiles") if self.project else data_dir()

    @property
    def state_file(self) -> Path:
        return (self.project / ".agentfiles" / "state.json") if self.project else state_dir() / "state.json"

    @property
    def marketplace(self) -> str:
        """Claude marketplace names are global, so each project gets its own."""
        if not self.project:
            return GEN_MARKETPLACE
        slug = "".join(c if c.isalnum() else "-" for c in self.project.name.lower()).strip("-")[:24] or "project"
        return f"agentfiles-{slug}-{hashlib.sha256(str(self.project).encode()).hexdigest()[:6]}"

    @property
    def claude_scope(self) -> str:
        return "local" if self.project else "user"

    @property
    def label(self) -> str:
        return f"project {self.project}" if self.project else "user (global)"


@dataclass
class Desired:
    shared_links: dict[str, str] = field(default_factory=dict)   # dest -> src
    claude_links: dict[str, str] = field(default_factory=dict)   # skill name -> src (agentfiles plugin)
    claude_native: dict[str, dict] = field(default_factory=dict) # plugin name -> {root, entry, skills, ref}
    claude_mcp: dict[str, dict] = field(default_factory=dict)
    snippet_mcp: dict[str, dict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- planning

def _add_unique(bucket: dict[str, Skill], skill: Skill, channel: str) -> None:
    prev = bucket.get(skill.name)
    if prev and prev.path != skill.path:
        raise AgentfilesError(
            f"skill name collision in {channel}: {skill.name!r} comes from both {prev.item.ref} "
            f"and {skill.item.ref}. Remove one, or use `exclude:` in a profile.")
    bucket[skill.name] = skill


def desired_state(plan: Plan, scope: Scope) -> Desired:
    d = Desired()
    targets = set(plan.resolved.targets)

    if targets & SHARED_DIR_TARGETS:
        shared: dict[str, Skill] = {}
        for s in plan.skills:
            _add_unique(shared, s, short(scope.shared_skills_dir))
        for p in plan.plugins:
            if p.item.explode:
                for s in p.skills:
                    _add_unique(shared, s, short(scope.shared_skills_dir))
        d.shared_links = {str(scope.shared_skills_dir / n): str(s.path) for n, s in sorted(shared.items())}

    if "claude-code" in targets:
        gen: dict[str, Skill] = {}
        for s in plan.skills:
            _add_unique(gen, s, "Claude Code (agentfiles plugin)")
        for p in plan.plugins:
            if p.claude is not None and p.item.native and not p.blocked:
                if p.name == GEN_PLUGIN or p.name in d.claude_native:
                    other = d.claude_native.get(p.name, {}).get("ref", "agentfiles itself")
                    raise AgentfilesError(f"two plugins named {p.name!r} for Claude Code: {p.item.ref} and {other}")
                d.claude_native[p.name] = {
                    "root": str(p.claude.root), "entry": p.claude.entry, "ref": p.item.ref,
                    "skills": [str(x) for x in p.claude.skills] if p.claude.skills is not None else None,
                }
                continue
            if p.claude is not None and p.blocked:
                d.notes.append(
                    f"{p.item.ref}: ships {', '.join(sorted(p.blocked))}, so it was NOT installed natively in "
                    f"Claude Code (only its skills were). Review it, then add "
                    f"`allow: [{', '.join(sorted(p.blocked))}]` to install it fully.")
            for s in p.skills:
                _add_unique(gen, s, "Claude Code (agentfiles plugin)")
            if not p.skills and p.claude is None:
                d.notes.append(f"{p.item.ref}: nothing to install in Claude Code (no skills, no Claude manifest)")
        d.claude_links = {n: str(s.path) for n, s in sorted(gen.items())}
        d.claude_mcp = {name: to_claude_mcp(name, cfg) for name, cfg in plan.resolved.mcp.items()}

    others = targets - {"claude-code"}
    for p in plan.plugins:
        extra = p.components - {"mcp"}
        if extra and others:
            d.notes.append(f"{p.item.ref}: its {', '.join(sorted(extra))} only work in Claude Code; "
                           f"other tools get its skills" + ("" if p.skills else " (it has none)"))
    if targets & {"codex", "cursor", "opencode"}:
        # Profile MCP servers plus servers bundled in plugins (those tools get plugin skills
        # through the shared directory, so they need the plugin's MCP servers separately).
        snippets = {}
        for p in plan.plugins:
            snippets.update(p.mcp)
        snippets.update(plan.resolved.mcp)
        d.snippet_mcp = snippets
    if scope.is_project:
        _skip_globally_installed(d)
    return d


def _skip_globally_installed(d: Desired) -> None:
    """Tools read both user-level and project-level locations, so installing the same
    item in both shows duplicates. Drop anything the last global sync already provides."""
    g = read_json(state_dir() / "state.json", default={}) or {}
    skipped = 0
    g_shared = {Path(dest).name: src for dest, src in (g.get("links") or {}).items()}
    for dest, src in list(d.shared_links.items()):
        if g_shared.get(Path(dest).name) == src:
            del d.shared_links[dest]
            skipped += 1
    gc = g.get("claude") or {}
    for name, src in list(d.claude_links.items()):
        if (gc.get("generated_links") or {}).get(name) == src:
            del d.claude_links[name]
            skipped += 1
    g_native = gc.get("native") or {}
    for name, spec in list(d.claude_native.items()):
        fp = spec["root"] if spec["skills"] is None else json.dumps(spec["skills"])
        if g_native.get(name) == fp:
            del d.claude_native[name]
            skipped += 1
    for name, cfg in list(d.claude_mcp.items()):
        if (gc.get("mcp") or {}).get(name) == _digest(cfg):
            del d.claude_mcp[name]
            skipped += 1
    if skipped:
        d.notes.append(f"{skipped} item(s) skipped here because your global sync already installs them")


def _digest(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- MCP formats

def _check_mcp(name: str, cfg: dict) -> str:
    t = cfg.get("type", "stdio")
    if t == "stdio" and not cfg.get("command"):
        raise AgentfilesError(f"mcp {name}: stdio servers need 'command'")
    if t in ("streamable-http", "sse") and not cfg.get("url"):
        raise AgentfilesError(f"mcp {name}: {t} servers need 'url'")
    if t not in ("stdio", "streamable-http", "sse"):
        raise AgentfilesError(f"mcp {name}: unknown type {t!r}")
    if "${PLUGIN_" in json.dumps(cfg):
        raise AgentfilesError(f"mcp {name}: ${{PLUGIN_ROOT}}/${{PLUGIN_DATA}} only work inside plugins")
    return t


def to_claude_mcp(name: str, cfg: dict) -> dict:
    t = _check_mcp(name, cfg)
    if t == "stdio":
        out = {"type": "stdio", "command": cfg["command"], "args": cfg.get("args", [])}
        if cfg.get("env"):
            out["env"] = cfg["env"]
        return out
    out = {"type": "http" if t == "streamable-http" else "sse", "url": cfg["url"]}
    if cfg.get("headers"):
        out["headers"] = cfg["headers"]
    return out


def _toml_value(v) -> str:
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{json.dumps(k)} = {_toml_value(x)}" for k, x in v.items()) + " }"
    return json.dumps(v)


def mcp_snippets(servers: dict) -> dict[str, str]:
    codex, opencode, cursor = [], {}, {}
    for name, cfg in sorted(servers.items()):
        t = _check_mcp(name, cfg)
        codex.append(f"[mcp_servers.{name}]")
        if t == "stdio":
            codex.append(f"command = {_toml_value(cfg['command'])}")
            if cfg.get("args"):
                codex.append(f"args = {_toml_value(cfg['args'])}")
            if cfg.get("env"):
                codex.append(f"env = {_toml_value(cfg['env'])}")
            opencode[name] = {"type": "local", "command": [cfg["command"], *cfg.get("args", [])],
                              **({"environment": cfg["env"]} if cfg.get("env") else {})}
            cursor[name] = {"command": cfg["command"], "args": cfg.get("args", []),
                            **({"env": cfg["env"]} if cfg.get("env") else {})}
        else:
            codex.append(f"url = {_toml_value(cfg['url'])}")
            if cfg.get("headers"):
                codex.append(f"http_headers = {_toml_value(cfg['headers'])}")
            opencode[name] = {"type": "remote", "url": cfg["url"],
                              **({"headers": cfg["headers"]} if cfg.get("headers") else {})}
            cursor[name] = {"url": cfg["url"], **({"headers": cfg["headers"]} if cfg.get("headers") else {})}
        codex.append("")
    return {
        "codex.toml": "# Paste into ~/.codex/config.toml (or .codex/config.toml in a trusted project)\n"
                      + "\n".join(codex),
        "opencode.json": json.dumps({"$comment": "Merge into ~/.config/opencode/opencode.json",
                                     "mcp": opencode}, indent=2) + "\n",
        "cursor.json": json.dumps({"$comment": "Merge into ~/.cursor/mcp.json (or .cursor/mcp.json)",
                                   "mcpServers": cursor}, indent=2) + "\n",
    }


# --------------------------------------------------------------------------- applying

SYNTH_KEYS = ("description", "version", "author", "keywords", "category", "homepage", "license")


class Applier:
    def __init__(self, scope: Scope, *, dry_run: bool):
        self.scope = scope
        self.dry = dry_run
        self.old = read_json(scope.state_file, default={}) or {}
        self.new = {"version": 2, "scope": scope.label, "links": {},
                    "claude": {"marketplace": None, "plugins": [], "mcp": {}, "generated_links": {},
                               "native": {}}}
        self.claude_bin = shutil.which("claude")

    # -------------------------------------------------- generic
    def _do(self, fn) -> None:
        """File operations: summarized by the +/-/= lines and skipped in a dry run."""
        if not self.dry:
            fn()

    def _claude(self, args: list[str]) -> bool:
        cmd = ["claude", *args]
        if self.dry:
            info(f"  [dry-run] {shlex.join(cmd)}")
            return True
        p = run(cmd, cwd=self.scope.project, check=False)
        if p.returncode != 0:
            warn(f"{shlex.join(cmd)} failed: {(p.stderr or p.stdout).strip()[:400]}")
            return False
        return True

    def _claude_json(self, args: list[str]):
        if not self.claude_bin:
            return []
        p = run(["claude", *args, "--json"], cwd=self.scope.project, check=False)
        try:
            return json.loads(p.stdout) if p.returncode == 0 else []
        except json.JSONDecodeError:
            return []

    # -------------------------------------------------- symlinks
    def _sync_links(self, desired: dict[str, str], old: dict[str, str], label: str) -> dict[str, str]:
        kept: dict[str, str] = {}
        for dest, src in desired.items():
            dp = Path(dest)
            if dp.is_symlink():
                cur = os.readlink(dp)
                if cur == src:
                    same(f"{label}: {dp.name}")
                    kept[dest] = src
                    continue
                if old.get(dest) == cur:
                    self._do(lambda dp=dp, src=src: (dp.unlink(), dp.symlink_to(src)))
                    ok(f"{label}: {dp.name} (updated)")
                    kept[dest] = src
                    continue
                warn(f"{short(dest)} already links to {short(cur)} (not managed by agentfiles); skipping")
                continue
            if dp.exists():
                warn(f"{short(dest)} exists and is not a symlink (not managed by agentfiles); skipping")
                continue
            self._do(lambda dp=dp, src=src: (dp.parent.mkdir(parents=True, exist_ok=True), dp.symlink_to(src)))
            ok(f"{label}: {dp.name}")
            kept[dest] = src
        for dest, src in old.items():
            if dest in desired:
                continue
            dp = Path(dest)
            if dp.is_symlink() and os.readlink(dp) == src:
                self._do(dp.unlink)
                removed(f"{label}: {dp.name}")
        return kept

    # -------------------------------------------------- generated Claude marketplace
    def _write_marketplace(self, d: Desired) -> tuple[Path, list[str], str]:
        """Write agentfiles-local. Returns (root, plugin names, content digest)."""
        root = self.scope.generated_dir / "claude-marketplace"
        pdir = root / "plugins"
        names: list[str] = []
        entries = []

        # (a) the "agentfiles" plugin with standalone skills
        gen = pdir / GEN_PLUGIN
        if d.claude_links:
            names.append(GEN_PLUGIN)
            entries.append({"name": GEN_PLUGIN, "source": f"./plugins/{GEN_PLUGIN}",
                            "description": "Skills from your agentfiles profiles"})
            version = "0.0.0-" + hashlib.sha256(json.dumps(d.claude_links, sort_keys=True).encode()).hexdigest()[:10]
            self._do(lambda: write_json(gen / ".claude-plugin" / "plugin.json", {
                "name": GEN_PLUGIN, "version": version, "author": {"name": "agentfiles"},
                "description": "Skills from your agentfiles profiles (generated)"}))
        old_links = {str(gen / "skills" / n): s
                     for n, s in ((self.old.get("claude") or {}).get("generated_links") or {}).items()}
        self._sync_links({str(gen / "skills" / n): s for n, s in d.claude_links.items()}, old_links,
                         "claude skill")
        self.new["claude"]["generated_links"] = d.claude_links

        # (b) native plugins: symlink to the pinned plugin root, or a synthesized plugin
        #     holding only the listed skills (marketplace entries with an explicit skills list)
        old_native = (self.old.get("claude") or {}).get("native") or {}
        for name in sorted(set(old_native) - set(d.claude_native)):
            self._do(lambda p=pdir / name: _remove_entry(p))
        for name, spec in sorted(d.claude_native.items()):
            target = pdir / name
            names.append(name)
            entry = {"name": name, "source": f"./plugins/{name}"}
            if spec["skills"] is None:
                entry.update(spec["entry"])
                fingerprint = spec["root"]
                if old_native.get(name) != fingerprint or not target.is_symlink():
                    self._do(lambda t=target, r=spec["root"]: (_remove_entry(t), t.parent.mkdir(parents=True, exist_ok=True),
                                                               t.symlink_to(r)))
            else:
                entry.update({k: v for k, v in spec["entry"].items() if k in SYNTH_KEYS})
                fingerprint = json.dumps(spec["skills"])
                if old_native.get(name) != fingerprint or not target.is_dir():
                    def build(t=target, spec=spec, name=name):
                        _remove_entry(t)
                        write_json(t / ".claude-plugin" / "plugin.json", {
                            "name": name, "description": spec["entry"].get("description", name),
                            "version": spec["entry"].get("version", "0.0.0"),
                            "author": spec["entry"].get("author") or {"name": "agentfiles"}})
                        for sk in spec["skills"]:
                            (t / "skills").mkdir(parents=True, exist_ok=True)
                            (t / "skills" / Path(sk).name).symlink_to(sk)
                    self._do(build)
            entries.append(entry)
            self.new["claude"]["native"][name] = fingerprint

        manifest = {"name": self.scope.marketplace, "owner": {"name": "agentfiles"},
                    "description": "Generated by agentfiles from your profiles. Do not edit; run `agentfiles sync`.",
                    "plugins": entries}
        self._do(lambda: write_json(root / ".claude-plugin" / "marketplace.json", manifest))
        digest = hashlib.sha256(json.dumps([manifest, self.new["claude"]["native"]], sort_keys=True)
                                .encode()).hexdigest()[:16]
        return root, names, digest

    # -------------------------------------------------- main entry
    def apply(self, d: Desired, targets: list[str]) -> None:
        step(f"Shared skills directory {short(self.scope.shared_skills_dir)} "
             f"({', '.join(sorted(set(targets) & SHARED_DIR_TARGETS)) or 'no targets'})")
        self.new["links"] = self._sync_links(d.shared_links, self.old.get("links") or {}, "skill")

        old_claude = self.old.get("claude") or {}
        if "claude-code" in targets and not self.claude_bin and not self.dry:
            warn("claude CLI not found; skipping Claude Code (install it, then re-run sync)")
            self.new["claude"] = old_claude
        elif "claude-code" in targets or old_claude:
            self._apply_claude(d if "claude-code" in targets else Desired(), old_claude)

        if d.snippet_mcp:
            step("MCP snippets for Codex, Cursor and OpenCode")
            out = self.scope.generated_dir / "mcp"
            for fname, content in mcp_snippets(d.snippet_mcp).items():
                self._do(lambda p=out / fname, c=content: (p.parent.mkdir(parents=True, exist_ok=True),
                                                           p.write_text(c)))
                ok(short(out / fname))
            info("  (merge these into each tool's config; see docs/TARGETS.md)")

        if d.notes:
            step("Notes")
            for n in d.notes:
                info(f"  - {n}")
        if not self.dry:
            write_json(self.scope.state_file, self.new)

    def _apply_claude(self, d: Desired, old: dict) -> None:
        step(f"Claude Code ({self.scope.claude_scope} scope)")
        installed = {p.get("id") for p in self._claude_json(["plugin", "list"])}
        markets = {m.get("name"): m.get("path") for m in self._claude_json(["plugin", "marketplace", "list"])}
        sc = ["--scope", self.scope.claude_scope]
        root, names, digest = self._write_marketplace(d)
        wanted = [f"{n}@{self.scope.marketplace}" for n in names]
        old_ids = set(old.get("plugins") or [])

        # 1. the marketplace
        if wanted:
            cur = markets.get(self.scope.marketplace)
            if cur not in (None, str(root)) and not old.get("marketplace"):
                warn(f"a Claude marketplace named {self.scope.marketplace!r} already exists at {cur} and is not "
                     "managed by agentfiles; skipping Claude Code plugins")
                wanted = []
            elif cur != str(root):
                if cur is not None:
                    self._claude(["plugin", "marketplace", "remove", self.scope.marketplace])
                    installed = {i for i in installed if not str(i).endswith("@" + self.scope.marketplace)}
                # Always declare the catalog in user settings: Claude Code refuses symlinked plugin
                # entries from marketplaces declared at local/project scope. Plugins themselves are
                # still installed at the right scope below.
                if self._claude(["plugin", "marketplace", "add", str(root), "--scope", "user"]):
                    ok(f"marketplace {self.scope.marketplace} -> {short(root)}")
            elif old.get("marketplace_digest") != digest:
                if self._claude(["plugin", "marketplace", "update", self.scope.marketplace]):
                    ok(f"marketplace {self.scope.marketplace} (refreshed)")
            else:
                same(f"marketplace {self.scope.marketplace}")
            self.new["claude"]["marketplace"] = str(root)
            self.new["claude"]["marketplace_digest"] = digest

        # 2. plugins
        for pid in wanted:
            if pid in installed:
                same(f"plugin {pid}")
            elif self._claude(["plugin", "install", pid, *sc]):
                ok(f"plugin {pid}")
            else:
                continue
            self.new["claude"]["plugins"].append(pid)
        for pid in sorted(old_ids - set(wanted)):
            if pid in installed and self._claude(["plugin", "uninstall", pid, *sc]):
                removed(f"plugin {pid}")
        if not wanted and old.get("marketplace") and self.scope.marketplace in markets:
            if self._claude(["plugin", "marketplace", "remove", self.scope.marketplace]):
                removed(f"marketplace {self.scope.marketplace}")

        # 3. MCP servers
        old_mcp = old.get("mcp") or {}
        mscope = ["-s", self.scope.claude_scope]
        for name, cfg in d.claude_mcp.items():
            digest = _digest(cfg)
            if old_mcp.get(name) == digest:
                same(f"mcp {name}")
            else:
                if name in old_mcp:
                    self._claude(["mcp", "remove", name, *mscope])
                if not self._claude(["mcp", "add-json", *mscope, name, json.dumps(cfg)]):
                    continue
                ok(f"mcp {name}")
            self.new["claude"]["mcp"][name] = digest
        for name in sorted(set(old_mcp) - set(d.claude_mcp)):
            if self._claude(["mcp", "remove", name, *mscope]):
                removed(f"mcp {name}")


def _remove_entry(p: Path) -> None:
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)
