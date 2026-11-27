"""agentfiles command line."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

import yaml

from . import __version__, loaded
from .apm import emit_apm
from .config import KNOWN_TARGETS, Config, Profile, parse_profile
from .lint import Finding, changed_skills, introduced_by, key_counts, lint_at, new_findings
from .policy import check_project_policy
from .resolve import build_plan, verify_and_lock
from .store import Store
from .targets import Applier, Desired, Scope, desired_state
from .util import (AgentfilesError, confirm, info, read_json, read_yaml, repo_root, short, state_dir,
                   step, warn)

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
    """Paths to review on update: what profiles use, else what the source says to watch."""
    paths = set()
    for prof in cfg.profiles.values():
        for it in prof.skills + prof.plugins:
            if it.source == source:
                paths.add(it.path if it.path else ".")
        if any(c.source == source for c in prof.commands.values()):
            paths.add(".")  # a command runs the whole source tree
    if not paths:
        paths = set(cfg.sources[source].watch)
    return sorted(paths)


MAX_LINT_COMMITS = 50


def _lint_update(store: Store, name: str, old: str, new: str, paths: list[str]) -> dict[str, list[Finding]]:
    """New lint findings in the skills this update changes, keyed by the commit that brought each in."""
    try:
        new_root = store.tree_at(name, new)
        skills = changed_skills(new_root, store.changed_files(name, old, new, paths))
        if not skills:
            return {}
        before = key_counts(lint_at(store.tree_at(name, old), skills))
        found = new_findings(before, lint_at(new_root, skills))
        if not found:
            return {}
        commits = store.commits_touching(name, old, new, skills)
        if len(commits) > MAX_LINT_COMMITS:
            return {"": found}
        with tempfile.TemporaryDirectory(prefix="agentfiles-lint-") as tmp:
            counts_at = [(sha, key_counts(lint_at(store.extract(name, sha, skills, Path(tmp) / sha), skills,
                                                  store.files_at(name, sha))))
                         for sha in commits]
        return introduced_by(found, counts_at, before)
    except Exception as e:
        warn(f"{name}: the skill lint could not run ({type(e).__name__}: {e}); review the update by hand")
        return {}


def _print_commits(log: str, findings: dict[str, list[Finding]]) -> None:
    """The commit log with each commit's new lint findings under it. Findings are reports, never a block."""
    lines = (log or "(no commits touching these paths)").splitlines()
    placed: set[str] = set()
    for i, line in enumerate(lines):
        short = line.split(" ", 1)[0]
        hits = [(sha, fs) for sha, fs in findings.items() if sha and sha.startswith(short)]
        if i < 40 or hits:
            info("    " + line)
        for sha, fs in hits:
            placed.add(sha)
            info("\n".join(f"      ! {f}" for f in fs))
    rest = [f for sha, fs in findings.items() if sha not in placed for f in fs]
    if rest:
        info("    (not tied to one of these commits)")
        info("\n".join(f"      ! {f}" for f in rest))
    if findings:
        n = sum(len(fs) for fs in findings.values())
        info(f"  lint: {n} new finding(s) in the changed skills. They don't block the update.")


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
            _print_commits(log, _lint_update(store, name, old, new, paths))
            if stat:
                info("  files:")
                info("\n".join("    " + l for l in stat.splitlines()[-25:]))
            if args.diff:
                info(store.diff(name, old, new, paths))
        if confirm(f"  Accept {name} @ {new[:12]}?", args.yes):
            store.lock.set_source(src, new)
            changed += 1
    if changed:
        # Items carry their own commit and hash; move them with their source, or the lock says
        # one commit for the source and installs another for its skills, plugins and commands.
        _pin_items(cfg, store, sorted(cfg.profiles), frozen=False)
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
    if r.mode:
        info(f"Mode: {r.mode}")
    if r.roles:
        info("Roles: " + "; ".join(f"{role}: " + ", ".join(f"{t}={m}" for t, m in tools.items())
                                   for role, tools in r.roles.items()))
    if r.policy is not None:
        info(_policy_summary(r.policy))
    if r.commands:
        info("Commands: " + ", ".join(f"{c.name} ({c.source}:{c.path})" for c in r.commands.values()))
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
    cursor_links = state.get("cursor_links") or {}
    info(f"Scope: {state.get('scope')}")
    info(f"Shared skills ({len(links)}): " + ", ".join(sorted(Path(d).name for d in links)))
    info(f"Cursor skills ({len(cursor_links)}): "
         + ", ".join(sorted(Path(d).name for d in cursor_links)))
    broken = [d for d, s in {**links, **cursor_links}.items() if not Path(d).exists()]
    if broken:
        warn(f"missing installed skills: {', '.join(broken)}")
    c = state.get("claude") or {}
    gen = c.get("generated_links") or {}
    info(f"Claude Code agentfiles plugin skills ({len(gen)}): " + ", ".join(sorted(gen)))
    info(f"Claude Code plugins: {', '.join(c.get('plugins') or []) or '(none)'}")
    info(f"Claude Code MCP servers: {', '.join(c.get('mcp') or {}) or '(none)'}")
    instr = state.get("instructions") or {}
    info(f"Always-on instructions: {', '.join(short(p) for p in instr) or '(none)'}")
    roles = state.get("roles") or {}
    info(f"Model roles file: {short(roles['path']) if roles.get('path') else '(none)'}")
    pol = state.get("policy") or {}
    if pol.get("path") and Path(pol["path"]).exists():
        info(f"Policy file: {short(pol['path'])}")
        try:
            info("  " + _policy_summary(yaml.safe_load(Path(pol["path"]).read_text()) or {}))
        except yaml.YAMLError:
            warn(f"{short(pol['path'])} doesn't parse as YAML")
    else:
        info("Policy file: (none)")
    cmds = state.get("commands") or {}
    info(f"Commands: {', '.join(short(p) for p in sorted(cmds)) or '(none)'}")
    lock = read_json(repo_root() / "agentfiles.lock", default={}) or {}
    if lock.get("sources"):
        info("\nLocked sources:")
        for n, s in sorted(lock["sources"].items()):
            info(f"  {n}: {s['commit'][:12]} ({s['ref']}, locked {s.get('locked_at', '?')})")
    return 0


def error(msg: str) -> None:
    print(f"agentfiles: error: {msg}", file=sys.stderr)


def _policy_summary(policy: dict) -> str:
    gates = policy.get("gates") or []
    budgets = "; ".join(f"{tier} ${b.get('usd')}, {b.get('tokens')} tokens, {b.get('wall_clock')}, "
                        f"{b.get('max_parallel_agents')} agents"
                        for tier, b in (policy.get("budgets") or {}).items() if isinstance(b, dict))
    return f"Policy: {len(gates)} gates ({', '.join(gates)}); budgets: {budgets or '(none)'}"


def cmd_policy(args) -> int:
    """Check a project's committed .agents/policy.yaml (S2): it parses, and drops no gate."""
    path = Path(args.path) if args.path else Path.cwd() / ".agents" / "policy.yaml"
    if not path.exists():
        error(f"{path} not found")
        return 2
    user = None
    user_path = Path.home() / ".agents" / "policy.yaml"
    if user_path.exists():
        try:
            user = yaml.safe_load(user_path.read_text()) or {}
        except yaml.YAMLError as e:
            error(f"{short(user_path)} doesn't parse: {e}")
            return 2
    problems = check_project_policy(path, user)
    for p in problems:
        error(p)
    if problems:
        return 1
    info(f"ok: {path} parses and keeps every gate"
         + (f" in the defaults and {short(user_path)}" if user is not None else " in the defaults"))
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
    cursor_dir = home / ".cursor" / "skills"
    claude_dir = home / ".claude" / "skills"
    if shared.is_dir() and claude_dir.is_dir():
        dup = sorted({p.name for p in shared.iterdir()} & {p.name for p in claude_dir.iterdir()})
        if dup:
            warn(f"skills in both ~/.agents/skills and ~/.claude/skills (Cursor/OpenCode will see "
                 f"duplicates): {', '.join(dup)}")
            problems += 1
    if shared.is_dir() and cursor_dir.is_dir():
        # Expected when Codex/OpenCode/pi and Cursor are both targets: shared dir is for
        # those tools, ~/.cursor/skills is Cursor's channel. Cursor also discovers
        # ~/.agents/skills, so the same name can appear twice there. Not a doctor failure.
        dup = sorted({p.name for p in shared.iterdir()} & {p.name for p in cursor_dir.iterdir()})
        if dup:
            shown = ", ".join(dup[:8]) + ("…" if len(dup) > 8 else "")
            info(f"  note  {len(dup)} skill name(s) in both ~/.agents/skills and ~/.cursor/skills "
                 f"(Cursor may list them twice when both tool sets are targets): {shown}")
    try:
        cfg = Config(repo_root())
        for name, prof in cfg.profiles.items():
            cfg.resolve([name])
        info(f"  ok  {len(cfg.profiles)} profiles and {len(cfg.sources)} sources parse cleanly")
        for src in cfg.sources.values():
            if src.path is not None and not src.path.is_dir():
                warn(f"source '{src.name}' points at {src.path}, which does not exist. "
                     f"Fix its path in sources.yaml or source_overrides in local.yaml.")
                problems += 1
    except AgentfilesError as e:
        warn(str(e))
        problems += 1
    # A moved checkout leaves symlinks that still look installed; only resolving them shows it.
    state = read_json(state_dir() / "state.json", default={}) or {}
    link_dests = list(state.get("links") or {}) + list(state.get("cursor_links") or {})
    link_dests += list(((state.get("claude") or {}).get("generated_links") or {}).values())
    broken = sorted(str(p) for p in link_dests if not Path(p).exists())
    if broken:
        warn(f"{len(broken)} installed skill link(s) no longer resolve (a source checkout moved or "
             f"was deleted). Fix the source path, then run `agentfiles sync`:\n    "
             + "\n    ".join(broken))
        problems += 1
    elif link_dests:
        info(f"  ok  {len(link_dests)} installed skill links resolve")
    problems += _doctor_claude_loaded(state.get("claude") or {})
    return 1 if problems else 0


def _doctor_claude_loaded(claude_state: dict) -> int:
    expected = loaded.expected_from_state(claude_state)
    if expected is None:
        info("  --  Claude Code load check: the last sync installed no Claude Code plugins")
        return 0
    if not shutil.which("claude"):
        info("  --  Claude Code load check: claude not found")
        return 0
    init = loaded.claude_init()
    if init is None:
        warn("Claude Code load check: `claude -p` gave no init event, so what it loaded is unknown")
        return 1
    report = loaded.compare(expected, init)
    for note in report.notes:
        info(f"  note  {note}")
    for problem in report.problems:
        warn(problem)
    if not report.problems:
        n = sum(len(s) for s in expected.plugins.values())
        info(f"  ok  Claude Code {init.get('claude_code_version', '?')} loaded all {len(expected.plugins)} "
             f"agentfiles plugins and {n} skills from the last sync")
    return len(report.problems)


def _pin_items(cfg: Config, store: Store, profiles: list[str], *, frozen: bool) -> set[str]:
    """Pin each item the profiles use at its source's locked commit; return the items' keys."""
    keys: set[str] = set()
    for name in profiles:
        plan = build_plan(cfg.resolve([name]), store, frozen=frozen)
        verify_and_lock(plan, store, frozen=frozen)
        keys |= set(plan.digests)
    return keys


def cmd_lock(args) -> int:
    """Pin every source used by the given profiles (default: all) without installing."""
    cfg = Config(repo_root())
    store = Store(cfg)
    keep_items = _pin_items(cfg, store, args.profiles or sorted(cfg.profiles), frozen=args.frozen)
    if not args.profiles:
        # Only a lock of every profile knows which items are unused; a subset must leave the rest
        # alone. Sources stay while sources.yaml defines them, used or not: `update` pins every
        # defined source, and a watched one (pstack) keeps its last reviewed commit here.
        stale = store.lock.stale(keep_items, set(cfg.sources))
        if stale and args.frozen:
            raise AgentfilesError("agentfiles.lock has entries no profile uses (run `agentfiles lock` "
                                  "and commit the result):\n    " + "\n    ".join(stale))
        store.lock.prune(keep_items, set(cfg.sources))
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

    s = sub.add_parser("policy", help="check a project's .agents/policy.yaml against the gate rules")
    psub = s.add_subparsers(dest="policy_command", required=True)
    pc = psub.add_parser("check", help="it must parse and keep every default and user gate")
    pc.add_argument("path", nargs="?", help="the policy file (default: .agents/policy.yaml here)")
    pc.set_defaults(func=cmd_policy)

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
