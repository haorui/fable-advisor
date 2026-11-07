# Fable Advisor

**Your session runs on whichever model you choose (often Claude Opus 5.5). GPT-6.1 Sol handles substantial implementation through Codex, the architect makes small, local changes directly, Claude Sonnet takes over only when Sol is unavailable, and every deliverable is reviewed in a clean context: by Claude Opus for routine lane work, and by Fable 5.1 for consults, the architect's own changes, and high-risk work.**

> Experimental fork of [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor). This fork keeps the architect model open: the session owns requirements, decomposition, specs, routing, and verification, while specialized lanes implement and review the work.

Claude Code lets each subagent run on a different model from the session. This plugin uses that to route substantial implementation through GPT-6.1 Sol via Codex, with Claude Sonnet as the fallback when Sol is unavailable and a Claude reviewer in a clean context before anything is called done:

| Agent | Producer | Role | Lane |
|---|---|---|---|
| `sol-implementer` | **GPT-6.1 Sol** (`gpt-6.1-sol`, `medium` baseline) | Delegated implementation; the architect names the effort per task in the required `REASONING:` line; requires the Codex CLI | Default/standing implementation lane |
| `sonnet-implementer` | **Claude Sonnet** (high effort) | Writes the code itself; no external dependency | Fallback only when Sol is unavailable |
| `fable-advisor` | **Claude Opus** by default; **Fable 5.1** (`model: "fable"`) for consults, architect-written changes, and high-risk work (high effort) | Outside voice and reviewer; REVIEW returns ship / fix-first / rethink, CONSULT returns proceed / revise / rethink | Commitment boundaries and final review; no CLI or relay; Opus stands in when Fable is unavailable |

Sol uses the architect's `medium` baseline and requires the architect to name its effort explicitly for each delegated task, including mechanical and routine work. Small, local changes (a few lines, doc or config edits, small follow-up fixes) the architect makes directly, because there the handoff costs more than the work; they still go through the final review. Escalation raises Sol's `REASONING:` one or more rungs. Sonnet is the fallback only after Sol reports `STATUS: unavailable`; the architect makes that routing decision.

Routing implementation to GPT-6.1 Sol reflects the author's preference. It is not a claim that a second vendor makes the code more accurate, and published comparisons don't show that it does. Under the Sonnet fallback, Claude both writes and reviews. The session model remains the user's choice. The reviewer always reads in a clean context. When it is a different model from the author, the review is also an independent-model check. That is true of lane work, and of the architect's own changes, which go to Fable. When the reviewer is the same model as the author, the review is a fresh-eyes check rather than an independent-model check. That happens with a Fable architect, or when Opus stands in for an unavailable Fable on an Opus architect's work. The architect does not report done before the final review returns a verdict.

The plugin ships the **orchestration skill** — routing guidance, model labels for each delegation, the six-part spec contract, the two-failures takeover, and verification rules that keep each lane honest.

## Turning it off

Set the pattern off in either of two ways:

- **In session** — say "solo mode", "不用车道", or "关闭 architect 模式". It takes effect immediately for that scope.
- **Persistent** — put this line in the project's or the user's `CLAUDE.md`:

```
fable-advisor lane profile: off
```

`off` is the only value that line recognises. While it is active, the session reads, implements, and verifies directly, with no lane delegation, no mandatory consult, and no mandatory review gate. The three lane agents run only when you ask for one by name, which does not turn the pattern back on. Your session says so once at its first implementation step ("architect mode off: implementing directly"). In-session beats the `CLAUDE.md` line; a project's line beats your user-level one. To turn the pattern back on in-session, say "architect mode on", "use lanes", or "开启 architect 模式".

## Install

```
claude plugin marketplace add haorui/fable-advisor
claude plugin install fable-advisor@fable-advisor
```

Choose whichever model you want for the architect session. Claude Opus 5.5 is a typical choice; this plugin does not select the session model for you. The advisor runs on Claude Opus by default. The architect routes consults, its own changes, and high-risk work to Fable 5.1.

## Requirements

- **Claude Code ≥ 2.1.170** and an account with access to Claude Opus, `fable-advisor`'s default model, and ideally Fable 5.1 (the `fable` alias) for the reviews routed to it. Without Fable, Opus stands in. The session itself can use any model.
- **Sol implementation:** the [OpenAI Codex CLI](https://github.com/openai/codex) installed and authenticated (`npm i -g @openai/codex`, then `codex login`). `sol-implementer` runs **GPT-6.1 Sol** (`gpt-6.1-sol`) with `medium` as the architect's baseline and effort named for each task in its required `REASONING:` line. It reports `STATUS: unavailable` if the CLI or model access is unavailable and never silently substitutes itself. Without Codex, the architect falls back to `sonnet-implementer`, which has no external dependency. Unsupported effort is a spec defect to fix, not a fallback trigger.
- **Optional Codex plugin:** the [Codex plugin for Claude Code](https://github.com/openai/codex-plugin-cc) (`/plugin marketplace add openai/codex-plugin-cc`, then `/plugin install codex@openai-codex`). When enabled, the orchestration skill can use `/codex:adversarial-review` before the `fable-advisor` gate on sensitive deliverables and `/codex:rescue` for user-driven delegation. It is optional; `sol-implementer` calls `codex exec` directly.
- **Heads-up:** if the model requested for `fable-advisor` is unavailable, or is overridden by `CLAUDE_CODE_SUBAGENT_MODEL`, Claude Code silently falls back to the session model. The call can also error outright, e.g. on a Fable usage limit (HTTP 429). To make a silent fallback visible, `fable-advisor` reports the model it actually ran on in a `MODEL:` line. When Fable was requested, an Opus verdict stands and is marked `(Fable requested, unavailable)`. On an error, the architect re-invokes with `model: "opus"`. Any model other than Fable or Opus is surfaced to you instead of accepted. `sol-implementer` fails loudly with a structured error instead of falling back.

Model resolution order in Claude Code: `CLAUDE_CODE_SUBAGENT_MODEL` env var → per-invocation `model` parameter → agent frontmatter → session model. **If `CLAUDE_CODE_SUBAGENT_MODEL` is set, it overrides both the advisor's frontmatter and the `model: "fable"` parameter, so your review silently runs on another model.** Check the `env` block of `~/.claude/settings.json` too. Effort resolution: `CLAUDE_CODE_EFFORT_LEVEL` env var → agent frontmatter `effort` → session `/effort`. `fable-advisor` and `sonnet-implementer` set `effort: high`; Sol passes the effort from the required `REASONING:` line.

## Use it

With the plugin installed, ask for work in the usual way — the orchestration skill routes it:

```
Add rate limiting to our public API. Design it, delegate the
implementation, and verify the evidence before you call it done.
```

The architect writes the spec, labels and announces the routing decision, sends substantial implementation to `sol-implementer` with effort named in `REASONING:`, and makes small, local changes directly. Escalation raises that effort; only Sol's unavailability triggers the `sonnet-implementer` fallback for the rest of the session. The architect reads the diff and verification evidence, accepts the working tree (lanes never commit), sends the finished work through `fable-advisor`, and reports done only after a verdict.

To make the doctrine always-on, add one line to your project's `CLAUDE.md`:

```
You are the architect. Delegate substantial implementation through the
orchestration skill's routing table and make small, local changes
directly, as its "Delegate or implement directly" section defines;
label each delegation with its model, delegate broad codebase exploration
to read-only agents, consult `fable-advisor` at commitment boundaries,
verify evidence before accepting any lane's report, and get
`fable-advisor`'s verdict before reporting any deliverable done.
```

## The final review

Every deliverable ends at `fable-advisor`, the review gate. It runs on Claude Opus for routine lane work. It runs on Fable 5.1 for the architect's own changes, for security-sensitive, migration, API-contract, or concurrency work, and for anything high-value or complex. It reads the accumulated diff in a clean context, and returns ship / fix-first / rethink. The tier depends on who wrote the change. FULL, with held-back cases the implementer never saw, applies to anything with lane-written code and to risky direct changes. LIGHT, a single pass at medium effort that still re-runs verification, applies only when the deliverable consists entirely of the architect's own small direct changes. It also serves as the outside voice at commitment boundaries through CONSULT mode (proceed / revise / rethink). It has no CLI or relay to fail; if Fable 5.1 is unavailable, Claude Opus stands in, and the advisor's `MODEL:` line says so. Each brief names the author and the routed model, so a misrouted review comes back asking for Fable instead of ruling.

## FAQ

**Why keep the session model open?** The architect's job is to make requirements, routing, and verification decisions. Choose the model that fits your work; Opus 5.5 is a typical choice for this fork. Fable 5.1 remains available as a clean-context advisor and reviewer.

**Why is the implementation lane a GPT model?** Personal preference. It was first chosen in the expectation that code written by a second vendor would be more accurate. Published comparisons and this plugin's own usage didn't bear that out, so it stays as a preference, not an accuracy argument. The review's value comes from what doesn't depend on who wrote the code: a clean-context reviewer, re-run verification, and held-back cases. Sonnet is the availability fallback.

**Why not Fable for every review?** Fable 5.1 is Claude's most capable model and the scarcest. Routine lane code is written by GPT-6.1 Sol, so an Opus reviewer is already a second model reading in a clean context. Fable is kept for the reviews where it matters most. Consults shape everything downstream. The architect's own changes would otherwise be Opus reviewing Opus. High-risk work is where a missed defect costs the most.

**Upstream versions?** This fork's lineage: upstream v4 (Opus architect, Codex routine lane, Fable escalation + review) → v5 (Fable architect, Codex implementation lane, native Claude final review) → v6 (one fixed arrangement, Codex implements and Claude reviews; profiles removed) → v6.1 (adds a Sol escalation lane) → v6.2 (updates the escalation model) → v6.3 (`medium` escalation baseline and a separate routing rule) → v7.0.0: rename the routine Codex lane, high-complexity Codex lane, and earlier Claude review agent to `luna-implementer`, `sol-implementer`, and `fable-advisor` on GPT-6 Luna, GPT-6 Sol, and Fable 5.1, and stop assuming the architect runs on Fable → v8.0.0 (remove `luna-implementer`; `sol-implementer` becomes the default lane with effort-rung escalation; `opus-implementer` becomes `sonnet-implementer`, a fallback used only when Sol is unavailable; parallel same-spec lanes removed) → v8.1.0 (with an Opus-led session the norm, architect token volume no longer decides routing; the architect makes small, local changes directly and delegates substantial work). For the original pattern, see [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor).

## License

MIT
