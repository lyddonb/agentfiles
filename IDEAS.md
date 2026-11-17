# Ideas

Maybe-someday ideas that don't earn a roadmap slot yet. Promote one to
[ROADMAP.md](ROADMAP.md) when a real need appears.

## Profiles and personas
- **Context budgets per profile** — `max_always_on_tokens: 3000`; `sync` warns when a profile
  exceeds it (Claude Code's `plugin details` already estimates cost).
- **Auto-selected project profiles** — pick a profile from repo signals (`package.json` with
  `next` → web profile, `pyproject.toml` → Python profile).
- **Time-boxed trials** — `trial: 14d` on an item; `sync` reminds you to keep or drop it.
- **An employer profile and a "new hire" profile** — onboarding skills (repo map, deploy
  process, review norms). Belongs in a private repo, not here.

## Discovery
- **`agentfiles search <term>`** across all sources' skill names and descriptions.
- **Popularity / freshness signals** in `list`: last upstream commit, stars, open issues.
- **Watch new upstream skills** — the weekly CI job could also list skills added upstream that
  no profile uses yet.

## Quality and safety
- **Static checks on install** — flag skills whose scripts use `curl | sh`, write outside the
  project, or read credential files; show it during `update`.
- **Hidden-Unicode scan** of `SKILL.md` files (APM does this), to catch prompt-injection tricks.
- **Per-skill usage stats** from Claude Code transcripts to find skills you never use.

## Ergonomics
- **Shell completion** for profile and source names.
- **`agentfiles diff PROFILE_A PROFILE_B`** to compare personas.
- **Menu-bar / TUI picker** for switching personas quickly. Probably overkill.

## Modes
- **Mode per directory.** Let `~/code/<work-folder>` default to one mode and personal repos to
  another, without a `.agentfiles.yaml` in each.
- **`agentfiles mode <name>`** to switch the always-on mode for a while (for example to
  `superpowers` for a week) and switch back.
- **Show the active mode in each tool's status line** where the tool allows it.


## From "Steering AI Beyond Automation" (2026-11-15)

Ideas from Narayanan and Unger's [essay](https://www.normaltech.ai/p/steering-ai-beyond-automation) on collaboration over full automation.
Context and reasoning: [notes in agent-ledger](https://github.com/lyddonb/agent-ledger/blob/main/docs/notes/steering-beyond-automation.md).

- **An `interactive` role in `roles.yaml`.** A fast, low-latency model per tool for attended
  work, which talks with the human while the `code` and `judgment` roles do deep work in the
  background. agent-kit would name the role in beau-mode; agentfiles writes the model for it per
  tool, and a missing entry still means "use the current model".
- **A `steer` command or hint in the policy.** Once agent-ledger has `steer` entries, tell each
  tool's global instructions where a human can post one mid-run, so steering works the same in
  every tool.

## From "intent over steps" (2026-11-16)

Context and reasoning: [notes in agent-ledger](https://github.com/lyddonb/agent-ledger/blob/main/docs/notes/intent-over-steps.md).

- **Instructions say outcomes, not steps.** A `doctor` check that flags profile `instructions:`
  written as procedures ("first run X, then Y") instead of outcomes ("tests prove the
  behavior, not the implementation"). The always-on block costs tokens in every session, so
  it should hold only what changes the result.
- **`agentfiles census`.** One list of everything this setup owns and runs: installed skills
  and plugins (the lock), scheduled jobs and their owners, watched repos, books repos. It
  fails when a scheduled job has no owner or two. The pieces exist today in `agentfiles.lock`,
  `watched.csv` and `identity.scheduled_owner`, spread across repos.
- **Policy gates as hooks.** Where a tool supports hooks (Claude Code today), generate hooks
  from `~/.agents/policy.yaml` that stop a gated action (deploy, delete-data, spend,
  outbound-message) until the ledger has a gate answer. Prose asks; a hook enforces. Install
  only behind `allow: [hooks]`.

