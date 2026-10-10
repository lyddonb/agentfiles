"""Turn profile items (refs) into concrete skill directories and plugin descriptions."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import Item, Resolved
from .store import Store
from .util import NAME_RE, AgentfilesError, data_dir, parse_frontmatter, short, tree_hash, warn

MARKETPLACE_FILES = (
    ".claude-plugin/marketplace.json",
    ".agents/plugins/marketplace.json",
    ".cursor-plugin/marketplace.json",
)


@dataclass
class Skill:
    name: str
    path: Path
    item: Item
    via_plugin: str | None = None


@dataclass
class ClaudeNative:
    """How to expose a plugin to Claude Code through the generated marketplace."""
    root: Path
    entry: dict                       # upstream marketplace entry fields to carry over
    skills: list[Path] | None = None  # explicit skill list: synthesize a plugin with only these


@dataclass
class Plugin:
    name: str
    root: Path
    item: Item
    skills: list[Skill] = field(default_factory=list)
    components: set[str] = field(default_factory=set)
    claude: "ClaudeNative | None" = None
    # MCP servers the plugin declares, in neutral (Agent Plugins) shape with paths made absolute
    mcp: dict = field(default_factory=dict)

    @property
    def blocked(self) -> set[str]:
        """Components that need an explicit `allow:` before native installation."""
        return {c for c in self.components if c in ("hooks", "mcp", "bin")} - set(self.item.allow)


@dataclass
class Plan:
    resolved: Resolved
    skills: list[Skill]          # standalone skills from `skills:`
    plugins: list[Plugin]
    digests: dict[str, tuple[str, str]]   # item key -> (commit, hash)


# --------------------------------------------------------------------------- skills

def skill_name(path: Path) -> str:
    fm = parse_frontmatter(path / "SKILL.md")
    name = fm.get("name")
    if isinstance(name, str) and NAME_RE.match(name) and len(name) <= 64:
        if name != path.name:
            warn(f"{short(path)}: frontmatter name {name!r} differs from folder {path.name!r}; installing as {name!r}")
        return name
    if not NAME_RE.match(path.name):
        warn(f"{short(path)}: no valid frontmatter name; using folder name {path.name!r}")
    return path.name


def collect_skill_dirs(base: Path) -> list[Path]:
    """A ref may point at one skill or at a folder of skills."""
    if (base / "SKILL.md").is_file():
        return [base]
    found = sorted(p.parent for p in base.glob("*/SKILL.md"))
    if not found and (base / "skills").is_dir():
        found = sorted(p.parent for p in (base / "skills").glob("*/SKILL.md"))
    return found


# --------------------------------------------------------------------------- plugins

def _load_marketplaces(tree: Path) -> list[tuple[str, str, dict, Path]]:
    """Return (file, marketplace name, entry, marketplace root) for every entry found."""
    out = []
    for rel in MARKETPLACE_FILES:
        f = tree / rel
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            warn(f"{f}: invalid JSON; ignoring")
            continue
        for entry in data.get("plugins") or []:
            if isinstance(entry, dict) and entry.get("name"):
                out.append((rel, data.get("name", ""), entry, tree))
    return out


def _entry_root(tree: Path, entry: dict) -> Path | None:
    src = entry.get("source")
    if isinstance(src, dict):
        if src.get("source") == "local" and src.get("path"):
            src = src["path"]
        else:
            return None          # remote git/url sources are not resolvable from this tree
    if not isinstance(src, str):
        return None
    root = (tree / src).resolve()
    if tree.resolve() not in (root, *root.parents):
        return None
    return root


def _manifest(root: Path) -> dict:
    for rel in (".claude-plugin/plugin.json", "plugin.json", ".codex-plugin/plugin.json",
                ".cursor-plugin/plugin.json"):
        f = root / rel
        if f.is_file():
            try:
                return json.loads(f.read_text())
            except json.JSONDecodeError:
                warn(f"{f}: invalid JSON")
    return {}


def _components(root: Path, manifest: dict) -> set[str]:
    comps = set()
    if (root / "hooks" / "hooks.json").exists() or (root / "hooks.json").exists() or manifest.get("hooks"):
        comps.add("hooks")
    if (root / ".mcp.json").exists() or (root / "mcp.json").exists() or manifest.get("mcpServers"):
        comps.add("mcp")
    for d in ("agents", "commands", "bin"):
        if (root / d).is_dir():
            comps.add(d)
    return comps


def resolve_plugin(item: Item, tree: Path) -> Plugin:
    entries = _load_marketplaces(tree)
    entry = None
    if item.entry:
        matches = [e for e in entries if e[2]["name"] == item.entry]
        if not matches:
            names = sorted({e[2]["name"] for e in entries})
            raise AgentfilesError(f"{item.ref}: no marketplace entry {item.entry!r}. "
                                  f"Entries: {', '.join(names) or '(no marketplace files)'}")
        entry = matches[0]
        root = _entry_root(tree, entry[2])
        if root is None:
            raise AgentfilesError(f"{item.ref}: entry source is remote or invalid; reference its repo directly")
    else:
        root = (tree / item.path).resolve()
        if not root.is_dir():
            raise AgentfilesError(f"{item.ref}: {item.path} is not a directory in the source")

    manifest = _manifest(root)
    name = (entry[2]["name"] if entry else None) or manifest.get("name") or root.name
    plugin = Plugin(name=name, root=root, item=item, components=_components(root, manifest))

    # Skills: an explicit entry list wins, then manifest paths, then the default skills/ folder.
    skill_dirs: list[Path] = []
    explicit = entry[2].get("skills") if entry else None
    if explicit:
        skill_dirs = [(tree / s).resolve() for s in explicit]
    else:
        extra = manifest.get("skills")
        extra = [extra] if isinstance(extra, str) else (extra or [])
        for rel in ["skills", *extra]:
            d = (root / rel).resolve()
            if d.is_dir():
                skill_dirs += [p for p in collect_skill_dirs(d) if p not in skill_dirs]
        if not skill_dirs and (root / "SKILL.md").is_file():
            skill_dirs = [root]
    plugin.skills = [Skill(name=skill_name(d), path=d, item=item, via_plugin=name) for d in skill_dirs]
    plugin.mcp = plugin_mcp(root, name)

    # Can Claude Code install it natively? Yes if the source repo lists it in a Claude
    # marketplace, or it has its own .claude-plugin/plugin.json. agentfiles re-exposes it
    # through its own generated marketplace (see targets.py), so upstream marketplace
    # names never matter and the install stays pinned to the locked tree.
    claude_entry = None
    for rel, _mk_name, ent, _mk_root in entries:
        if rel != ".claude-plugin/marketplace.json":
            continue
        if entry is not None and ent["name"] != entry[2]["name"]:
            continue
        if _entry_root(tree, ent) == root and (entry is not None or not ent.get("skills")):
            claude_entry = ent
            break
    if claude_entry is not None or (root / ".claude-plugin" / "plugin.json").is_file():
        explicit_skills = bool(claude_entry and claude_entry.get("skills"))
        plugin.claude = ClaudeNative(
            root=root,
            entry={k: v for k, v in (claude_entry or {}).items() if k not in ("name", "source", "skills")},
            skills=[sk.path for sk in plugin.skills] if explicit_skills else None,
        )
    return plugin


def _subst(value, mapping: dict[str, str]):
    if isinstance(value, str):
        for k, v in mapping.items():
            value = value.replace(k, v)
        return value
    if isinstance(value, list):
        return [_subst(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: _subst(v, mapping) for k, v in value.items()}
    return value


def plugin_mcp(root: Path, name: str) -> dict:
    """Read a plugin's MCP servers (Agent Plugins mcp.json first, then Claude's .mcp.json)."""
    data_path = str(data_dir() / "plugin-data" / name)
    mapping = {"${PLUGIN_ROOT}": str(root), "${PLUGIN_DATA}": data_path,
               "${CLAUDE_PLUGIN_ROOT}": str(root), "${CLAUDE_PLUGIN_DATA}": data_path}
    for fname in ("mcp.json", ".mcp.json"):
        f = root / fname
        if not f.is_file():
            continue
        try:
            servers = (json.loads(f.read_text()) or {}).get("mcpServers") or {}
        except json.JSONDecodeError:
            warn(f"{f}: invalid JSON; ignoring its MCP servers")
            return {}
        out = {}
        for sname, cfg in servers.items():
            cfg = _subst(dict(cfg), mapping)
            t = cfg.get("type") or ("stdio" if "command" in cfg else "streamable-http")
            cfg["type"] = {"http": "streamable-http"}.get(t, t)
            if cfg["type"] == "stdio" and str(cfg.get("command", "")).startswith("./"):
                cfg["command"] = str(root / cfg["command"][2:])
            cfg.pop("cwd", None)
            out[sname] = cfg
        return out
    return {}


# --------------------------------------------------------------------------- whole plan

def build_plan(resolved: Resolved, store: Store, *, frozen: bool = False) -> Plan:
    digests: dict[str, tuple[str, str]] = {}
    skills: list[Skill] = []
    for item in resolved.skills:
        tree = store.tree(item.source, frozen=frozen)
        base = (tree / item.path).resolve()
        if not base.exists():
            raise AgentfilesError(f"{item.ref} (profile {item.origin}): {item.path} not found in source")
        dirs = collect_skill_dirs(base)
        if not dirs:
            raise AgentfilesError(f"{item.ref}: no SKILL.md at {item.path} or one level below")
        skills += [Skill(name=skill_name(d), path=d, item=item) for d in dirs]
        digests[item.key] = (store.locked_commit(item.source, frozen=frozen), tree_hash(base))

    plugins: list[Plugin] = []
    for item in resolved.plugins:
        tree = store.tree(item.source, frozen=frozen)
        plugin = resolve_plugin(item, tree)
        plugins.append(plugin)
        digests[item.key] = (store.locked_commit(item.source, frozen=frozen), tree_hash(plugin.root))
    return Plan(resolved=resolved, skills=skills, plugins=plugins, digests=digests)


def verify_and_lock(plan: Plan, store: Store, *, frozen: bool) -> None:
    """Content hashes: record new ones, and refuse silent changes to locked ones."""
    for key, (commit, digest) in plan.digests.items():
        if commit == "local":
            continue
        locked = store.lock.items.get(key)
        if locked and locked.get("commit") == commit and locked.get("hash") != digest:
            raise AgentfilesError(
                f"{key}: content hash changed for the same commit {commit[:12]} "
                f"(locked {locked.get('hash')}, got {digest}). The cache may be corrupted or "
                "tampered with; delete ~/.cache/agentfiles/trees and retry.")
        if frozen and not locked:
            raise AgentfilesError(f"{key} is not in agentfiles.lock and --frozen was given")
        store.lock.set_item(key, commit, digest)
