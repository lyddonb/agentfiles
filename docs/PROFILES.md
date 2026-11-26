# Profiles and sources reference

## Files

| File | Committed? | Purpose |
|---|---|---|
| `sources.yaml` | yes | Upstream repos and the ref (branch/tag) each follows |
| `profiles/**/*.yaml` | yes | Profiles. Subfolders are just for organization; the profile name is the file name |
| `agentfiles.yaml` | yes | Repo-wide settings: default `targets`, `default_profiles` |
| `agentfiles.lock` | yes | Exact commit + content hash for everything profiles use |
| `local.yaml` | **no** (gitignored) | Per-machine overrides: same keys as `agentfiles.yaml` plus `source_overrides` |
| `<project>/.agentfiles.yaml` | your choice | A profile for one project, used by `sync --project` |

## sources.yaml

```yaml
sources:
  pstack:
    git: https://github.com/cursor/plugins
    ref: main
    watch: [pstack]                             # paths `update` reviews when no profile uses the source
  anthropic-skills:
    git: https://github.com/anthropics/skills   # any git URL, including private repos you can clone
    ref: main                                   # branch or tag that `agentfiles update` follows
  scratch:
    path: ~/src/my-skills                       # local directory: read live, never locked
```

- Git sources are cloned once into `~/.cache/agentfiles/git/` and each locked commit is
  extracted into an immutable tree under `~/.cache/agentfiles/trees/<source>/<commit>/`.
  Shared-dir installs (Codex, OpenCode, pi) are symlinks into those trees; Cursor and Claude
  Code get copies (Cursor for Sync Skills / Cloud; Claude because plugin paths may not escape).
- Changing a source's `git` or `ref` re-locks it on the next `sync` (or fails with `--frozen`).
- Private repos work if `git clone` works for you (SSH keys or a credential helper).

## Profiles

```yaml
description: One line shown by `agentfiles list`.
extends: [base]                 # profiles merged first, in order (depth-first, deduplicated)

skills:                         # Agent Skills
  - anthropic-skills:skills/pdf          # <source>:<path to a skill folder>
  - pi-skills:.                          # ...or a folder of skill folders (all of them)

plugins:                        # plugins: native in Claude Code, skills everywhere else
  - superpowers:@superpowers             # <source>:@<entry> - an entry in that repo's marketplace
  - anthropic-claude-code:plugins/feature-dev   # <source>:<path to a plugin folder>
  - ref: anthropic-claude-code:plugins/security-guidance
    allow: [hooks]                       # permit code-running components (see SECURITY.md)
    explode: true                        # also share its skills via tool skill dirs (default true)
    native: true                         # install natively in Claude Code when possible (default true)
    targets: [codex, cursor]             # only these tools (default: the profile's targets)
  - ref: podcast-studio:@podcast-studio
    requires:                            # setup agentfiles can't do for you; checked on sync/plan
      commands: [python3, ffmpeg]        # must be on PATH
      env: [GEMINI_API_KEY]              # must be set in the shell you run sync from
      note: Install ffmpeg and get a key at https://aistudio.google.com/apikey.

mcp:                            # MCP servers (Agent Plugins shape)
  docs:
    type: streamable-http                # streamable-http | sse | stdio
    url: https://example.com/mcp
  playwright:
    type: stdio
    command: npx
    args: ["-y", "@playwright/mcp@latest"]
    env: { DEBUG: "0" }

targets: [claude-code, codex]   # optional: override the tools for this profile (last one wins)

mode: beau-mode                 # a skill these profiles install; sync tells every tool to use it
                                # for non-trivial work. `mode: none` clears an inherited mode.
instructions:                   # extra always-on text, appended in profile order (deduplicated)
  - Prefer several small PRs to one large one.
roles:                          # model per subagent role, per tool (~/.agents/roles.yaml; projects: .agents/roles.yaml)
  code:      {claude-code: sonnet, cursor: grok-4.7-xhigh-fast}
  judgment:  {claude-code: opus}
  explorer:  {claude-code: sonnet}
  reviewers: {claude-code: [opus, sonnet]}   # a list = one reviewer per entry
policy:                         # the agent policy (agent-ledger S2), written to ~/.agents/policy.yaml
  gates: [prod-data]            # added to the ten default gates
  budgets: {tier2: {usd: 40}}   # lowered; budgets can only go down
  identity: {human: you@github}
commands:                       # a command on PATH that runs a script from a pinned source
  ledger: agent-ledger:ci/run_ledger.py

exclude:                        # drop items inherited through `extends`
  skills: [vercel:skills/composition-patterns]
  plugins: [anthropic-claude-code:plugins/feature-dev]
  mcp: [docs]
```

### How refs resolve

| Ref | Means |
|---|---|
| `src:path/to/skill` | A folder containing `SKILL.md` |
| `src:path/to/folder` | Every `*/SKILL.md` one level below (or under `folder/skills/`) |
| `src:path/to/plugin` | A plugin folder: skills from `skills/`, plus whatever Claude manifest it has |
| `src:@name` | The entry `name` in the repo's `.claude-plugin/marketplace.json`, `.agents/plugins/marketplace.json` or `.cursor-plugin/marketplace.json` |

Skills install under their frontmatter `name` (the spec says it must match the folder; when
an upstream breaks that rule, agentfiles warns and uses the frontmatter name).

### Manual setup (`requires:`)

Some skills and plugins need things agentfiles does not install: system commands, API keys,
feature flags. Declare them with `requires:` on the item (skills and plugins alike). After
every `sync` and `plan`, a **Manual setup** section checks each one in your current shell:

```
==> Manual setup
  ok  gdp-ts:skills/gdp-ts
  !!  podcast-studio:@podcast-studio
        not on PATH: ffmpeg
        not set in this shell: GEMINI_API_KEY
        Install ffmpeg and get a key at https://aistudio.google.com/apikey.
```

The note is shown only while something is missing. The env check sees only the shell that
runs agentfiles, so a key kept in a project `.env` file still shows as missing; say so in
the note when a tool accepts that.

### Merging rules

- `extends` is resolved depth-first; each profile is applied once.
- Later profiles add to `skills`, `plugins` and `mcp` (same ref or MCP name = override).
- `exclude` removes items contributed by earlier profiles.
- `targets`: the last profile that sets it wins; `--targets` on the command line beats all.
- Two different items that install a skill with the same name is an error. Fix it with `exclude`.
- `mode`: the last profile that sets it wins. `instructions`: appended in order, duplicates dropped.
- `roles`: merged per role and per tool; later profiles override single entries. `roles:` in
  `local.yaml` is applied last, because the models you can use depend on the machine.
- `policy`: stricter always wins, then `policy:` in `agentfiles.yaml` and then `local.yaml` are
  applied the same way (each merges; neither replaces the other). Gates,
  `sandbox_unattended`, `redact_patterns` and audit `sinks` only accumulate; every budget figure
  and `lfs_over_mb` take the lowest value given; `network_allow` only narrows (a host must be in
  every list that sets one); session archiving stays on once any profile turns it on. `identity`
  is not a strictness question: the last profile that sets a field wins. `approvers` is reserved.
- `commands`: the last profile that names a command wins.

### Modes and roles

A **mode** is a router skill (such as `beau-mode` from agent-kit's `bstack`) that decides how the
agent works on every non-trivial task: which playbook, which principles, what counts as done.
Naming it in a profile makes `sync` write an always-on instruction that points every tool at it.
`sync` fails if the mode isn't a skill the same profiles install.

**Roles** are the four kinds of subagent bstack skills start: `code` (implementation to a precise
brief), `judgment` (design, prose, synthesis, the hardest changes), `explorer` (bulk reading) and
`reviewers` (a panel; give it more than one model family where your tool has them). Skills look
up the entry for the tool they run in; a missing entry or `inherit` means the current model.
Model names are whatever that tool accepts: `opus`/`sonnet` in Claude Code, Cursor's model ids in
Cursor.

An entry that starts with `cli:` names another agent's CLI instead of a model: bstack skills
don't start a subagent for it but run agent-kit's `second_opinion.py`, which asks that CLI for a
read-only review.

```yaml
roles:
  reviewers: {claude-code: [opus, cli:cursor-agent:gpt-5.6-sol-high], cursor: [cli:claude:opus]}
```

The form is `cli:<agent>:<model>`, where the agent is one `second_opinion.py` can run (`claude` or
`cursor-agent`, the `CLI_AGENTS` table in `agentfiles/config.py`) and the model is whatever that
CLI's `--model` accepts. `sync` and `plan` fail on a malformed entry (a bad `cli` prefix such as
`CLI:`, an unknown agent, or no model), naming the role, the tool and the entry, so it never
reaches `roles.yaml`. They don't check that the CLI is installed: profiles are shared across
machines, and the script reports a missing CLI as `missing` when it runs.

## Project profiles

Put a `.agentfiles.yaml` (same keys as a profile) in a repo, then run
`agentfiles sync --project` from it. Or name profiles explicitly:
`agentfiles sync --project ~/src/app example-webapp`.

Project installs go to `<project>/.agents/skills` (Codex/OpenCode/pi),
`<project>/.cursor/skills` (Cursor), and Claude Code's **local** scope (your
checkout only). Anything your last global sync already installed is skipped, because tools
read both user and project locations and would show duplicates. The same goes for always-on
text: a project leaves out the mode and instructions your global sync actually wrote for Claude
Code, and the roles it actually wrote to `~/.agents/roles.yaml` (if it skipped a file, or Claude
Code wasn't a global target, the project gets the full text), written to personal files (`.claude/rules/agentfiles.md`, `.cursor/rules/agentfiles.mdc`,
`.agents/roles.yaml`) that agentfiles adds to `.git/info/exclude`. Cursor always gets the complete
text in a project, because its global copy is a paste-in snippet. The comparison uses your last
global sync, so re-run `sync --project` in a project after you change your global profiles. Add `.agentfiles/` to the
project's `.gitignore`. Teammates without agentfiles can use `agentfiles emit-apm`.

### Policy

`policy:` is opt-in: `sync` writes `~/.agents/policy.yaml` only when a profile in the set has the
key (`policy: {}` takes the defaults: the ten gates from agent-ledger's S2 and its tier 2 and 3
budgets). Agents read it to know which actions are gates and how big a run may be, and
agent-ledger reads its `security.redact_patterns`. The file is written for a global sync only. A
project's policy is its committed `.agents/policy.yaml`, written by hand;
`agentfiles policy check [PATH]` checks it parses and keeps every default gate and every gate in
your `~/.agents/policy.yaml`, and that it only tightens the rest: no budget or `lfs_over_mb` above
yours, no host you don't allow, no sandboxed tier dropped, archiving not turned off. Exit 0 ok, 1 a
problem, 2 no file. Redact patterns must be one line, without control characters, ` #` or the text
`redact_patterns`, which agent-ledger's strict reader can't read back.

### Commands

`commands:` puts a command on PATH that runs a Python script from a source, pinned like
everything else: `sync` writes a small shim to `bin_dir` (default `~/.local/bin`; set `bin_dir:` in
`local.yaml`; it must be absolute) that runs the script from the locked commit's tree with
`python3 -I -B`: the interpreter is the absolute path found at sync time, and neither the current
directory, `PYTHONPATH`, a `sitecustomize.py` nor bytecode can change what runs. The whole source
tree is hashed into `agentfiles.lock` (bytecode excluded) and its files are made read-only, and
`agentfiles update` reviews every change in the source before moving the pin. The hash is checked
at sync, not at every run, so an edit someone makes to the cached tree (after a `chmod`) runs
until the next sync reports it; this guards against mistakes and upstream changes, not against
your own user account. A command name that is a basic tool (`git`, `sh`, `python3` and so on) or
already found elsewhere on PATH is refused, and a binary or symlink already in `bin_dir` is left
alone. A cleared cache makes the shim say to run `agentfiles sync`. Global sync only.

## Per-machine settings (local.yaml)

```yaml
default_profiles: [beau]                 # what a bare `agentfiles sync` installs here
targets: [claude-code, codex, pi]        # tools on this machine
roles:                                   # models this machine can use (wins over profiles)
  code: {cursor: composer-2}
policy:                                  # tighten the policy on this machine (never loosen it)
  budgets: {tier2: {usd: 20}}
bin_dir: ~/bin                           # where `commands:` shims go (default ~/.local/bin)
source_overrides:
  mine: { path: ~/src/agent-kit }        # develop against a checkout
```

A source can also carry `targets:` (in `sources.yaml` or, per machine, in `source_overrides`).
Its items then install only into those tools, unless an item sets its own `targets:`. Use it
when a tool already gets that source another way. For example, if your claude.ai account syncs
agent-kit's marketplace from GitHub, Claude Code (and the desktop app) already have those
plugins, so keep agentfiles' copies to the other tools:

```yaml
source_overrides:
  mine: { path: ~/src/agent-kit, targets: [codex, cursor, opencode, pi] }
```
