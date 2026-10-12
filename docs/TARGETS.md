# What happens in each tool

`agentfiles sync` writes to three channels. Paths shown for the user (global) scope;
with `--project DIR` the same things happen under `DIR/`.

| Tool | Skills | Plugins | MCP servers |
|---|---|---|---|
| Claude Code | via the generated `agentfiles-local` marketplace | **native** (hooks, agents, commands, MCP) when the plugin has a Claude manifest and its risky parts are allowed | `claude mcp add-json` (profile servers); plugin servers come with the plugin |
| Codex | `~/.agents/skills` | skills only | snippet: `~/.local/share/agentfiles/mcp/codex.toml` |
| Cursor | `~/.agents/skills` | skills only | snippet: `~/.local/share/agentfiles/mcp/cursor.json` |
| OpenCode | `~/.agents/skills` | skills only | snippet: `~/.local/share/agentfiles/mcp/opencode.json` |
| pi | `~/.agents/skills` | skills only | none (pi has no built-in MCP) |

## The shared skills directory

`~/.agents/skills` (project: `.agents/skills`) is the cross-tool convention: Codex, Cursor,
OpenCode and pi all read it. agentfiles puts **one symlink per skill** there, pointing into the
pinned, immutable source tree in `~/.cache/agentfiles/trees/`. Plugins contribute their skills
here too (set `explode: false` on a plugin to stop that).

agentfiles never writes to `~/.claude/skills`: Cursor and OpenCode read it *as well as*
`~/.agents/skills`, so skills placed in both show up twice. `agentfiles doctor` warns if it
finds the same skill in both.

## Claude Code

Claude Code doesn't read `~/.agents/skills`. Instead agentfiles maintains one local
marketplace at `~/.local/share/agentfiles/claude-marketplace` (projects get their own, named
`agentfiles-<project>-<hash>`):

- plugin **`agentfiles`** — every standalone skill from your profiles, as symlinks
  (invoked as `/agentfiles:<skill>`), plus skills of plugins that can't install natively;
- one plugin per **native** plugin — a symlink to the plugin's pinned tree, so its hooks,
  agents, commands and MCP servers work exactly as the author intended.

Why our own marketplace instead of adding upstream marketplaces directly:

1. **Pinning.** Upstream marketplaces track the latest commit; ours points at the locked tree.
2. **Reserved names.** Claude Code only lets official marketplace names
   (`claude-code-plugins`, `anthropic-agent-skills`, ...) come from GitHub's `anthropics` org,
   so a pinned local copy of them is refused. Re-exposing the plugins under one name avoids that.
3. **One place to clean up.** Uninstalling is `agentfiles uninstall`.

Plugins are installed at **user** scope globally and **local** scope in projects. The
marketplace itself is always declared in user settings, because Claude Code refuses
symlinked plugin entries from marketplaces declared at local scope.

A plugin installs natively when its source repo lists it in `.claude-plugin/marketplace.json`
or it has `.claude-plugin/plugin.json`, **and** any hooks, MCP servers or `bin/` it ships are
listed in `allow:`. Otherwise only its skills are installed (through the `agentfiles` plugin)
and `sync` prints a note.

If you already installed the same plugin yourself (for example `superpowers@claude-plugins-official`),
uninstall that copy to avoid duplicates: `claude plugin uninstall superpowers@claude-plugins-official`.

## MCP servers outside Claude Code

Codex, Cursor and OpenCode keep MCP servers in config files you also edit by hand, so
agentfiles writes ready-to-merge snippets instead of editing them (automatic merging is
ROADMAP R1):

| Tool | Merge the snippet into |
|---|---|
| Codex | `~/.codex/config.toml` (or `.codex/config.toml` in a trusted project) |
| Cursor | `~/.cursor/mcp.json` (or `.cursor/mcp.json`) |
| OpenCode | the `mcp` key of `~/.config/opencode/opencode.json` |

Snippets include both profile `mcp:` servers and servers bundled inside plugins (since those
tools only receive the plugins' skills).

## Native plugins in Codex, Cursor and pi

agentfiles currently gives these tools plugin *skills* (which is most of the value for
portable plugins). Installing plugins natively in them is ROADMAP R2. Until then you can
still install a plugin natively by hand, for example
`codex plugin marketplace add obra/superpowers` or `pi install git:github.com/obra/superpowers`
— set `explode: false` on that plugin in your profile so its skills aren't installed twice.

## Always-on instructions

A profile's `mode`, `instructions` and `roles` become one Markdown block. agentfiles puts it where
each tool reads global instructions, and never touches anything outside its own markers or files:

| Tool | Global | Project (`sync --project`) |
|---|---|---|
| Claude Code | `~/.claude/rules/agentfiles.md` (a file agentfiles owns; Claude Code loads every file in `~/.claude/rules/`) | `.claude/rules/agentfiles.md` |
| Codex | block between `agentfiles` markers in `~/.codex/AGENTS.md` (`AGENTS.override.md` if that is the active file; `CODEX_HOME` respected) | not written: Codex reads only the shared `AGENTS.md` |
| pi | block in `~/.pi/agent/AGENTS.md`, or in whichever context file already exists there | not written |
| OpenCode | block in `~/.config/opencode/AGENTS.md` if it exists or if `~/.claude/CLAUDE.md` doesn't; otherwise a snippet to add to `instructions` in `opencode.json` (creating that file would stop OpenCode reading your `~/.claude/CLAUDE.md`) | not written |
| Cursor | a snippet at `~/.local/share/agentfiles/instructions/cursor-user-rule.md` to paste into Settings > Rules > User Rules (Cursor keeps them in its settings) | `.cursor/rules/agentfiles.mdc` with `alwaysApply: true` |

Model roles go to `~/.agents/roles.yaml` (project: `.agents/roles.yaml`), which bstack skills read.

Safety rules:
- Shared files keep everything outside the markers byte for byte (removing the block only tidies the
  blank lines where it was); `uninstall` removes only the block, and deletes the file only if
  agentfiles created it and nothing else is left. Markers that are duplicated, unpaired or out of
  order make agentfiles leave the file alone until you fix them.
- Paste-in snippets are deleted when no longer needed (and on `uninstall`); `sync` then reminds you
  to remove them from Cursor or `opencode.json`.
- Files agentfiles owns are rewritten only if they still match what it last wrote. If you edited one,
  `sync` and `uninstall` leave it alone and say so. Put the change in a profile's `instructions:`.
- Project files are added to `.git/info/exclude`, so they never show up as changes to commit.

## Files agentfiles owns

| Path | Contents |
|---|---|
| `~/.cache/agentfiles/git/` | bare clones of sources |
| `~/.cache/agentfiles/trees/<source>/<commit>/` | immutable extracted trees (safe to delete; re-created on sync) |
| `~/.local/share/agentfiles/claude-marketplace/` | generated Claude marketplace |
| `~/.local/share/agentfiles/mcp/` | MCP snippets |
| `~/.local/state/agentfiles/state.json` | what the last global sync installed (used for pruning) |
| `~/.claude/rules/agentfiles.md`, `~/.agents/roles.yaml` | always-on instructions for Claude Code; model roles |
| `~/.local/share/agentfiles/instructions/` | paste-in instruction snippets (Cursor, sometimes OpenCode) |
| `<project>/.agentfiles/` | the same three for a project (gitignore it) |

`XDG_CACHE_HOME`, `XDG_DATA_HOME` and `XDG_STATE_HOME` are respected.
