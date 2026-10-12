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
| wanting obra/superpowers' workflow instead of beau-mode | `superpowers` (instead of `builder`) |

Profiles combine freely: `agentfiles sync builder eng-lead`.

### Context cost

Every installed skill adds its name and description to each session; the body loads only
when used. Measured with `claude plugin details` in Claude Code:

| Profile | Claude Code plugins | Always-on cost (approx.) |
|---|---|---|
| base | 3 | ~400 tokens |
| knowledge | 4 | ~1,200 tokens |
| eng-lead | 5 | ~2,000 tokens |
| builder | 9 | ~7,100 tokens (estimated with bstack 0.2.0) |
| beau | 13 | ~9,300 tokens (estimated with bstack 0.2.0) |

The base, knowledge and eng-lead counts predate gdp-ts, promo, claude-api, podcast-studio and
fast-jev-compaction; re-measure after syncing. bstack 0.2.0 and principles together add about 2,100
tokens (19 skill descriptions plus the instruction block; 0.1.0 was about 1,300); dropping Superpowers from builder saved about 850. If `beau` feels heavy, sync personas per project instead of everything globally:
`base` globally, `builder` via `.agentfiles.yaml` in code repos.

### Setup checklist

Items that need more than `agentfiles sync`. Each declares this in its profile with
`requires:`, and `sync`/`plan` print a **Manual setup** section listing what is still missing.

| Item | Profiles | Install | Configure |
|---|---|---|---|
| `podcast-studio` | base | Python 3.9+, `ffmpeg` (`brew install ffmpeg`) | `GEMINI_API_KEY` ([free key](https://aistudio.google.com/apikey)) in your env or `podcast/.env.local` |
| `promo` | builder, eng-lead, knowledge | Node.js, `ffmpeg`; the agent may add rendering tools per video | `OPENROUTER_API_KEY` in your env or the project's `.env` (about $0.50 to $1.50 per video), or local TTS |
| `fast-jev-compaction` | beau | nothing | `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` and `TYPESAFE_API_KEY` in your shell profile (the key can go in the plugin's `apiKey` option instead) |
| `webapp-testing` | builder | Python Playwright in the project | nothing |

---

## base — every machine

| Item | From | Why |
|---|---|---|
| `essentials` plugin: `commit-message`, `handoff-notes` | agent-kit | Commit messages from the staged diff; hand work between sessions and tools (Claude Code ⇄ Codex ⇄ pi) without re-explaining |
| `research-tools` plugin: `library-docs` + Context7 MCP | agent-kit | Version-correct library docs instead of memory. `allow: [mcp]` because it ships a (remote, read-only) MCP server |
| `skill-creator` | anthropics/skills | The fastest way to grow this setup: turn a repeated workflow into a skill, then publish it in agent-kit |
| `claude-api` | anthropics/skills | Claude API/SDK reference, and the eval guides in `shared/evals/` (build an eval, audit one, hill-climb quality or cost against it). The eval guides are part of this skill, not a skill on their own. Claude Code also has a built-in `claude-api`; this copy keeps the same version in every tool |
| `podcast-studio` plugin: `podcast-setup`, `make-podcast` | benogren/podcast-studio | Turn notes, articles, PDFs or transcripts into a multi-host podcast MP3. Needs Python 3.9+, `ffmpeg` and a `GEMINI_API_KEY`. `podcast-setup` copies `../../template/` from the plugin folder, so it is most reliable in Claude Code (native plugin) |

## builder — shipping code

| Item | From | Why | Notes |
|---|---|---|---|
| **bstack** plugin: `beau-mode` + 13 playbooks; `how`, `why`, `teach`, `recall`; `verify-work`, `create-verification-skill`, `maintain-verification-skill`, `swarm`; `architect`, `arena`, `technical-writing`; `interrogate`, `show-me-your-work`, `figure-it-out`, `reflect`, `correct`, `unslop`; `beau-agent` | agent-kit | The way of working: each non-trivial task gets a playbook, named principles, proof on the real artifact, and a decision trail for unattended runs. Each app repo gets its own verification skill. Adapted from Lauren Tan's pstack to work in every tool | `mode: beau-mode` makes it always on. About 2,000 always-on tokens in Claude Code. Guide: agent-kit `docs/BSTACK.md` |
| **principles** plugin | agent-kit | 24 named rules ("prove it works", "subtract before you add", ...) that beau-mode cites and you can steer with by name | One skill, about 120 always-on tokens |
| Model roles | this profile | `code`, `judgment`, `explorer` and `reviewers` per tool, written to `~/.agents/roles.yaml` (projects that differ get `.agents/roles.yaml`, which skills read first) | Cursor model ids come from pstack's defaults; confirm yours (HUMAN_TASKS H10) |
| `pr-review-toolkit` plugin | anthropics/claude-code | Six specialized review agents: general code review, tests, silent failures, type design, comments, simplification | Claude Code only (agents + commands) |
| `feature-dev` plugin | anthropics/claude-code | `/feature-dev`: explore → clarify → architect → implement → review, with dedicated agents | Claude Code only |
| `security-guidance` plugin | anthropics/claude-code | Regex warnings on risky edits, an LLM review of the diff at turn end, agentic review on `git commit` | `allow: [hooks]`; extra model calls (cost/latency); installs the Agent SDK on first session. Claude Code only. Drop it if the cost isn't worth it |
| `webapp-testing` | anthropics/skills | Verify UI changes by driving the app with Playwright | Needs Python Playwright in the project |
| `mcp-builder` | anthropics/skills | Building MCP servers well (relevant to agent-kit R7) | |
| `frontend-design` | anthropics/skills | Distinctive UI instead of generic templates | |
| `vercel-react-best-practices` | vercel-labs/agent-skills | React/Next.js performance rules | Installs under its frontmatter name |
| `vercel-composition-patterns` | vercel-labs/agent-skills | Component composition and API design | |
| `web-design-guidelines` | vercel-labs/agent-skills | UI, UX and accessibility review checklist | |
| `gdp-ts` | rauchg/gdp-ts | Authorization and other preconditions as compile-time proofs in TypeScript ("Ghosts of Departed Proofs") | Only triggers in codebases that use, or are adopting, the `gdp-ts` library |
| `promo` | h14h/explainers | Narrated explainer videos rendered from a generated JS animation to MP4 | In all three personas. Needs `OPENROUTER_API_KEY` (about $0.50 to $1.50 per video) or local TTS; the agent may install rendering tools |

Superpowers used to be in `builder`. It is now the `superpowers` add-on profile: it and
beau-mode are both routers (Superpowers' SessionStart hook makes the agent check its skills
before every response), and running both makes agents follow two competing processes. Pick one.

## eng-lead — running the engineering org

| Item | From | Why |
|---|---|---|
| `eng-leadership` plugin: `design-review`, `interview-kit` | agent-kit | Senior-level RFC/design critique with prioritized findings; structured interview loops with rubrics (hiring is a core mandate) |
| `document-skills` plugin: `docx`, `pdf`, `pptx`, `xlsx` | anthropics/skills | Read, edit and create the Office/PDF files leadership work runs on (offer letters, board decks, headcount models) |
| `doc-coauthoring` | anthropics/skills | Structured co-writing of proposals, specs and decision docs |
| `internal-comms` | anthropics/skills | Status reports, leadership updates, incident comms, FAQs |
| `writing-guidelines` | vercel-labs/agent-skills | Clear, concise writing rules for docs and announcements |
| `promo` | h14h/explainers | Explainer videos for launches, onboarding and all-hands (see builder) |

Optional (commented in the profile): OpenAI's `linear` and `notion` plugins if you use those
tools — they need account auth.

## knowledge — Obsidian and note work

| Item | From | Why |
|---|---|---|
| `obsidian` plugin: `obsidian-markdown`, `obsidian-bases`, `json-canvas`, `obsidian-cli`, `knap`, `defuddle` | kepano/obsidian-skills (Steph Ango, Obsidian) | Agents write proper Obsidian flavored Markdown (wikilinks, callouts, properties), Bases and Canvas files, and can drive the Obsidian CLI; `defuddle` extracts clean article text for capture |
| `doc-coauthoring` | anthropics/skills | Long-form drafting |
| `promo` | h14h/explainers | Turn a topic you are researching into an explainer video (see builder) |

Considered and left out: `pi-skills/youtube-transcript` needs `npm install` inside its folder,
which agentfiles deliberately keeps immutable and hash-checked (see ROADMAP R4).

## beau — your laptop

`builder` + `eng-lead` + `knowledge`, plus:

| Item | From | Why | Notes |
|---|---|---|---|
| `fast-jev-compaction` plugin | tamaratran/fast-jev-compaction | Replaces Claude Code's lossy compaction summary: TypeSafe's Jev model scores every tool call and result, stale ones are dropped or truncated, and everything kept stays verbatim | Claude Code only. `allow: [hooks]` (an early-access function-hook module). Needs `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` and `TYPESAFE_API_KEY`. **Sends the session transcript to TypeSafe** on each compaction, which is why it is in `beau` and not `base` |

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
