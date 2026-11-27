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
**What:** Run `agentfiles sync base` on a real machine and confirm each tool lists the skills,
follows the symlinks, and that `{baseDir}`/relative script paths resolve. Fix anything that
doesn't (e.g. switch a tool to copies instead of symlinks).
**Progress:** Cursor no longer relies on `~/.agents/skills` for its channel. Sync installs
**real copies** into `~/.cursor/skills` (project: `.cursor/skills`) so Sync Skills / Cloud
works (symlinks do not). Local Agents Window `/` ignoring personal skills is a separate Cursor
product issue. Remaining: confirm Codex, OpenCode and pi on real machines still pick up
`~/.agents/skills`.
**Why deferred:** The build sandbox only had the Claude Code CLI. Claude Code was tested end to
end (global, project, prune, uninstall); the other tools' directory conventions come from their
current docs.
**Blocked by:** HUMAN_TASKS H4 (Cursor copies done; other tools still need human verification).

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

### R13. Cross-model roles through other agent CLIs — Done
A role entry such as `cli:cursor-agent:gpt-5.6-sol-high` is written to roles.yaml only when
agent-kit's `second_opinion.py` (agent-kit R11) can run it: `sync` and `plan` fail on a bad
prefix, an unknown agent or an empty model. The known agents are `CLI_AGENTS` in
`agentfiles/config.py`, a copy of the script's adapters that a CI step checks against the
agent-kit commit in `agentfiles.lock`. See [docs/PROFILES.md](docs/PROFILES.md#modes-and-roles).

### R20. Decide the always-on kb rule after agent-kit R42 — Done
Beau chose option A (HUMAN_TASKS H14): `profiles/beau.yaml` no longer has the two
`instructions:` paragraphs that told every agent to search the `kb` MCP server before design
work and to read topic pages by path. agent-kit's R42 eval
([PR 132](https://github.com/lyddonb/agent-kit/pull/132), evidence in
[`.changes/2026-11-26-r42-kb-eval/`](https://github.com/lyddonb/agent-kit/tree/main/.changes/2026-11-26-r42-kb-eval))
gave Claude Sonnet both paragraphs verbatim with the server connected, and none of its 10 runs
called or searched for it, the 2 in-scope tasks included. The kb server stays installed, so an
agent asked outright can still use it. Limits of that evidence: `claude -p` with no user
settings, Sonnet only, the paragraphs appended to the system prompt rather than loaded as a
rules file, 2 in-scope tasks, and a call would have been refused in that harness. Options B
(keep and measure in real sessions) and C (load named entries by id) were not chosen; R42 did
not support C either. A rule that brings a lookup back needs an eval in which agents make it.

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
ops. agentfiles does the installing, so three items land here. agent-kit's Knowledge factory
section adds R19. Its lock is also the input to
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
**Done when:** for each tool, the check fails after a sync of a skill whose header has no usable
`description` (sync installs it; the tool doesn't list it as a skill), and passes after a clean
sync of `base`. Reworded 2026-11-27 (Beau: "Use the no-description case"): on Claude Code 2.1.325
every header that keeps a skill from loading also fails agent-kit's `tools/validate.py`.
**Prioritize when:** with R0 or R11.
**Status (2026-11-27):** the Claude Code half is done (pull requests 39 and 40). `doctor` reads Claude Code's `init` event
(`claude -p --output-format stream-json --verbose`, killed before any model call) and compares
its plugins and skills with the plugins and skill folders the last sync installed in
`agentfiles-local`. Expected comes from the sync state, not the lock: the lock also pins plugins
a user may have installed from another marketplace instead, so a lock-based check fails on a
healthy machine. Measured on Claude
Code 2.1.325 over about 35 header variants: a skill is named by its folder, and it is listed as
a slash command and not as a skill when its header has no usable string `description`.
`resolve.py` installs such a skill without a word, so this is the check that sees it. The one
header validate accepts that hides a skill, `user-invocable: false`, is deliberate, and doctor
prints it as a note. The Done when is met for Claude Code by
`.changes/2026-11-27-r16-doctor-claude-code/proof.sh`. Codex, Cursor, OpenCode and pi still
wait on R0 and H4.

### R17. Upstream skills pass the lint at `agentfiles update` — Done
`update` lints each skill a source update changes and prints each new finding under the commit
that brought it in, and the update can still be accepted. The command check is vendored from
agent-kit's `tools/validate.py` into `agentfiles/lint.py`, scoped to each skill's own files. It
also flags scripts that pipe a download into a shell or read credential files, and hidden
Unicode in skill docs. See [docs/SECURITY.md](docs/SECURITY.md). Left out: "writes outside the
project", which a static read can't settle.

### R19. A narrow profile and policy for a proposing agent
**What:** A profile for an agent that runs on a schedule, reads the ledger and the books, and
proposes skill and knowledge edits as pull requests. Its policy says what it may do: read the
ledger and the books, write branches only (never `main`, never a merge), in agent-kit and its
own repo. Its `instructions:` require a leak check on every pull request body, commit message
and diff bound for a public repo, and a failure blocks the pull request. `agentfiles sync`
installs it like any profile. From agent-kit's Knowledge factory section (flags raised by
agents, read by one proposing agent) and Uber's
"[How Uber Evals 1 Million Agent Skill Invocations a Month](https://www.uber.com/us/en/blog/optimizing-ubers-agent-skills/)"
(read 2026-11-25), where a fix proposed from an agent's report is measured before it lands.
**Why not done:** no agent reads flags yet.
**Depends on:** agent-kit R45, and the agent that reads flags being built.
**Done when:** `agentfiles plan` for the profile shows only the tools and gates its policy
names, and a dry run that tries to push to `main` stops at the policy.
**Prioritize when:** the agent that reads flags is being built.

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
