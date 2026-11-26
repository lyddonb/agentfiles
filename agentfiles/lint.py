"""Static checks on the skills a source update changes. They read files and never run one.

The command check comes from agent-kit's tools/validate.py (check_commands, agent-kit 7c4563d,
MIT). There it reads agent-kit's own layout; here each skill is a directory with a SKILL.md,
and its scripts are every script file under it, so two skills may ship scripts of the same name.
A JavaScript or TypeScript script is checked only for existence, since its flags can't be read.
"""
from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    message: str

    @property
    def key(self) -> tuple[str, str]:
        return self.path, self.message

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


GENERATED_RE = re.compile(r"^[ \t]*<!-- BEGIN GENERATED.*?^[ \t]*<!-- END GENERATED[^\n]*", re.S | re.M)
FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)")
SPAN_RE = re.compile(r"`([^`\n]+)`")
READABLE = (".py", ".sh")
SCRIPT_SUFFIXES = READABLE + (".js", ".mjs", ".cjs", ".ts")
SCRIPT_RE = re.compile(r"(?<![\w.-])([\w.-]+\.(?:py|sh|js|mjs|cjs|ts))(?![\w.-])")
ALIAS_RE = re.compile(r"`(\w+)` below is `([^`\n]+)`")
QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"|<[^<>|]*>")
FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")
DOC_FLAG_RE = re.compile(r"--[A-Za-z][\w-]*")
RUNNERS = {"python", "python3", "bash", "sh", "uv", "run", "exec", "time", "node", "npx", "bun", "deno", "tsx"}
PLACEHOLDER_RE = re.compile(r"[A-Z0-9_]+|.*[./].*")
SH_ARM_RE = re.compile(r"^\s*([-\w=*|\s]*--[a-z][-\w=*|\s]*)\)", re.M)
COMMAND_END_RE = re.compile(r"\s--\s|\s#|[|;>]|&&")

PIPE_TO_SHELL_RE = re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b")
CREDENTIALS_RE = re.compile(r"~/\.ssh/|\.aws/credentials|\.netrc\b|\.git-credentials|\bid_(?:rsa|ed25519)\b"
                            r"|\.docker/config\.json|\.kube/config")
COMMENT_STARTS = ("#", "//", "*", "/*")
VISIBLE_FORMAT_CHARS = {"­", "‍"}


@dataclass
class ScriptSpec:
    """What one script accepts. `flags` is None when they can't be read; `subcommands` is None when it has none."""
    path: Path
    flags: set[str] | None = field(default_factory=set)
    subcommands: dict[str, set[str]] | None = None

    def allowed(self, sub: str | None) -> set[str]:
        if self.subcommands is None:
            return self.flags
        if sub is None:
            return self.flags.union(*self.subcommands.values())
        return self.subcommands[sub]


@dataclass
class CommandRef:
    path: str
    line: int
    script: str
    in_scripts_dir: bool
    args: list[str]


def _flag_literals(node: ast.AST) -> set[str]:
    return {c.value for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and FLAG_RE.fullmatch(c.value)}


def _argparse_spec(path: Path, tree: ast.AST) -> ScriptSpec:
    """Follow the parser variables in source order, since one name is often rebound per subcommand."""
    spec = ScriptSpec(path, flags={"--help"})
    owner: dict[str, str | None] = {}
    holders: set[str] = set()
    calls = sorted((n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign, ast.Expr))
                    and isinstance(n.value, ast.Call) and isinstance(n.value.func, (ast.Attribute, ast.Name))),
                   key=lambda n: (n.lineno, n.col_offset))
    for stmt in calls:
        call, func = stmt.value, stmt.value.func
        method = func.attr if isinstance(func, ast.Attribute) else func.id
        recv = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else None
        bound = stmt.targets[0] if isinstance(stmt, ast.Assign) else getattr(stmt, "target", None)
        target = bound.id if isinstance(bound, ast.Name) else None
        if method == "ArgumentParser" and target:
            owner[target] = None
        elif method == "add_subparsers" and target and recv in owner:
            holders.add(target)
            spec.subcommands = spec.subcommands or {}
        elif method == "add_parser" and recv in holders:
            name = call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else None
            if not isinstance(name, str) or not target:
                raise ValueError(f"line {stmt.lineno}: add_parser needs a literal name and a variable")
            spec.subcommands[name] = {"--help"}
            owner[target] = name
            for kw in call.keywords:
                if kw.arg == "aliases":
                    for alias in ast.literal_eval(kw.value):
                        spec.subcommands[alias] = spec.subcommands[name]
        elif method in ("add_mutually_exclusive_group", "add_argument_group") and target and recv in owner:
            owner[target] = owner[recv]
        elif method == "add_argument":
            if recv not in owner:
                raise ValueError(f"line {stmt.lineno}: add_argument on {recv!r}, which can't be traced to a parser")
            if not all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in call.args):
                raise ValueError(f"line {stmt.lineno}: add_argument with a name that is not a string literal")
            flags = {a.value for a in call.args if a.value.startswith("--")}
            if any(kw.arg == "action" and "BooleanOptionalAction" in ast.dump(kw.value) for kw in call.keywords):
                flags |= {"--no-" + f[2:] for f in flags}
            (spec.flags if owner[recv] is None else spec.subcommands[owner[recv]]).update(flags)
    return spec


def script_spec(path: Path) -> ScriptSpec:
    """Read a script's subcommands and flags from its source. Raises ValueError when it can't."""
    if path.suffix not in READABLE:
        return ScriptSpec(path, flags=None)
    text = path.read_text(errors="replace")
    if path.suffix == ".sh":
        arms = SH_ARM_RE.findall(text) or [ln for ln in text.split("\n") if not ln.lstrip().startswith("#")]
        return ScriptSpec(path, flags={f for arm in arms for f in FLAG_RE.findall(arm)})
    tree = ast.parse(text)
    if any(isinstance(n, ast.Attribute) and n.attr == "add_argument" for n in ast.walk(tree)):
        return _argparse_spec(path, tree)
    flags: set[str] = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and any(a.arg == "argv" for a in fn.args.args):
            flags |= _flag_literals(fn)
    return ScriptSpec(path, flags=flags)


def _commands(text: str):
    """Yield (line number, command text): each inline code span, and each line of a fenced block
    with its backslash continuations joined."""
    fence, pending, start = None, "", 0
    for no, line in enumerate(text.split("\n"), 1):
        m = FENCE_LINE_RE.match(line)
        if m and fence in (None, m.group(1)):
            fence, pending = (None if fence else m.group(1)), ""
        elif fence:
            start = start if pending else no
            pending += line.rstrip()
            if pending.endswith("\\"):
                pending = pending[:-1] + " "
            else:
                yield start, pending
                pending = ""
        else:
            for m in SPAN_RE.finditer(line):
                yield no, m.group(1)


def command_refs(text: str, where: str) -> list[CommandRef]:
    text = GENERATED_RE.sub(lambda m: "\n" * m.group().count("\n"), text)
    aliases = dict(ALIAS_RE.findall(text))
    refs = []
    for no, command in _commands(text):
        first, _, rest = command.partition(" ")
        if first in aliases and rest:
            command = f"{aliases[first]} {rest}"
        found = list(SCRIPT_RE.finditer(command))
        for m, nxt in zip(found, found[1:] + [None]):
            before = COMMAND_END_RE.split(QUOTED_RE.sub("ARG", command[:m.start()]))[-1].rpartition("$(")[2]
            in_scripts_dir = before.endswith("scripts/") and not before.endswith("./scripts/")
            *runners, path = (before + "x").split()
            run = all(w in RUNNERS or not w.isalpha() for w in runners) and (in_scripts_dir or "/" not in path)
            tail = QUOTED_RE.sub(" ARG ", command[m.end():nxt.start() if nxt else len(command)])
            tail = COMMAND_END_RE.split(" " + tail + " ", maxsplit=1)[0]
            refs.append(CommandRef(where, no, m.group(1), in_scripts_dir, tail.split() if run else []))
    return refs


def check_ref(ref: CommandRef, specs: dict[str, ScriptSpec | None]) -> list[Finding]:
    def found(message: str) -> list[Finding]:
        return [Finding(ref.path, ref.line, message)]

    if ref.script not in specs:
        return found(f"names scripts/{ref.script}, which this skill does not ship") if ref.in_scripts_dir else []
    spec = specs[ref.script]
    if spec is None or spec.flags is None:
        return []
    args = [w.lstrip("[(") for w in ref.args]
    sub, at = None, len(args)
    if spec.subcommands is not None:
        for i, word in enumerate(args):
            if word.startswith("-") or (i and args[i - 1] in spec.flags):
                continue
            if not PLACEHOLDER_RE.fullmatch(word.rstrip("]")):
                sub, at = word.rstrip("]"), i
                if sub not in spec.subcommands:
                    return found(f"runs `{ref.script} {sub}`, but {ref.script} has no {sub!r} subcommand "
                                 f"(it has {', '.join(sorted(spec.subcommands))})")
            break
    out = []
    for i, word in enumerate(args):
        m = DOC_FLAG_RE.match(word)
        if not m:
            continue
        allowed = spec.flags if sub and i < at else spec.subcommands[sub] if sub else spec.allowed(None)
        if m.group() not in allowed:
            target = f"{ref.script} {sub}" if sub and i > at else ref.script
            place = " before the subcommand" if sub and i < at else ""
            out += found(f"passes {m.group()} to `{target}`{place}, which does not accept it there "
                         f"(it accepts {', '.join(sorted(allowed)) or 'no flags'})")
    return out


def _hidden_chars(text: str, where: str) -> list[Finding]:
    out = []
    for no, line in enumerate(text.split("\n"), 1):
        for col, ch in enumerate(line):
            if (unicodedata.category(ch) == "Cf" and ch not in VISIBLE_FORMAT_CHARS
                    and not (no == 1 and col == 0 and ch == "﻿")):
                name = unicodedata.name(ch, "unnamed")
                out.append(Finding(where, no, f"hidden character U+{ord(ch):04X} ({name})"))
    return out


def _risky_lines(text: str, where: str) -> list[Finding]:
    out = []
    for no, line in enumerate(text.split("\n"), 1):
        if line.lstrip().startswith(COMMENT_STARTS):
            continue
        if PIPE_TO_SHELL_RE.search(line):
            out.append(Finding(where, no, "pipes a download into a shell"))
        if CREDENTIALS_RE.search(line):
            out.append(Finding(where, no, "reads a credential file"))
    return out


def _own_files(skill: Path, nested: list[Path]) -> list[Path]:
    return sorted(p for p in skill.rglob("*")
                  if p.is_file() and not p.is_symlink() and not any(n in p.parents for n in nested))


def lint_skill(root: Path, skill: Path, nested: list[Path]) -> list[Finding]:
    files = _own_files(skill, nested)
    specs: dict[str, ScriptSpec | None] = {}
    out: list[Finding] = []
    for path in files:
        if path.suffix not in SCRIPT_SUFFIXES:
            continue
        rel = str(path.relative_to(root))
        out += _risky_lines(path.read_text(errors="replace"), rel)
        if path.name in specs:
            specs[path.name] = None
            continue
        try:
            specs[path.name] = script_spec(path)
        except (ValueError, SyntaxError):
            specs[path.name] = None
    for md in (p for p in files if p.suffix == ".md"):
        rel = str(md.relative_to(root))
        text = md.read_text(errors="replace")
        out += _hidden_chars(text, rel)
        for ref in command_refs(text, rel):
            out += check_ref(ref, specs)
    return out


def lint_tree(root: Path, skills: list[Path]) -> list[Finding]:
    """Lint each skill directory. Findings are deduplicated and their paths are relative to `root`."""
    every = sorted({p.parent for p in root.rglob("SKILL.md")})
    seen, out = set(), []
    for skill in skills:
        nested = [s for s in every if skill in s.parents]
        for f in lint_skill(root, skill, nested):
            if (f.path, f.line, f.message) not in seen:
                seen.add((f.path, f.line, f.message))
                out.append(f)
    return out


def skill_of(root: Path, rel: str) -> Path | None:
    """The nearest directory holding a SKILL.md that contains the path `rel`."""
    p = (root / rel).parent
    while p == root or root in p.parents:
        if (p / "SKILL.md").is_file():
            return p
        if p == root:
            return None
        p = p.parent
    return None


def lint_at(root: Path, skills: list[str]) -> list[Finding]:
    """Lint the skills, given relative to `root`, that exist there."""
    return lint_tree(root, [root / s for s in skills if (root / s / "SKILL.md").is_file()])


def changed_skills(root: Path, changed: list[str]) -> list[str]:
    """The skills, relative to `root`, that hold the `changed` paths."""
    return sorted({str(s.relative_to(root)) for s in (skill_of(root, rel) for rel in changed) if s})


def new_findings(old_root: Path, new_root: Path, skills: list[str]) -> list[Finding]:
    """Findings in `skills` at the new tree that the old tree didn't have."""
    before = {f.key for f in lint_at(old_root, skills)}
    return [f for f in lint_at(new_root, skills) if f.key not in before]


def introduced_by(findings: list[Finding], keys_at: list[tuple[str, set[tuple[str, str]]]]) -> dict[str, list[Finding]]:
    """Group findings by the commit that brought each in for good. `keys_at` is each commit, oldest
    first, with the finding keys its tree has. A finding no commit can account for goes under ""."""
    out: dict[str, list[Finding]] = {}
    for f in findings:
        intro = ""
        for sha, keys in keys_at:
            if f.key not in keys:
                intro = ""
            elif not intro:
                intro = sha
        out.setdefault(intro, []).append(f)
    return out
