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

### R6. Per-item target filters — Done
`targets:` on an item or a source (including a per-machine `source_overrides` entry). See
[docs/PROFILES.md](docs/PROFILES.md#per-machine-settings-localyaml).

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

---

# Skill ops

From Akshay's "[Our Claude skills and guidance, six months later](https://akshay.co/posts/our-claude-skills-and-guidance-six-months-later/)"
(read 2026-11-19): measure skills in use, test their behavior, then prune. The plan and the
map of all eight items across repos are in
[agent-kit's roadmap](https://github.com/lyddonb/agent-kit/blob/main/ROADMAP.md), under Skill
ops. agentfiles does the installing, so three items land here. Its lock is also the input to
agent-kit R38, which books use for every installed skill, third-party ones included.

## P1

### R16. `doctor` checks that each tool loaded what the lock says
**What:** After a sync, `agentfiles doctor` compares the skills each target tool reports as
loaded with the skills the lock and the synced profiles say it should have. A skill missing
from one tool, or loaded and not in the lock, is a problem line. This turns the checks R0 and
R11 do by hand into one command, and it covers every skill, not only "one skill triggers".
agent-kit's `verify-kit` skill (its R27) calls it.
**Why not done:** How each tool reports its loaded skills is not confirmed outside Claude Code
(R0). Settle that by prototype per tool.
**Depends on:** R0 and H4 for Codex, Cursor, OpenCode and pi. The Claude Code half needs neither.
**Done when:** the check fails for a skill whose YAML header is broken in a way agent-kit's
`tools/validate.py` accepts, and passes after a clean sync of `base`.
**Prioritize when:** with R0 or R11.

### R17. Upstream skills pass the lint at `agentfiles update`
**What:** `agentfiles update` runs agent-kit R39's check (a skill never names a script,
subcommand or flag that doesn't exist) on the third-party skills a source update changes, and
shows the failures beside the commits before the lock accepts them. It also runs the static
checks listed in [IDEAS.md](IDEAS.md) under Quality and safety. It reports and never blocks on
its own.
**Why not done:** The check does not exist yet.
**Depends on:** agent-kit R39.
**Done when:** an update to a fixture source whose new commit names a missing script prints the
failure next to that commit, and the update can still be accepted.
**Prioritize when:** agent-kit R39 has merged.

## P2

### R18. A skill retires from a profile first, and a new one starts on a trial
**What:** The profile half of agent-kit R41. Its monthly prune brief ranks skills by use and
cost and asks at most three retirement questions, third-party skills first, because they can
be measured and dropped but not fixed. A yes lands here as a PR that removes the item from a
profile. The source and the lock stay, so restoring it is one line. New third-party items
enter with `trial: 14d` (promoted from [IDEAS.md](IDEAS.md)): when the trial ends, the brief
shows the item's uses from agent-kit R38 and asks keep or drop.
**Why not done:** No skill use is booked, so nothing can be retired on evidence.
**Depends on:** agent-kit R38 and R41.
**Done when:** on fixture rows, a proposed retirement produces a profile diff that
`agentfiles plan` shows as only that removal, and an item past its trial is listed with its
uses. Nothing is removed without Beau's answer.
**Prioritize when:** agent-kit R38 has 60 days of rows.
