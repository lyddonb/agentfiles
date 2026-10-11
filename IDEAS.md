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

