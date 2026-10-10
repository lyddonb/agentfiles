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

### Merging rules

- `extends` is resolved depth-first; each profile is applied once.
- Later profiles add to `skills`, `plugins` and `mcp` (same ref or MCP name = override).
- `exclude` removes items contributed by earlier profiles.
- `targets`: the last profile that sets it wins; `--targets` on the command line beats all.
- Two different items that install a skill with the same name is an error. Fix it with `exclude`.

## Project profiles

Put a `.agentfiles.yaml` (same keys as a profile) in a repo, then run
`agentfiles sync --project` from it. Or name profiles explicitly:
`agentfiles sync --project ~/src/app example-webapp`.

Project installs go to `<project>/.agents/skills` and Claude Code's **local** scope (your
checkout only). Anything your last global sync already installed is skipped, because tools
read both user and project locations and would show duplicates. Add `.agentfiles/` to the
project's `.gitignore`. Teammates without agentfiles can use `agentfiles emit-apm`.

## Per-machine settings (local.yaml)

```yaml
default_profiles: [beau]                 # what a bare `agentfiles sync` installs here
targets: [claude-code, codex, pi]        # tools on this machine
source_overrides:
  mine: { path: ~/src/agent-kit }        # develop against a checkout
```
