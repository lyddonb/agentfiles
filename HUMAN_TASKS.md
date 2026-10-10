# Human tasks

Things only you can do: accounts, your machines, judgment calls. **🚧 BLOCKER** items block
the listed work. Do them roughly in order.

| # | Task | Status |
|---|---|---|
| H1 | Publish agent-kit first (its HUMAN_TASKS H1/H2) | Done |
| H2 | Create the agentfiles repo and lock `mine` | Done |
| H3 | Install on your laptop and remove duplicate copies | Done |
| H4 | Verify Codex, Cursor, OpenCode and pi pick up the skills | 🚧 **BLOCKER** for ROADMAP R0–R2 |
| H5 | Review the plugins that run code before trusting them | To do |
| H6 | Merge the MCP snippets into Codex / Cursor / OpenCode | To do |
| H7 | Keep employer content in its own repo | Done |

---

### H1. Publish agent-kit first — Done
**Why:** Every profile pulls `mine:@essentials` and `mine:@research-tools` from
`https://github.com/lyddonb/agent-kit`. Until it exists, `sync` fails for every profile unless
you point `mine` at a local checkout in `local.yaml` (that's how the scaffold was tested).
**Steps:** Follow agent-kit's HUMAN_TASKS H1 (create + push) and H2 (license).
**Unblocks:** H2 and CI's `lock --frozen` step.

### H2. Create the agentfiles repo and lock `mine` — Done
**Why:** Needs your GitHub account. This repo is public and personal. Employer-specific
sources and profiles belong in a separate repo.
**Steps:**
```bash
cd agentfiles
git init -b main && git add -A && git commit -m "feat: initial agentfiles"
git remote add origin git@github.com:lyddonb/agentfiles.git && git push -u origin main
bin/agentfiles lock            # adds `mine` (agent-kit) to agentfiles.lock
git commit -am "chore: lock agent-kit" && git push
```
`agentfiles.lock` already pins the six third-party sources at the commits that were tested.

### H3. Install on your laptop and remove duplicate copies — Done
**Steps:**
1. `pip install --user pyyaml` and `ln -s ~/src/agentfiles/bin/agentfiles ~/.local/bin/agentfiles`.
2. `cp examples/local.yaml local.yaml` and edit `targets:` to the tools you actually have.
3. **Before syncing,** remove copies you installed by hand so nothing shows twice:
   - Claude Code: `claude plugin list`, then `claude plugin uninstall <id>` for anything agentfiles
     will now manage (e.g. `superpowers@claude-plugins-official`, `document-skills@anthropic-agent-skills`).
   - Skills folders: check `~/.claude/skills` and `~/.agents/skills` for copies of the same skills.
     `agentfiles doctor` flags overlaps.
4. `agentfiles plan`, read it, then `agentfiles sync`. Restart running agents.

### H4. Verify the other tools — 🚧 BLOCKER for ROADMAP R0–R2
**Why:** Only Claude Code was available where this was built.
**Steps:** After H3, in each tool you use, ask it to list its skills (or check its skills UI) and
confirm the `base` skills appear: `commit-message`, `handoff-notes`, `library-docs`,
`skill-creator`. Then try one (e.g. "write a commit message for the staged changes"). Note
anything missing in an issue; that becomes ROADMAP R0.

### H5. Review the plugins that run code
**Why:** Your judgment call on trust and cost. Three profile entries carry `allow:`:
- `superpowers` (`hooks`): a SessionStart hook that injects the `using-superpowers` skill, which
  aggressively pushes the agent to use skills. Read `hooks/` in obra/superpowers.
- `security-guidance` (`hooks`): Python hooks that call a model at turn end and on commit
  (extra cost), and install the Agent SDK at session start.
- `research-tools` (`mcp`): your own plugin; connects to Context7's hosted MCP server.
  Without an API key Context7 may rate-limit; check its current terms and add a key if needed.
Remove an `allow:` (or the entry) if you're not comfortable; you'll still get its skills.

### H6. Merge MCP snippets
**Why:** Automatic merging is ROADMAP R1; until then it's a copy-paste.
**Steps:** After `sync`, merge `~/.local/share/agentfiles/mcp/codex.toml`, `cursor.json` and
`opencode.json` into each tool's config (paths in [docs/TARGETS.md](docs/TARGETS.md)).

### H7. Keep employer content in its own repo — Done
**Why:** This repo is public. Profiles and docs here stay personal and generic.
**Decision:** No employer name, sources, or profiles in this repo. Company-specific skills,
profiles, and project setup live in a separate repo. That repo can depend on these public
repos and add its own private sources.
