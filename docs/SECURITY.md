# Security and trust

Skills and plugins are code you let an agent act on. A skill can tell the agent to run its
scripts; a plugin hook runs on every matching event; an MCP server is a running process or a
remote service with access to whatever you give it. agentfiles cannot make untrusted content
safe. It makes what you install **explicit, pinned, and reviewable**.

## What agentfiles guarantees

- **Pinned content.** Every git source is locked to a commit in `agentfiles.lock`. Nothing
  changes on your machine until you run `agentfiles update` and accept the change.
- **Tamper check.** Each installed item has a content hash in the lock. If the files for a
  locked commit ever differ from the hash, `sync` stops with an error.
- **Review before update.** `agentfiles update` shows the commits and changed files that touch
  the paths your profiles use (`--diff` prints the full diff) and asks before accepting.
- **Lint on update.** For each skill an update changes, `update` reads its docs and scripts
  without running them and prints, under the commit that brought it in, each new problem: a
  command that names a script, subcommand or flag the skill doesn't ship, a script that pipes
  a download into a shell or reads a credential file, and hidden Unicode in a doc. It only
  reports: you can still accept the update. It can't tell a skill's own `scripts/` from the
  `scripts/` of a project the skill teaches you to build, so read each line before acting on it.
- **Gated code execution.** A plugin that ships hooks, MCP servers or a `bin/` folder is only
  installed natively in Claude Code when the profile lists them in `allow:`. Without it, you
  get the plugin's skills only.
- **No clobbering.** agentfiles only removes symlinks, Cursor skill copies, and plugins it
  recorded installing, and never overwrites a real file or a symlink it didn't create
  (Cursor's `~/.cursor/skills` skips unmanaged directories; Claude's generated marketplace is
  wholly owned and rewritten).
- **Immutable trees.** Shared-dir skills are symlinks into
  `~/.cache/agentfiles/trees/<source>/<commit>/`. Cursor and Claude Code get copies of those
  trees. agentfiles never modifies the cache trees; if anything else writes into them (for
  example a skill that runs `npm install` in its own folder), the next `sync` reports a hash
  mismatch.

## What it does not do

- It does not sandbox anything. Hooks, scripts and MCP servers run with your permissions.
- It does not vet content. Treat a new source like a new dependency.
- Snippet MCP configs for Codex/Cursor/OpenCode are written for you to merge by hand.

## Reviewing a new source or plugin

Before adding a source or an `allow:`:

1. Read the `SKILL.md` files and anything in `scripts/` they tell the agent to run.
2. For `allow: [hooks]`, read `hooks/hooks.json` and every script it calls.
3. For `allow: [mcp]`, check what each server is: a remote URL (who runs it, what data it
   sees) or a local command (what package it downloads, e.g. via `npx`).
4. Prefer pinning to a tag (`ref: v1.2.0`) for sources you don't control.

## Team use

For a team, keep the agentfiles repo (or a team fork) as the reviewed allowlist: changes to
`sources.yaml`, `allow:` and `agentfiles.lock` go through pull requests. CI can run
`agentfiles lock --frozen` to prove the lock covers every profile.
