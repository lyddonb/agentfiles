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
  Installed skills are symlinks into those trees.
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
    explode: true                        # also share its skills via ~/.agents/skills (default true)
    native: true                         # install natively in Claude Code when possible (default true)
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
roles:                          # model per subagent role, per tool (written to ~/.agents/roles.yaml)
  code:      {claude-code: sonnet, cursor: grok-4.7-xhigh-fast}
  judgment:  {claude-code: opus}
  explorer:  {claude-code: sonnet}
  reviewers: {claude-code: [opus, sonnet]}   # a list = one reviewer per entry

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

## Project profiles

Put a `.agentfiles.yaml` (same keys as a profile) in a repo, then run
`agentfiles sync --project` from it. Or name profiles explicitly:
`agentfiles sync --project ~/src/app example-webapp`.

Project installs go to `<project>/.agents/skills` and Claude Code's **local** scope (your
checkout only). Anything your last global sync already installed is skipped, because tools
read both user and project locations and would show duplicates. The same goes for always-on
text: a project gets only the mode, instructions and roles that differ from your global sync,
written to personal files (`.claude/rules/agentfiles.md`, `.cursor/rules/agentfiles.mdc`,
`.agents/roles.yaml`) that agentfiles adds to `.git/info/exclude`. Add `.agentfiles/` to the
project's `.gitignore`. Teammates without agentfiles can use `agentfiles emit-apm`.

## Per-machine settings (local.yaml)

```yaml
default_profiles: [beau]                 # what a bare `agentfiles sync` installs here
targets: [claude-code, codex, pi]        # tools on this machine
roles:                                   # models this machine can use (wins over profiles)
  code: {cursor: composer-2}
source_overrides:
  mine: { path: ~/src/agent-kit }        # develop against a checkout
```
