"""The agent policy (agent-ledger spec S2): which actions are gates, run budgets, security rules,
audit sinks and identity. Profiles set it under `policy:`; `sync` writes ~/.agents/policy.yaml.

Profiles merge in order, then local.yaml, and stricter always wins: gates and security rules
only accumulate, and a budget can be lowered but never raised. So a profile or a machine can
tighten the policy but can't loosen what another profile set. A project's committed
.agents/policy.yaml is checked with `agentfiles policy check`: it may add gates, never drop one.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import yaml

from .util import AgentfilesError

# S2's defaults. The budgets are placeholders until recorded runs calibrate them.
DEFAULT_GATES = ("migration", "delete-data", "public-api", "deploy", "auth-permissions",
                 "new-dependency", "secrets", "outbound-message", "license", "spend")
DEFAULT_POLICY: dict = {
    "version": 1,
    "gates": list(DEFAULT_GATES),
    "budgets": {
        "tier2": {"usd": 50, "tokens": 8000000, "wall_clock": "8h", "max_parallel_agents": 4},
        "tier3": {"usd": 150, "tokens": 20000000, "wall_clock": "24h", "max_parallel_agents": 6},
    },
    "security": {
        "sandbox_unattended": [2, 3],
        "network_allow": ["github.com", "registry.npmjs.org", "pypi.org"],
        "redact_patterns": [],
    },
    "audit": {"sinks": ["repo"], "sessions": {"archive": True, "lfs_over_mb": 20}},
    "identity": {"scheduled_owner": "creator"},
    "approvers": {},
}

TIERS = ("tier2", "tier3")
BUDGET_KEYS = ("usd", "tokens", "wall_clock", "max_parallel_agents")
KNOWN_SINKS = ("repo",)  # s3-object-lock and external come in M4
_GATE = re.compile(r"[a-z][a-z0-9-]*")
_DURATION = re.compile(r"([0-9]+)([mhd])")
_HOST = re.compile(r"[A-Za-z0-9.-]+")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*@[a-z]+")
_UNREADABLE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\ufeff]")


def _minutes(value) -> int | None:
    m = _DURATION.fullmatch(value) if isinstance(value, str) else None
    return int(m.group(1)) * {"m": 1, "h": 60, "d": 1440}[m.group(2)] if m else None


def _keys(where: str, raw: dict, allowed) -> None:
    extra = sorted(set(raw) - set(allowed))
    if extra:
        raise AgentfilesError(f"{where}: unknown keys {extra}; known: {', '.join(allowed)}")


def _pos_int(v) -> bool:
    return type(v) is int and v > 0


def parse_policy(raw, where: str) -> dict:
    """Validate a `policy:` mapping (a full or partial policy). Returns a deep copy."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise AgentfilesError(f"{where}: policy must be a mapping")
    _keys(where, raw, ("version", "gates", "budgets", "security", "audit", "identity", "approvers"))
    if "version" in raw and (type(raw["version"]) is not int or raw["version"] != 1):
        raise AgentfilesError(f"{where}: policy version must be 1")
    if "gates" in raw:
        gates = raw["gates"]
        if not isinstance(gates, list) or not all(isinstance(g, str) and _GATE.fullmatch(g) for g in gates):
            raise AgentfilesError(f"{where}: policy.gates must be a list of gate ids like new-dependency")
    if not isinstance(raw.get("budgets") or {}, dict):
        raise AgentfilesError(f"{where}: policy.budgets must map tier2 or tier3 to a budget")
    for tier, b in (raw.get("budgets") or {}).items():
        if tier not in TIERS:
            raise AgentfilesError(f"{where}: policy.budgets.{tier}: unknown tier; known: {', '.join(TIERS)}")
        if not isinstance(b, dict):
            raise AgentfilesError(f"{where}: policy.budgets.{tier} must be a mapping")
        _keys(f"{where}: policy.budgets.{tier}", b, BUDGET_KEYS)
        for k in ("usd", "tokens", "max_parallel_agents"):
            if k in b and not _pos_int(b[k]):
                raise AgentfilesError(f"{where}: policy.budgets.{tier}.{k} must be a positive whole number")
        if "wall_clock" in b and not _minutes(b["wall_clock"]):
            raise AgentfilesError(f"{where}: policy.budgets.{tier}.wall_clock must be a duration like 90m, 8h or 2d")
    sec = raw.get("security") or {}
    if not isinstance(sec, dict):
        raise AgentfilesError(f"{where}: policy.security must be a mapping")
    _keys(f"{where}: policy.security", sec, ("sandbox_unattended", "network_allow", "redact_patterns"))
    if "sandbox_unattended" in sec and (not isinstance(sec["sandbox_unattended"], list)
                                        or not all(t in (1, 2, 3) and type(t) is int for t in sec["sandbox_unattended"])):
        raise AgentfilesError(f"{where}: policy.security.sandbox_unattended must list tiers 1 to 3")
    if "network_allow" in sec and (not isinstance(sec["network_allow"], list)
                                   or not all(isinstance(h, str) and _HOST.fullmatch(h) for h in sec["network_allow"])):
        raise AgentfilesError(f"{where}: policy.security.network_allow must list host names")
    if "redact_patterns" in sec and not isinstance(sec["redact_patterns"], list):
        raise AgentfilesError(f"{where}: policy.security.redact_patterns must be a list")
    for i, pat in enumerate(sec.get("redact_patterns") or []):
        # agent-ledger reads these with a strict reader (no YAML library): a pattern it can't
        # read back exactly would stop every ledger write, so refuse it here instead.
        if not isinstance(pat, str) or not pat or _UNREADABLE.search(pat) or " #" in pat \
                or "redact_patterns" in pat:
            raise AgentfilesError(f"{where}: policy.security.redact_patterns[{i}] must be a one-line regex "
                                  f"without control characters, ' #' or the text redact_patterns "
                                  f"(agent-ledger can't read those back)")
        try:
            re.compile(pat)
        except re.error as e:
            raise AgentfilesError(f"{where}: policy.security.redact_patterns[{i}] is not a valid regex: {e}") from None
    audit = raw.get("audit") or {}
    if not isinstance(audit, dict):
        raise AgentfilesError(f"{where}: policy.audit must be a mapping")
    _keys(f"{where}: policy.audit", audit, ("sinks", "sessions"))
    if "sinks" in audit and (not isinstance(audit["sinks"], list)
                             or not all(isinstance(x, str) and x in KNOWN_SINKS for x in audit["sinks"])):
        raise AgentfilesError(f"{where}: policy.audit.sinks may only list {', '.join(KNOWN_SINKS)} in M0")
    sessions = audit.get("sessions") or {}
    if not isinstance(sessions, dict):
        raise AgentfilesError(f"{where}: policy.audit.sessions must be a mapping")
    _keys(f"{where}: policy.audit.sessions", sessions, ("archive", "lfs_over_mb"))
    if "archive" in sessions and type(sessions["archive"]) is not bool:
        raise AgentfilesError(f"{where}: policy.audit.sessions.archive must be true or false")
    if "lfs_over_mb" in sessions and not _pos_int(sessions["lfs_over_mb"]):
        raise AgentfilesError(f"{where}: policy.audit.sessions.lfs_over_mb must be a positive whole number")
    ident = raw.get("identity") or {}
    if not isinstance(ident, dict):
        raise AgentfilesError(f"{where}: policy.identity must be a mapping")
    _keys(f"{where}: policy.identity", ident, ("human", "scheduled_owner"))
    if "human" in ident and not (isinstance(ident["human"], str) and _IDENTITY.fullmatch(ident["human"])):
        raise AgentfilesError(f"{where}: policy.identity.human must look like <login>@github")
    owner = ident.get("scheduled_owner")
    if "scheduled_owner" in ident and not (owner == "creator" or (isinstance(owner, str) and _IDENTITY.fullmatch(owner))):
        raise AgentfilesError(f"{where}: policy.identity.scheduled_owner must be creator or <login>@github")
    if raw.get("approvers") not in (None, {}):
        raise AgentfilesError(f"{where}: policy.approvers is reserved for M4; leave it empty")
    return copy.deepcopy(raw)


def _union(a: list, b: list) -> list:
    return a + [x for x in b if x not in a]


def merge_policy(base: dict, over: dict) -> dict:
    """Apply `over` on top of `base`; whichever is stricter wins (S2 "Files and precedence")."""
    out = copy.deepcopy(base)
    if "gates" in over:
        out["gates"] = _union(out.get("gates", []), over["gates"])
    for tier, b in (over.get("budgets") or {}).items():
        cur = out.setdefault("budgets", {}).setdefault(tier, {})
        for k, v in b.items():
            if k not in cur:
                cur[k] = v
            elif k == "wall_clock":
                cur[k] = v if _minutes(v) < _minutes(cur[k]) else cur[k]
            else:
                cur[k] = min(cur[k], v)
    sec, osec = out.setdefault("security", {}), over.get("security") or {}
    if "sandbox_unattended" in osec:
        sec["sandbox_unattended"] = sorted(set(sec.get("sandbox_unattended", [])) | set(osec["sandbox_unattended"]))
    if "network_allow" in osec:
        # Allowing a host loosens the policy, so a later profile can narrow the list, not widen it.
        sec["network_allow"] = ([h for h in sec["network_allow"] if h in osec["network_allow"]]
                                if "network_allow" in sec else list(osec["network_allow"]))
    if "redact_patterns" in osec:
        sec["redact_patterns"] = _union(sec.get("redact_patterns", []), osec["redact_patterns"])
    audit, oaudit = out.setdefault("audit", {}), over.get("audit") or {}
    if "sinks" in oaudit:
        audit["sinks"] = _union(audit.get("sinks", []), oaudit["sinks"])
    osess = oaudit.get("sessions") or {}
    sess = audit.setdefault("sessions", {})
    if "archive" in osess:
        sess["archive"] = bool(sess.get("archive")) or osess["archive"]
    if "lfs_over_mb" in osess:
        sess["lfs_over_mb"] = min(sess.get("lfs_over_mb", osess["lfs_over_mb"]), osess["lfs_over_mb"])
    # Who you are isn't a strictness question: the last profile (or the machine) says.
    out.setdefault("identity", {}).update(over.get("identity") or {})
    out["version"] = 1
    out["approvers"] = {}
    return out


def _scalar(v) -> str:
    """A YAML scalar that every reader, including agent-ledger's strict ones, reads the same."""
    if v is True or v is False:
        return "true" if v else "false"
    if type(v) is int:
        return str(v)
    s = str(v)
    return "'" + s.replace("'", "''") + "'"


def _flow(d: dict, keys) -> str:
    return "{" + ", ".join(f"{k}: {_scalar(d[k])}" for k in keys if k in d) + "}"


def render_policy(profiles: list[str], policy: dict) -> str:
    """policy.yaml text. Every string is single-quoted, the one form agent-ledger's policy reader
    accepts for redact patterns, and the result must read back as exactly `policy`."""
    lines = ["# Generated by `agentfiles sync` from profiles: " + ", ".join(profiles),
             "# Agent policy (agent-ledger spec S2): gates, budgets, security, audit, identity.",
             "# Stricter always wins across profiles and local.yaml. Edit profiles, not this file.",
             "version: 1", "gates:"]
    lines += [f"  - {_scalar(g)}" for g in policy.get("gates", [])]
    lines.append("budgets:")
    for tier in TIERS:
        if tier in policy.get("budgets", {}):
            lines.append(f"  {tier}: {_flow(policy['budgets'][tier], BUDGET_KEYS)}")
    sec = policy.get("security", {})
    lines += ["security:",
              f"  sandbox_unattended: [{', '.join(_scalar(t) for t in sec.get('sandbox_unattended', []))}]",
              f"  network_allow: [{', '.join(_scalar(h) for h in sec.get('network_allow', []))}]"]
    pats = sec.get("redact_patterns", [])
    lines += ["  redact_patterns: []"] if not pats else ["  redact_patterns:"] + [f"    - {_scalar(p)}" for p in pats]
    audit = policy.get("audit", {})
    lines += ["audit:", f"  sinks: [{', '.join(_scalar(s) for s in audit.get('sinks', []))}]",
              f"  sessions: {_flow(audit.get('sessions', {}), ('archive', 'lfs_over_mb'))}"]
    ident = policy.get("identity", {})
    lines.append("identity:" if ident else "identity: {}")
    lines += [f"  {k}: {_scalar(ident[k])}" for k in ("human", "scheduled_owner") if k in ident]
    lines.append("approvers: {}")
    text = "\n".join(lines) + "\n"
    if sum("redact_patterns" in line.split("#", 1)[0] for line in text.splitlines()) != 1:
        raise AgentfilesError("the policy mentions redact_patterns outside its own key (in an identity?); "
                              "agent-ledger couldn't read it")
    if yaml.safe_load(text) != policy:
        raise AgentfilesError("internal: the rendered policy doesn't read back as the merged policy")
    return text


def check_project_policy(path: Path, user_policy: dict | None) -> list[str]:
    """Problems with a project's committed .agents/policy.yaml. It must parse, and it may only
    tighten what applies to you (S2: stricter wins at each level): it keeps every default and
    user gate, sets no budget or LFS limit above yours, doesn't turn session archiving off,
    allows no host you don't, and drops no sandboxed tier."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        return [f"{path}: can't read it as YAML: {e}"]
    try:
        project = parse_policy(raw or {}, str(path))
    except AgentfilesError as e:
        return [str(e)]
    mine = merge_policy(DEFAULT_POLICY, parse_policy(user_policy, "your policy") if user_policy else {})
    out = []
    if "gates" in project:
        missing = [g for g in mine["gates"] if g not in project["gates"]]
        if missing:
            out.append(f"{path}: gates can be added, not removed; missing {', '.join(missing)}")
    for tier, b in (project.get("budgets") or {}).items():
        for k, v in b.items():
            cap = mine["budgets"].get(tier, {}).get(k)
            if cap is not None and (_minutes(v) > _minutes(cap) if k == "wall_clock" else v > cap):
                out.append(f"{path}: budgets.{tier}.{k} {v} is above yours ({cap}); a project can only lower it")
    sec, msec = project.get("security") or {}, mine["security"]
    wider = [h for h in sec.get("network_allow", []) if h not in msec["network_allow"]]
    if wider:
        out.append(f"{path}: network_allow adds {', '.join(wider)}, which your policy doesn't allow")
    dropped = [t for t in msec["sandbox_unattended"] if "sandbox_unattended" in sec and t not in sec["sandbox_unattended"]]
    if dropped:
        out.append(f"{path}: sandbox_unattended drops tier {', '.join(map(str, dropped))}")
    sess = (project.get("audit") or {}).get("sessions") or {}
    if sess.get("archive") is False and mine["audit"]["sessions"].get("archive"):
        out.append(f"{path}: audit.sessions.archive can't be turned off")
    if "lfs_over_mb" in sess and sess["lfs_over_mb"] > mine["audit"]["sessions"]["lfs_over_mb"]:
        out.append(f"{path}: audit.sessions.lfs_over_mb is above yours")
    return out
