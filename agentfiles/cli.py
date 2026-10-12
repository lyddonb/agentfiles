"""agentfiles command line."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import textwrap
from pathlib import Path

from . import __version__
from .apm import emit_apm
from .config import KNOWN_TARGETS, Config, Profile, parse_profile
from .resolve import build_plan, verify_and_lock
from .store import Store
from .targets import Applier, Desired, Scope, desired_state
from .util import AgentfilesError, confirm, info, read_json, read_yaml, repo_root, step, warn

PROJECT_FILE = ".agentfiles.yaml"


# --------------------------------------------------------------------------- helpers

def _scope(args) -> Scope:
    if getattr(args, "project", None) is None:
        return Scope()
    p = Path(args.project).expanduser().resolve()
    if not p.is_dir():
        raise AgentfilesError(f"--project {p} is not a directory")
    return Scope(project=p)


def _targets(args) -> list[str] | None:
    if not getattr(args, "targets", None):
        return None
    t = [x.strip() for x in args.targets.split(",") if x.strip()]
    bad = set(t) - set(KNOWN_TARGETS)
    if bad:
        raise AgentfilesError(f"unknown targets {sorted(bad)}; known: {', '.join(KNOWN_TARGETS)}")
    return t


def _resolve(cfg: Config, args, scope: Scope):
    extra: Profile | None = None
    names = list(args.profiles or [])
    if scope.is_project and (scope.project / PROJECT_FILE).exists():
        extra = parse_profile(f"project:{scope.project.name}", read_yaml(scope.project / PROJECT_FILE),
                              scope.project / PROJECT_FILE)
    if not names and extra is None:
        names = list(cfg.settings.get("default_profiles") or [])
        if scope.is_project:
            raise AgentfilesError(f"no profiles given and {scope.project / PROJECT_FILE} does not exist")
    return cfg.resolve(names, extra=extra, targets_override=_targets(args))


def _report_setup(items) -> None:
    """Check each item's `requires:` and say what still has to be done by hand."""
    items = [it for it in items if it.requires]
    if not items:
        return
    step("Manual setup")
    for it in items:
        req = it.requires
        missing_cmds = [c for c in req["commands"] if not shutil.which(c)]
        missing_env = [e for e in req["env"] if not os.environ.get(e)]
        if not missing_cmds and not missing_env:
            info(f"  ok  {it.ref}")
            continue
        info(f"  !!  {it.ref}")
        if missing_cmds:
            info(f"        not on PATH: {', '.join(missing_cmds)}")
        if missing_env:
            info(f"        not set in this shell: {', '.join(missing_env)}")
        if req["note"]:
            info(textwrap.fill(req["note"], width=92, initial_indent=" " * 8, subsequent_indent=" " * 8))


# --------------------------------------------------------------------------- commands

def cmd_sync(args) -> int:
    cfg = Config(repo_root())
    scope = _scope(args)
    store = Store(cfg, offline=args.offline)
    resolved = _resolve(cfg, args, scope)
    step(f"Profiles: {', '.join(resolved.profiles)}  ·  scope: {scope.label}  ·  "
         f"targets: {', '.join(resolved.targets)}")
    plan = build_plan(resolved, store, frozen=args.frozen)
    verify_and_lock(plan, store, frozen=args.frozen)
    desired = desired_state(plan, scope)
    Applier(scope, dry_run=args.dry_run).apply(desired, resolved.targets)
    if not args.dry_run:
        store.lock.save()
    _report_setup(resolved.skills + resolved.plugins)
    info("")
    info("Dry run complete; nothing changed." if args.dry_run else
         "Done. Restart running agents to pick up changes.")
    return 0


def cmd_uninstall(args) -> int:
    scope = _scope(args)
    if not read_json(scope.state_file, default=None):
        info(f"Nothing installed by agentfiles for {scope.label}.")
        return 0
    if not confirm(f"Remove everything agentfiles installed for {scope.label}?", args.yes or args.dry_run):
        return 1
    Applier(scope, dry_run=args.dry_run).apply(Desired(), ["claude-code"])
    return 0


def _paths_used(cfg: Config, source: str) -> list[str]:
    paths = set()
    for prof in cfg.profiles.values():
        for it in prof.skills + prof.plugins:
            if it.source == source:
                paths.add(it.path if it.path else ".")
    return sorted(paths)


def cmd_update(args) -> int:
    cfg = Config(repo_root())
    store = Store(cfg)
    names = args.sources or [n for n, s in cfg.sources.items() if not s.is_local]
    changed = 0
    for name in names:
        src = cfg.sources.get(name)
        if src is None:
            raise AgentfilesError(f"unknown source {name!r}")
        if src.is_local:
            info(f"{name}: local path source; nothing to update")
            continue
        old, new = store.check_update(name)
        if old == new:
            info(f"{name}: up to date at {new[:12]} ({src.ref})")
            continue
        step(f"{name}: {old[:12] if old else '(unlocked)'} -> {new[:12]} ({src.ref})")
        paths = _paths_used(cfg, name)
        if old:
            log, stat = store.changes(name, old, new, paths)
            scope_note = "" if "." in paths or not paths else f" (limited to {', '.join(paths)})"
            info(f"  commits{scope_note}:")
            info("\n".join("    " + l for l in (log or "(no commits touching these paths)").splitlines()[:40]))
            if stat:
                info("  files:")
                info("\n".join("    " + l for l in stat.splitlines()[-25:]))
            if args.diff:
                info(store.diff(name, old, new, paths))
        if confirm(f"  Accept {name} @ {new[:12]}?", args.yes):
            store.lock.set_source(src, new)
            changed += 1
    store.lock.save()
    info(f"\n{changed} source(s) updated in agentfiles.lock." +
         (" Run `agentfiles sync` to apply." if changed else ""))
    return 0


def cmd_list(args) -> int:
    cfg = Config(repo_root())
    if not args.profiles:
        info("Profiles:")
        width = max((len(n) for n in cfg.profiles), default=0)
        for name, prof in sorted(cfg.profiles.items()):
            ext = f"  (extends {', '.join(prof.extends)})" if prof.extends else ""
            info(f"  {name:<{width}}  {prof.description}{ext}")
        info("\nSources:")
        for name, src in sorted(cfg.sources.items()):
            where = str(src.path) if src.is_local else f"{src.git} @ {src.ref}"
            info(f"  {name}: {where}")
        default = ", ".join(cfg.settings.get("default_profiles") or [])
        info(f"\nDefault profiles: {default}")
        return 0
    r = cfg.resolve(args.profiles)
    info(f"Resolved: {', '.join(r.profiles)}  ·  targets: {', '.join(r.targets)}")
    info("\nSkills:")
    for it in r.skills:
        info(f"  {it.ref}   [{it.origin}]")
    info("\nPlugins:")
    for it in r.plugins:
        flags = f"  allow={','.join(it.allow)}" if it.allow else ""
        flags += "" if it.explode else "  explode=false"
        info(f"  {it.ref}   [{it.origin}]{flags}")
    if r.mcp:
        info("\nMCP servers:")
        for name, c in r.mcp.items():
            info(f"  {name}: {c.get('url') or c.get('command')}")
    return 0


def cmd_status(args) -> int:
    scope = _scope(args)
    state = read_json(scope.state_file, default=None)
    if not state:
        info(f"Nothing installed by agentfiles for {scope.label}.")
        return 0
    links = state.get("links") or {}
    info(f"Scope: {state.get('scope')}")
    info(f"Shared skills ({len(links)}): " + ", ".join(sorted(Path(d).name for d in links)))
    broken = [d for d, s in links.items() if not Path(d).exists()]
    if broken:
        warn(f"broken links: {', '.join(broken)}")
    c = state.get("claude") or {}
    gen = c.get("generated_links") or {}
    info(f"Claude Code agentfiles plugin skills ({len(gen)}): " + ", ".join(sorted(gen)))
    info(f"Claude Code plugins: {', '.join(c.get('plugins') or []) or '(none)'}")
    info(f"Claude Code MCP servers: {', '.join(c.get('mcp') or {}) or '(none)'}")
    lock = read_json(repo_root() / "agentfiles.lock", default={}) or {}
    if lock.get("sources"):
        info("\nLocked sources:")
        for n, s in sorted(lock["sources"].items()):
            info(f"  {n}: {s['commit'][:12]} ({s['ref']}, locked {s.get('locked_at', '?')})")
    return 0


def cmd_doctor(args) -> int:
    problems = 0
    info(f"agentfiles {__version__}  ·  repo: {repo_root()}")
    for tool, why in (("git", "required"), ("claude", "Claude Code target"), ("codex", "Codex target"),
                      ("cursor-agent", "Cursor CLI (optional)"), ("opencode", "OpenCode target"),
                      ("pi", "pi target"), ("apm", "only for emit-apm users")):
        path = shutil.which(tool)
        info(f"  {'ok ' if path else '-- '} {tool:<13} {path or 'not found'}  ({why})")
        if tool == "git" and not path:
            problems += 1
    home = Path.home()
    shared = home / ".agents" / "skills"
    claude_dir = home / ".claude" / "skills"
    if shared.is_dir() and claude_dir.is_dir():
        dup = sorted({p.name for p in shared.iterdir()} & {p.name for p in claude_dir.iterdir()})
        if dup:
            warn(f"skills in both ~/.agents/skills and ~/.claude/skills (Cursor/OpenCode will see "
                 f"duplicates): {', '.join(dup)}")
            problems += 1
    try:
        cfg = Config(repo_root())
        for name, prof in cfg.profiles.items():
            cfg.resolve([name])
        info(f"  ok  {len(cfg.profiles)} profiles and {len(cfg.sources)} sources parse cleanly")
    except AgentfilesError as e:
        warn(str(e))
        problems += 1
    return 1 if problems else 0


def cmd_lock(args) -> int:
    """Pin every source used by the given profiles (default: all) without installing."""
    cfg = Config(repo_root())
    store = Store(cfg)
    names = args.profiles or sorted(cfg.profiles)
    keep: set[str] = set()
    for name in names:
        plan = build_plan(cfg.resolve([name]), store, frozen=args.frozen)
        verify_and_lock(plan, store, frozen=args.frozen)
        keep |= set(plan.digests)
    if not args.profiles:
        store.lock.prune_items(keep)
    changed = store.lock.dirty
    store.lock.save()
    info(f"agentfiles.lock {'updated' if changed else 'unchanged'}: "
         f"{len(store.lock.sources)} sources, {len(store.lock.items)} items")
    return 0


def cmd_emit_apm(args) -> int:
    cfg = Config(repo_root())
    store = Store(cfg)
    resolved = cfg.resolve(args.profiles)
    plan = build_plan(resolved, store)
    verify_and_lock(plan, store, frozen=False)
    store.lock.save()
    text = emit_apm(args.name or "-".join(args.profiles), plan, cfg, store)
    if args.output:
        Path(args.output).write_text(text)
        info(f"wrote {args.output}")
    else:
        sys.stdout.write(text)
    return 0


# --------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentfiles",
        description="Install profiles of AI agent skills and plugins into Claude Code, Codex, "
                    "Cursor, OpenCode and pi.")
    p.add_argument("--version", action="version", version=f"agentfiles {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def scoped(sp):
        sp.add_argument("--project", nargs="?", const=".", metavar="DIR",
                        help="install into a project (default: current dir) instead of your user config")

    s = sub.add_parser("sync", help="install/update/remove everything to match the given profiles")
    s.add_argument("profiles", nargs="*", help="profiles (default: default_profiles in agentfiles.yaml)")
    scoped(s)
    s.add_argument("--targets", help=f"comma list, subset of {','.join(KNOWN_TARGETS)}")
    s.add_argument("--dry-run", "-n", action="store_true", help="show what would change")
    s.add_argument("--frozen", action="store_true", help="fail instead of locking new sources (CI)")
    s.add_argument("--offline", action="store_true", help="use only cached sources")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("plan", help="same as `sync --dry-run`")
    s.add_argument("profiles", nargs="*")
    scoped(s)
    s.add_argument("--targets")
    s.add_argument("--frozen", action="store_true")
    s.add_argument("--offline", action="store_true")
    s.set_defaults(func=cmd_sync, dry_run=True)

    s = sub.add_parser("update", help="move sources to the latest commit of their ref, after review")
    s.add_argument("sources", nargs="*", help="sources to update (default: all)")
    s.add_argument("--yes", "-y", action="store_true", help="accept without prompting")
    s.add_argument("--diff", action="store_true", help="print the full diff for review")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("lock", help="resolve profiles and pin sources in agentfiles.lock without installing")
    s.add_argument("profiles", nargs="*", help="profiles to lock (default: all; also prunes unused entries)")
    s.add_argument("--frozen", action="store_true", help="verify the lock is complete and unchanged (CI)")
    s.set_defaults(func=cmd_lock)

    s = sub.add_parser("list", help="list profiles and sources, or show what profiles resolve to")
    s.add_argument("profiles", nargs="*")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("status", help="show what agentfiles installed")
    scoped(s)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("uninstall", help="remove everything agentfiles installed (for a scope)")
    scoped(s)
    s.add_argument("--yes", "-y", action="store_true")
    s.add_argument("--dry-run", "-n", action="store_true")
    s.set_defaults(func=cmd_uninstall)

    s = sub.add_parser("doctor", help="check tools, directories and config")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("emit-apm", help="write an apm.yml for profiles (for teammates using APM)")
    s.add_argument("profiles", nargs="+")
    s.add_argument("-o", "--output", help="file to write (default: stdout)")
    s.add_argument("--name", help="package name in apm.yml")
    s.set_defaults(func=cmd_emit_apm)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AgentfilesError as e:
        print(f"agentfiles: error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
