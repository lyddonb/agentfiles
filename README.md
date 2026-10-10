# agentfiles

Dotfiles for AI agents. Pick skills and plugins from **your own repo and anyone else's**
(Anthropic, OpenAI, obra/superpowers, Vercel, kepano, ...), group them into **profiles**
(personas, machines, projects), **pin** them in a lockfile, and **sync** them into
**Claude Code, Codex, Cursor, OpenCode, and pi** with one command.

```bash
agentfiles sync builder            # install the "builder" persona everywhere
agentfiles sync --project          # install this repo's .agentfiles.yaml into the project
agentfiles update                  # review upstream changes, then accept them into the lock
```

- **One list, every tool.** Skills land once in `~/.agents/skills` (read by Codex, Cursor,
  OpenCode, pi) and in Claude Code through a generated local plugin marketplace.
- **Pinned and reviewable.** `agentfiles.lock` records the exact commit and a content hash
  of everything installed. Updates show you the commits and files that changed first.
- **Declarative.** `sync` makes each tool match the profile: it adds what's new, updates
  what changed, and removes what it previously installed but you dropped. It never touches
  files it didn't create.
- **Safe by default.** Plugins that run code (hooks, MCP servers, `bin/`) are only installed
  natively once you add `allow:` for them; until then you get their skills only.

## Quick start

```bash
git clone https://github.com/lyddonb/agentfiles ~/src/agentfiles
cd ~/src/agentfiles
pip install --user pyyaml                  # only dependency (or: pipx install -e .)
ln -s ~/src/agentfiles/bin/agentfiles ~/.local/bin/agentfiles

agentfiles list                            # profiles and sources
agentfiles list builder                    # what a profile resolves to
agentfiles plan builder                    # dry run: what would change
agentfiles sync builder                    # do it
agentfiles doctor                          # check tools and duplicates
```

Restart running agents afterwards so they pick up new skills.

## Profiles in this repo

| Profile | For | Highlights |
|---|---|---|
| `base` | every machine | `commit-message`, `handoff-notes`, `library-docs` + Context7 MCP, `skill-creator` |
| `builder` | shipping code | Superpowers (plan → TDD → debug → review), PR review agents, feature-dev, security guidance, webapp testing, React/Next.js and web design guidelines |
| `eng-lead` | leading an eng org | design reviews, interview kits, Word/PDF/PowerPoint/Excel skills, doc co-authoring, internal comms, writing guidelines |
| `knowledge` | Obsidian / research | Obsidian Markdown, Bases, Canvas, CLI, defuddle, YouTube transcripts |
| `beau` | your laptop | `builder` + `eng-lead` + `knowledge` |
| `example-webapp` | a project | `builder` + Playwright MCP, scoped to one repo |

Why each item is there, setup notes, and context cost: **[docs/PERSONAS.md](docs/PERSONAS.md)**.

## How it fits with agent-kit

```
 agent-kit  (you publish)            other people's repos
 skills + plugins in every format    anthropics/skills, obra/superpowers, ...
            \                                /
             \______ sources.yaml __________/
                          |
                 profiles/*.yaml  +  agentfiles.lock
                          |
                   agentfiles sync
        ┌─────────────┬───────┴──────┬──────────────┐
   Claude Code     Codex        Cursor / OpenCode    pi
```

[agent-kit](https://github.com/lyddonb/agent-kit) is where you **author** skills and plugins
and publish them so anyone can install them. agentfiles is where you **choose** what you use.
agent-kit is just the `mine` source here. To develop agent-kit and agentfiles together, point
`mine` at your checkout in `local.yaml` (see [examples/local.yaml](examples/local.yaml)).

## Commands

| Command | What it does |
|---|---|
| `sync [PROFILE...]` | Install, update and remove to match the profiles (default: `default_profiles`) |
| `plan [PROFILE...]` | Same as `sync --dry-run` |
| `sync --project [DIR]` | Install into a project, using `DIR/.agentfiles.yaml` and/or named profiles |
| `update [SOURCE...]` | Fetch newer commits of each source's `ref`, show the changes, accept into the lock |
| `lock [PROFILE...]` | Pin everything profiles use without installing (`--frozen` to verify in CI) |
| `list [PROFILE...]` | List profiles and sources, or show what profiles resolve to |
| `status [--project]` | What agentfiles has installed |
| `uninstall [--project]` | Remove everything agentfiles installed for that scope |
| `emit-apm PROFILE...` | Write an [APM](https://microsoft.github.io/apm/) `apm.yml` so teammates can install a profile without agentfiles |
| `doctor` | Check tools, config, and duplicate skills |

Common flags: `--targets claude-code,codex` (limit tools), `--frozen` (never re-lock; for CI),
`--offline` (use only cached sources), `--dry-run`.

## Documentation

- [docs/PROFILES.md](docs/PROFILES.md) — writing profiles and sources (reference)
- [docs/PERSONAS.md](docs/PERSONAS.md) — the bundled personas and why each item is in them
- [docs/TARGETS.md](docs/TARGETS.md) — exactly what happens in each tool, and MCP setup
- [docs/SECURITY.md](docs/SECURITY.md) — trust model, `allow:`, reviewing updates
- [ROADMAP.md](ROADMAP.md) · [HUMAN_TASKS.md](HUMAN_TASKS.md) (**blockers inside**) · [IDEAS.md](IDEAS.md)

## Development

```bash
python3 -m unittest discover -s tests      # offline tests, no agent CLIs needed
```

## License

MIT. Installed third-party skills and plugins keep their own licenses.
