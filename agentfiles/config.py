"""Load agentfiles.yaml, sources.yaml and profiles, and resolve profile inheritance."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .util import NAME_RE, AgentfilesError, read_yaml

KNOWN_TARGETS = ("claude-code", "codex", "cursor", "opencode", "pi")
ALLOWABLE = ("hooks", "mcp", "agents", "commands", "bin")
DEFAULT_SETTINGS = {
    "targets": list(KNOWN_TARGETS),
    "default_profiles": ["base"],
}


@dataclass(frozen=True)
class Source:
    name: str
    git: str | None = None
    ref: str = "main"
    path: Path | None = None   # local directory source (development); never locked
    note: str = ""
    watch: tuple[str, ...] = ()  # paths `update` reviews when no profile uses this source

    @property
    def is_local(self) -> bool:
        return self.path is not None


@dataclass
class Item:
    kind: str                      # "skill" | "plugin"
    ref: str                       # "source:path" or "source:@entry"
    source: str
    path: str | None = None        # path inside the source repo
    entry: str | None = None       # marketplace entry name (plugins only)
    allow: tuple[str, ...] = ()
    explode: bool = True           # also share a plugin's skills via ~/.agents/skills
    native: bool = True            # install natively in Claude Code when possible
    origin: str = ""               # profile that declared it
    requires: dict = field(default_factory=dict)  # {commands, env, note}: manual setup, checked on sync

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.ref}"


@dataclass
class Profile:
    name: str
    description: str = ""
    extends: list[str] = field(default_factory=list)
    skills: list[Item] = field(default_factory=list)
    plugins: list[Item] = field(default_factory=list)
    mcp: dict = field(default_factory=dict)
    exclude: dict = field(default_factory=dict)
    targets: list[str] | None = None
    mode: str | None = None              # skill the always-on instructions point at ("" clears)
    instructions: list[str] = field(default_factory=list)  # extra always-on text, in order
    roles: dict = field(default_factory=dict)  # role -> {tool: model or [models]}
    file: Path | None = None


@dataclass
class Resolved:
    """The flattened result of one or more profiles."""
    profiles: list[str]
    skills: list[Item]
    plugins: list[Item]
    mcp: dict
    targets: list[str]
    mode: str | None = None
    instructions: list[str] = field(default_factory=list)
    roles: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- parsing

def parse_ref(ref: str, kind: str) -> tuple[str, str | None, str | None]:
    if ":" not in ref:
        raise AgentfilesError(f"{kind} ref {ref!r} must look like 'source:path' or 'source:@entry'")
    source, rest = ref.split(":", 1)
    rest = rest.strip().strip("/") or "."
    if rest.startswith("@"):
        if kind != "plugin":
            raise AgentfilesError(f"{ref!r}: '@entry' refs are only valid for plugins")
        return source, None, rest[1:]
    if ".." in Path(rest).parts:
        raise AgentfilesError(f"{ref!r}: '..' is not allowed in item paths")
    return source, rest, None


def parse_item(raw, kind: str, origin: str) -> Item:
    if isinstance(raw, str):
        raw = {"ref": raw}
    if not isinstance(raw, dict) or "ref" not in raw:
        raise AgentfilesError(f"profile {origin}: each {kind} must be a string or a mapping with 'ref'")
    unknown = set(raw) - {"ref", "allow", "explode", "native", "note", "requires"}
    if unknown:
        raise AgentfilesError(f"profile {origin}: unknown keys {sorted(unknown)} on {raw['ref']}")
    source, path, entry = parse_ref(str(raw["ref"]), kind)
    allow = tuple(raw.get("allow") or ())
    bad = set(allow) - set(ALLOWABLE)
    if bad:
        raise AgentfilesError(f"profile {origin}: allow {sorted(bad)} not in {list(ALLOWABLE)}")
    return Item(kind=kind, ref=f"{source}:{('@' + entry) if entry else path}", source=source,
                path=path, entry=entry, allow=allow, explode=bool(raw.get("explode", True)),
                native=bool(raw.get("native", True)), origin=origin,
                requires=parse_requires(raw.get("requires"), f"profile {origin}: {raw['ref']}"))


def parse_requires(raw, where: str) -> dict:
    """`requires:` lists what an item needs that agentfiles cannot install: commands on PATH,
    environment variables, and a free-text note on how to set them up."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise AgentfilesError(f"{where}: requires must be a mapping with commands, env and/or note")
    unknown = set(raw) - {"commands", "env", "note"}
    if unknown:
        raise AgentfilesError(f"{where}: unknown keys {sorted(unknown)} in requires")
    out = {k: [str(x) for x in raw.get(k) or []] for k in ("commands", "env")}
    out["note"] = " ".join(str(raw.get("note") or "").split())
    return out


ROLE_NAMES = ("code", "judgment", "explorer", "reviewers")


def parse_roles(raw, where: str) -> dict:
    """`roles:` maps a role to the model each tool should use for it.

    roles:
      judgment:  {claude-code: opus, cursor: claude-opus-5-5-xhigh}
      reviewers: {claude-code: [opus, sonnet]}

    `inherit` (or leaving a tool out) means: use the current model.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise AgentfilesError(f"{where}: roles must map role names to {{tool: model}}")
    out: dict = {}
    for role, per_tool in raw.items():
        if role not in ROLE_NAMES:
            raise AgentfilesError(f"{where}: unknown role {role!r}; known: {', '.join(ROLE_NAMES)}")
        if not isinstance(per_tool, dict):
            raise AgentfilesError(f"{where}: roles.{role} must map tools to a model or a list of models")
        for tool, model in per_tool.items():
            if tool not in KNOWN_TARGETS:
                raise AgentfilesError(f"{where}: roles.{role}: unknown tool {tool!r}; known: {', '.join(KNOWN_TARGETS)}")
            if isinstance(model, list):
                if not model or not all(isinstance(m, str) and m.strip() for m in model):
                    raise AgentfilesError(f"{where}: roles.{role}.{tool}: list entries must be model names")
            elif not (isinstance(model, str) and model.strip()):
                raise AgentfilesError(f"{where}: roles.{role}.{tool}: must be a model name, a list, or inherit")
        out[role] = dict(per_tool)
    return out


def merge_roles(base: dict, over: dict) -> dict:
    out = {role: dict(tools) for role, tools in base.items()}
    for role, tools in over.items():
        out.setdefault(role, {}).update(tools)
    return out


def parse_profile(name: str, data: dict, file: Path | None = None) -> Profile:
    unknown = set(data) - {"name", "description", "extends", "skills", "plugins", "mcp",
                           "exclude", "targets", "mode", "instructions", "roles"}
    if unknown:
        raise AgentfilesError(f"profile {name}: unknown keys {sorted(unknown)}")
    targets = data.get("targets")
    if targets is not None:
        bad = set(targets) - set(KNOWN_TARGETS)
        if bad:
            raise AgentfilesError(f"profile {name}: unknown targets {sorted(bad)}; known: {KNOWN_TARGETS}")
    return Profile(
        name=name,
        description=data.get("description", ""),
        extends=list(data.get("extends") or []),
        skills=[parse_item(s, "skill", name) for s in data.get("skills") or []],
        plugins=[parse_item(p, "plugin", name) for p in data.get("plugins") or []],
        mcp=dict(data.get("mcp") or {}),
        exclude=dict(data.get("exclude") or {}),
        targets=list(targets) if targets is not None else None,
        mode=_parse_mode(data, name),
        instructions=_parse_instructions(data.get("instructions"), name),
        roles=parse_roles(data.get("roles"), f"profile {name}"),
        file=file,
    )


def _parse_mode(data: dict, name: str) -> str | None:
    if "mode" not in data:
        return None
    mode = data["mode"]
    if mode in (None, "", "none"):
        return ""          # explicitly clears a mode set by an extended profile
    if not isinstance(mode, str) or not NAME_RE.match(mode):
        raise AgentfilesError(f"profile {name}: mode must be a skill name like beau-mode")
    return mode


def _parse_instructions(raw, name: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise AgentfilesError(f"profile {name}: instructions must be a string or a list of strings")
    return [x.strip() for x in raw if x.strip()]


# --------------------------------------------------------------------------- repo config

class Config:
    def __init__(self, root: Path):
        self.root = root
        if not (root / "sources.yaml").exists():
            raise AgentfilesError(
                f"{root} has no sources.yaml. Set AGENTFILES_HOME to your agentfiles repo.")
        self.settings = dict(DEFAULT_SETTINGS)
        for fname in ("agentfiles.yaml", "local.yaml"):   # local.yaml: per-machine, gitignored
            if (root / fname).exists():
                self.settings.update(read_yaml(root / fname))
        self.sources = self._load_sources()
        self.profiles = self._load_profiles()

    def _load_sources(self) -> dict[str, Source]:
        data = read_yaml(self.root / "sources.yaml").get("sources") or {}
        overrides = (self.settings.get("source_overrides") or {})
        out = {}
        for name, cfg in data.items():
            cfg = {**cfg, **(overrides.get(name) or {})}
            if "path" in cfg:
                p = Path(os.path.expanduser(cfg["path"]))
                if not p.is_absolute():
                    p = (self.root / p).resolve()
                out[name] = Source(name=name, path=p, note=cfg.get("note", ""))
            elif "git" in cfg:
                watch = cfg.get("watch") or []
                if not isinstance(watch, list) or not all(isinstance(w, str) for w in watch):
                    raise AgentfilesError(f"source {name}: watch must be a list of paths")
                out[name] = Source(name=name, git=cfg["git"], ref=str(cfg.get("ref", "main")),
                                   note=cfg.get("note", ""), watch=tuple(w.strip("/") for w in watch))
            else:
                raise AgentfilesError(f"source {name}: needs 'git' or 'path'")
        return out

    def _load_profiles(self) -> dict[str, Profile]:
        out: dict[str, Profile] = {}
        pdir = self.root / "profiles"
        for f in sorted(pdir.rglob("*.yaml")) if pdir.exists() else []:
            name = f.stem
            if name in out:
                raise AgentfilesError(f"duplicate profile name {name!r}: {out[name].file} and {f}")
            out[name] = parse_profile(name, read_yaml(f), f)
        return out

    # ----------------------------------------------------------------------- resolution

    def resolve(self, names: list[str], extra: Profile | None = None,
                targets_override: list[str] | None = None) -> Resolved:
        order: list[Profile] = []
        seen: set[str] = set()

        def visit(name: str, stack: tuple[str, ...]):
            if name in stack:
                raise AgentfilesError(f"profile cycle: {' -> '.join(stack + (name,))}")
            if name in seen:
                return
            prof = self.profiles.get(name)
            if prof is None:
                raise AgentfilesError(
                    f"unknown profile {name!r}. Available: {', '.join(sorted(self.profiles)) or '(none)'}")
            for parent in prof.extends:
                visit(parent, stack + (name,))
            seen.add(name)
            order.append(prof)

        for n in names:
            visit(n, ())
        if extra is not None:
            for parent in extra.extends:
                visit(parent, ())
            order.append(extra)

        skills: dict[str, Item] = {}
        plugins: dict[str, Item] = {}
        mcp: dict = {}
        mode: str | None = None
        instructions: list[str] = []
        roles: dict = {}
        targets = list(self.settings.get("targets") or KNOWN_TARGETS)
        for prof in order:
            if prof.mode is not None:
                mode = prof.mode or None
            for text in prof.instructions:
                if text not in instructions:
                    instructions.append(text)
            roles = merge_roles(roles, prof.roles)
            for kind, bucket in (("skills", skills), ("plugins", plugins)):
                for ex in prof.exclude.get(kind) or []:
                    bucket.pop(f"{kind[:-1]}:{ex}", None)
            for name in prof.exclude.get("mcp") or []:
                mcp.pop(name, None)
            for it in prof.skills:
                skills[it.key] = it
            for it in prof.plugins:
                plugins[it.key] = it
            mcp.update(prof.mcp)
            if prof.targets is not None:
                targets = prof.targets
        if targets_override:
            targets = targets_override

        for it in list(skills.values()) + list(plugins.values()):
            if it.source not in self.sources:
                raise AgentfilesError(
                    f"{it.ref} (profile {it.origin}): unknown source {it.source!r}; add it to sources.yaml")
        # Per-machine role overrides (local.yaml / agentfiles.yaml) win over profiles,
        # because which models you can use depends on the machine's subscriptions.
        roles = merge_roles(roles, parse_roles(self.settings.get("roles"), "settings"))
        return Resolved(profiles=[p.name for p in order], skills=list(skills.values()),
                        plugins=list(plugins.values()), mcp=mcp, targets=targets,
                        mode=mode, instructions=instructions, roles=roles)
