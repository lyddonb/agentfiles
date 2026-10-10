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
- **Gated code execution.** A plugin that ships hooks, MCP servers or a `bin/` folder is only
  installed natively in Claude Code when the profile lists them in `allow:`. Without it, you
  get the plugin's skills only.
- **No clobbering.** agentfiles only removes symlinks and plugins it recorded installing, and
  never overwrites a real file or a symlink it didn't create.
- **Immutable trees.** Installed skills point into `~/.cache/agentfiles/trees/<source>/<commit>/`.
  agentfiles never modifies those; if anything else writes into them (for example a skill
  that runs `npm install` in its own folder), the next `sync` reports a hash mismatch.

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
