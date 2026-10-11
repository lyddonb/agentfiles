# Roadmap

Planned work that is intentionally **not** in the initial version, why it was deferred, and
when to pick it up. Human-only work (accounts, verification on your machines, decisions) is in
[HUMAN_TASKS.md](HUMAN_TASKS.md).

**Priority key:** **P0** before relying on it daily · **P1** next, clear value ·
**P2** once there's real usage · **P3** only if a need shows up.

Order within a priority is the suggested order.

---

## P0

### R0. Verify the shared directory in Codex, Cursor, OpenCode and pi
**What:** Run `agentfiles sync base` on a real machine and confirm each tool lists the skills
from `~/.agents/skills`, follows the symlinks, and that `{baseDir}`/relative script paths
resolve. Fix anything that doesn't (e.g. switch a tool to copies instead of symlinks).
**Why deferred:** The build sandbox only had the Claude Code CLI. Claude Code was tested end to
end (global, project, prune, uninstall); the other tools' directory conventions come from their
current docs.
**Blocked by:** HUMAN_TASKS H4.

## P1

### R1. Merge MCP config into Codex, Cursor and OpenCode automatically
**What:** Instead of snippet files, merge agentfiles-managed servers into
`~/.codex/config.toml`, `~/.cursor/mcp.json` and `opencode.json`, tracking which entries it
owns so it can update and remove only those.
**Why deferred:** These are files you also edit by hand; OpenCode allows JSONC (comments) and
Codex uses TOML, so a safe round-trip editor (preserving comments and order) is real work.
Snippets are correct and safe in the meantime.
**Prioritize when:** you have more than ~3 MCP servers or change them often.

### R2. Native plugin installs in Codex, Cursor and pi
**What:** Mirror the Claude Code approach: a generated Codex marketplace
(`codex plugin marketplace add <path>` plus enabling entries in `config.toml`), a Cursor
equivalent, and `pi install <pinned tree path>` for pi packages (which can carry pi extensions).
When a plugin is native in a tool, stop sharing its skills to that tool to avoid duplicates.
**Why deferred:** Codex enables plugins in its app UI (there is no CLI install command), Cursor's
third-party flow needs verification, and the shared skills directory already delivers most of
the value (skills) to all of them. Needs R0 first.
**Prioritize when:** you want Codex/Cursor hooks, agents or app integrations from a plugin.

### R3. `agentfiles add` / `remove`
**What:** `agentfiles add builder anthropic-skills:skills/pdf` edits the profile YAML
(preserving comments) and syncs.
**Why deferred:** Editing YAML by hand is fine for one user; comment-preserving YAML editing
needs a dependency (ruamel.yaml) or care.
**Prioritize when:** profiles are edited weekly, or by people other than you.

### R4. Skill setup steps
**What:** Support skills that need setup (`npm install`, `pip install`) by running it in a
per-item copy under `~/.local/share/agentfiles/setup/<item>@<commit>/` instead of the immutable
tree, gated by `allow: [setup]`.
**Why deferred:** It runs third-party install scripts, so it needs the review story to be solid
first; few high-value skills need it (pi-skills' youtube-transcript and browser-tools do).
**Prioritize when:** a skill you want requires it.

## P2

### R5. Cache garbage collection
**What:** `agentfiles gc` removes trees for commits no longer in the lock or any state file.
**Why deferred:** Trees are small (a few MB each); disk use only grows with updates.
**Prioritize when:** `~/.cache/agentfiles` passes ~1 GB.

### R6. Per-item target filters
**What:** `targets: [claude-code]` on a single skill or plugin entry.
**Why deferred:** Profile-level `targets` plus `explode`/`native` cover the cases seen so far.
**Prioritize when:** a skill misbehaves in one tool but is wanted in others.

### R7. Windows support
**What:** Use directory junctions or copies where symlinks need Developer Mode; test paths.
**Why deferred:** Your machines are macOS/Linux.
**Prioritize when:** someone on Windows wants to use it.

### R8. Richer APM export
**What:** Emit APM `mcp:` entries and validate the output with the `apm` CLI in CI.
**Why deferred:** APM's custom-server schema wasn't verified; the current export comments MCP
servers out rather than guessing.
**Prioritize when:** a team adopts APM from an `emit-apm` file.

## P3

### R9. Package and publish the CLI
**What:** Publish to PyPI (`pipx install agentfiles`) with `AGENTFILES_HOME` pointing at your
config repo, separating the tool from your personal profiles.
**Why deferred:** One user; running from the checkout is simpler and keeps tool and config
versioned together.
**Prioritize when:** others want to use the tool with their own profiles.

### R10. More targets
**What:** Adapters for Gemini CLI, Amp, Droid, Kiro, GitHub Copilot CLI, etc.
**Why deferred:** Several already read `~/.agents/skills`; add a named target only when one
needs something extra (its own skills path, MCP format, or plugin install).

---

# Modes, roles and always-on instructions

Deferred from the first modes build (October 2026).

## P1

### R11. Verify the always-on block in each tool
**What:** After a sync, confirm each tool actually loads the block: Claude Code from
`~/.claude/rules/`, Codex from `~/.codex/AGENTS.md`, pi from `~/.pi/agent/AGENTS.md`, and the
pasted Cursor User Rule. Ask each agent "what instructions did you load about beau-mode?"
**Why not done:** The paths come from each tool's current docs; only Claude Code's CLI was
available while building, and it was not signed in as you.
**Blocked by:** HUMAN_TASKS H9.

### R12. Write Cursor User Rules and OpenCode `instructions` automatically
**What:** Replace the paste-in snippets: add the snippet path to the `instructions` list in
`opencode.json` (keeping comments, since OpenCode allows JSONC), and find a supported way to set
Cursor User Rules from outside the app.
**Why not done:** OpenCode's config can contain comments a plain JSON writer would drop. Cursor
stores User Rules in its own settings with no documented file. Snippets are correct and safe.
**Prioritize when:** you change the always-on text more than about once a month.

### R13. Cross-model roles through other agent CLIs
**What:** Accept role entries such as `cli:cursor-agent:gpt-5` and write them to roles.yaml,
paired with agent-kit's planned `second-opinion` script (agent-kit ROADMAP R11).
**Why not done:** Depends on that script.
**Prioritize when:** agent-kit R11 lands.

## P2

### R14. `agentfiles review-upstream`
**What:** A command that walks a watched source's pending changes file by file and, for files that
agent-kit adapted (listed in agent-kit's `docs/UPSTREAM.md`), shows the upstream diff next to
our version so you can decide adopt, adapt or skip.
**Why not done:** `agentfiles update pstack --diff` already shows the diff; the side-by-side view is
a convenience until upstream changes arrive often.
**Prioritize when:** reviewing pstack updates takes more than a few minutes.

### R15. Knowledge base as a source
**What:** Let a profile install a knowledge-base MCP server and point the always-on block at it,
so every agent can query team conventions while it works. See agent-kit `docs/KNOWLEDGE.md`.
**Why not done:** The knowledge base is its own follow-up project.
**Prioritize when:** the KB has an MCP interface.

