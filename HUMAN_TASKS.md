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
| H8 | Merge agent-kit's bstack, then re-lock `mine` | Done |
| H9 | Sync builder and check each tool loads beau-mode | To do |
| H10 | Confirm the model names in `roles:` | To do |
| H11 | Review the pending pstack changes | To do |
| H12 | Merge agent-kit's verification and planning branch, then re-lock `mine` | 🚧 **BLOCKER** for bstack 0.2.0 in your tools |

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

### H8. Merge agent-kit's bstack, then re-lock `mine` — Done

### H9. Sync builder and check each tool loads beau-mode
**Steps:**
1. `agentfiles plan beau`, read it, then `agentfiles sync beau`.
2. Paste `~/.local/share/agentfiles/instructions/cursor-user-rule.md` into Cursor Settings > Rules >
   User Rules.
3. In Claude Code and Cursor, start a session and ask "which instructions about beau-mode did you
   load, and where from?" Then try `/beau-mode` on a small real task.
4. If you previously installed Superpowers yourself, uninstall that copy
   (`claude plugin uninstall superpowers@<marketplace>`); `builder` no longer includes it.
This is ROADMAP R11.

### H10. Confirm the model names in `roles:`
**Why:** Model availability depends on your subscriptions. The Cursor ids in
`profiles/personas/builder.yaml` (`claude-opus-5-5-xhigh`, `grok-4.7-xhigh-fast`) are pstack's
defaults from October 2026, not read from your account.
**Steps:** In Cursor, check the model ids you can pick for subagents and fix `roles:` in
`builder.yaml`, or override per machine in `local.yaml`. Claude Code's `opus` and `sonnet` are aliases
and should not need changes.

### H11. Review the pending pstack changes
**Why:** agentfiles pins pstack at the commit bstack was first adapted from (`ccb5507`). Two upstream
commits have landed since (head `11713c6`): one distills many skill prompts (including several
principles, `reflect` and `unslop`) and one adds a `/ketchup` skill. agent-kit's verification and
planning branch ported its new skills from `11713c6`, so they already include the distillation;
the older files don't (agent-kit ROADMAP R14). Recommendation: adopt the distillation for the
principles, `reflect` and `unslop` in one agent-kit PR, and skip `/ketchup` unless you want it.
**Steps:** `agentfiles update pstack --diff`, then for each change decide adopt, adapt or skip per
agent-kit `docs/UPSTREAM.md`. Accept the new pstack commit into the lock after the agent-kit PR that
acts on it lands.

### H12. Merge agent-kit's verification and planning branch, then re-lock `mine` — 🚧 BLOCKER
**Why:** bstack 0.2.0 (verification skills, why, teach, recall, architect, arena, swarm,
technical-writing and the Multi-phase plan playbook) is on agent-kit's
`feat/bstack-verification-and-planning` branch. The lock still pins `mine` at `c481932`.
**Steps:**
1. Merge that agent-kit branch.
2. Here: `agentfiles update mine --yes`, commit `agentfiles.lock`, and merge.
3. `agentfiles sync beau`. Your `local.yaml` already points `mine` at `~/code/agent-kit`, so with that
   checkout on the branch you can sync it before merging.

