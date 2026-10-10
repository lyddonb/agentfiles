# Personas

Four bundled profiles, plus `beau` (all three personas) and an example project profile.
Everything listed was checked to exist upstream and installs cleanly with
`agentfiles sync` (October 2026, commits in `agentfiles.lock`).

## Choosing

| If you are... | Sync |
|---|---|
| setting up any machine | `base` |
| writing code most of the day | `builder` |
| running the eng org: hiring, reviews, planning, comms | `eng-lead` |
| working in an Obsidian vault | `knowledge` |
| on your own laptop | `beau` (set `default_profiles: [beau]` in `local.yaml`) |

Profiles combine freely: `agentfiles sync builder eng-lead`.

### Context cost

Every installed skill adds its name and description to each session; the body loads only
when used. Measured with `claude plugin details` in Claude Code:

| Profile | Claude Code plugins | Always-on cost (approx.) |
|---|---|---|
| base | 3 | ~400 tokens |
| knowledge | 4 | ~1,200 tokens |
| eng-lead | 5 | ~2,000 tokens |
| builder | 7 | ~4,900 tokens |
| beau | 10 | ~7,100 tokens |

If `beau` feels heavy, sync personas per project instead of everything globally:
`base` globally, `builder` via `.agentfiles.yaml` in code repos.

---

## base — every machine

| Item | From | Why |
|---|---|---|
| `essentials` plugin: `commit-message`, `handoff-notes` | agent-kit | Commit messages from the staged diff; hand work between sessions and tools (Claude Code ⇄ Codex ⇄ pi) without re-explaining |
| `research-tools` plugin: `library-docs` + Context7 MCP | agent-kit | Version-correct library docs instead of memory. `allow: [mcp]` because it ships a (remote, read-only) MCP server |
| `skill-creator` | anthropics/skills | The fastest way to grow this setup: turn a repeated workflow into a skill, then publish it in agent-kit |

## builder — shipping code

| Item | From | Why | Notes |
|---|---|---|---|
| **Superpowers** plugin (15 skills) | obra/superpowers | A complete workflow: brainstorming → writing plans → TDD → systematic debugging → requesting/receiving review → finishing a branch, plus git worktrees and parallel subagents | `allow: [hooks]`: in Claude Code a SessionStart hook injects `using-superpowers`, which strongly pushes the agent to check for and use skills before acting. Expect more deliberate (slower) starts. Other tools get the skills without the hook |
| `pr-review-toolkit` plugin | anthropics/claude-code | Six specialized review agents: general code review, tests, silent failures, type design, comments, simplification | Claude Code only (agents + commands) |
| `feature-dev` plugin | anthropics/claude-code | `/feature-dev`: explore → clarify → architect → implement → review, with dedicated agents | Claude Code only |
| `security-guidance` plugin | anthropics/claude-code | Regex warnings on risky edits, an LLM review of the diff at turn end, agentic review on `git commit` | `allow: [hooks]`; extra model calls (cost/latency); installs the Agent SDK on first session. Claude Code only. Drop it if the cost isn't worth it |
| `webapp-testing` | anthropics/skills | Verify UI changes by driving the app with Playwright | Needs Python Playwright in the project |
| `mcp-builder` | anthropics/skills | Building MCP servers well (relevant to agent-kit R7) | |
| `frontend-design` | anthropics/skills | Distinctive UI instead of generic templates | |
| `vercel-react-best-practices` | vercel-labs/agent-skills | React/Next.js performance rules | Installs under its frontmatter name |
| `vercel-composition-patterns` | vercel-labs/agent-skills | Component composition and API design | |
| `web-design-guidelines` | vercel-labs/agent-skills | UI, UX and accessibility review checklist | |

## eng-lead — running the engineering org

| Item | From | Why |
|---|---|---|
| `eng-leadership` plugin: `design-review`, `interview-kit` | agent-kit | Senior-level RFC/design critique with prioritized findings; structured interview loops with rubrics (hiring is a core mandate) |
| `document-skills` plugin: `docx`, `pdf`, `pptx`, `xlsx` | anthropics/skills | Read, edit and create the Office/PDF files leadership work runs on (offer letters, board decks, headcount models) |
| `doc-coauthoring` | anthropics/skills | Structured co-writing of proposals, specs and decision docs |
| `internal-comms` | anthropics/skills | Status reports, leadership updates, incident comms, FAQs |
| `writing-guidelines` | vercel-labs/agent-skills | Clear, concise writing rules for docs and announcements |

Optional (commented in the profile): OpenAI's `linear` and `notion` plugins if you use those
tools — they need account auth.

## knowledge — Obsidian and note work

| Item | From | Why |
|---|---|---|
| `obsidian` plugin: `obsidian-markdown`, `obsidian-bases`, `json-canvas`, `obsidian-cli`, `knap`, `defuddle` | kepano/obsidian-skills (Steph Ango, Obsidian) | Agents write proper Obsidian flavored Markdown (wikilinks, callouts, properties), Bases and Canvas files, and can drive the Obsidian CLI; `defuddle` extracts clean article text for capture |
| `doc-coauthoring` | anthropics/skills | Long-form drafting |

Considered and left out: `pi-skills/youtube-transcript` needs `npm install` inside its folder,
which agentfiles deliberately keeps immutable and hash-checked (see ROADMAP R4).

## example-webapp — project profile

`builder` minus `mcp-builder`, limited to Claude Code, Codex and Cursor, plus the Playwright
MCP server. Copy it per project, or use [examples/project.agentfiles.yaml](../examples/project.agentfiles.yaml)
inside the repo itself.

## Not included, but worth a look

| Source | What | Why not by default |
|---|---|---|
| `openai-plugins` | 60+ integrations (GitHub, Linear, Figma, Sentry, Stripe, Supabase, Vercel...) | Each needs an account and auth; add the ones you use |
| `anthropics/skills` | `canvas-design`, `algorithmic-art`, `theme-factory`, `slack-gif-creator` | Creative/visual; add to a personal profile if useful |
| `anthropic-claude-code` | `commit-commands`, `code-review`, `hookify`, `plugin-dev` | Overlap with `commit-message`/`pr-review-toolkit`; `plugin-dev` is useful while building agent-kit plugins |
| `pi-skills` | `browser-tools`, `brave-search`, Google CLIs | Need API keys or global npm installs; pi-centric |
