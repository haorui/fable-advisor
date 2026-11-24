# Fable Advisor

**Your session runs on whichever model you choose (often Claude Opus 5.5). Claude Sonnet handles substantial implementation, the architect makes small, local changes directly, GPT-6.2 Astra is the outside voice at commitment boundaries (with Fable standing in when Astra is unavailable), and every deliverable is reviewed in a clean context: by Claude Opus for routine work, and by Fable for takeovers and hard or high-risk work.**

> Experimental fork of [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor). This fork keeps the architect model open: the session owns requirements, decomposition, specs, routing, and verification, while specialized lanes implement, advise, and review.

Claude Code lets each subagent run on a different model from the session. This plugin uses that to route substantial implementation to Claude Sonnet, send decisions to a GPT model for a second opinion before they are committed, and put a Claude reviewer in a clean context before anything is called done:

| Agent | Producer | Role | Lane |
|---|---|---|---|
| `sonnet-implementer` | **Claude Sonnet** (high effort) | Writes delegated implementation code itself from the six-part spec; no external dependency | Implementation lane |
| `astra-advisor` | **GPT-6.2 Astra** (`gpt-6.2-astra` via the Codex CLI, read-only sandbox, `high` effort by default) | Outside voice; CONSULT returns proceed / revise / rethink | Commitment boundaries; requires the Codex CLI; Fable stands in when it is unavailable |
| `fable-advisor` | **Claude Opus** by default; **Fable** (`model: "fable"`) for takeovers, hard or high-risk work, and fallback consults (medium effort by default, high when the architect raises it) | Review gate; REVIEW returns ship / fix-first / rethink | Final review of every deliverable; no CLI or relay; Opus stands in when Fable is unavailable |

Small, local changes (a few lines, doc or config edits, small follow-up fixes) the architect makes directly, because there the handoff costs more than the work; they still go through the final review. A task that fails its spec twice is taken over by the architect.

Routing the outside voice to a GPT model reflects the author's preference, not a claim that a second vendor makes decisions more accurate. The review gate stays on Claude: it runs the held-back cases, reads the diff and re-runs verification itself, and has no relay that could distort its verdict. The reviewer always reads in a clean context. Lane code is written by Sonnet and reviewed by Opus or Fable, so lane reviews are independent-model checks. When the reviewer is the same model as the author, the review is a fresh-eyes check rather than an independent-model check. That happens on Opus reviews of an Opus architect's routine direct changes, on Fable reviews of a Fable architect's own work, and when Opus stands in for an unavailable Fable on an Opus architect's work. The architect does not report done before the final review returns a verdict.

The plugin ships the **orchestration skill** — routing guidance, model labels for each delegation, the six-part spec contract, the two-failures takeover, and verification rules that keep each lane honest.

## Turning it off

Set the pattern off in either of two ways:

- **In session** — say "solo mode", "不用车道", or "关闭 architect 模式". It takes effect immediately for that scope.
- **Persistent** — put this line in the project's or the user's `CLAUDE.md`:

```
fable-advisor lane profile: off
```

`off` is the only value that line recognises. While it is active, the session reads, implements, and verifies directly, with no lane delegation, no mandatory consult, and no mandatory review gate. The three agents run only when you ask for one by name, which does not turn the pattern back on. Your session says so once at its first implementation step ("architect mode off: implementing directly"). In-session beats the `CLAUDE.md` line; a project's line beats your user-level one. To turn the pattern back on in-session, say "architect mode on", "use lanes", or "开启 architect 模式".

## Install

```
claude plugin marketplace add haorui/fable-advisor
claude plugin install fable-advisor@fable-advisor
```

Choose whichever model you want for the architect session. Claude Opus 5.5 is a typical choice; this plugin does not select the session model for you. The reviewer runs on Claude Opus by default. The architect routes takeovers and hard or high-risk work to Fable, and consults to GPT-6.2 Astra.

## Requirements

- **Claude Code ≥ 2.1.170** and an account with access to Claude Sonnet, Claude Opus (`fable-advisor`'s default model), and ideally Fable (the `fable` alias) for the reviews and fallback consults routed to it. Without Fable, Opus stands in. The session itself can use any model.
- **Astra outside voice:** the [OpenAI Codex CLI](https://github.com/openai/codex) installed and authenticated (`npm i -g @openai/codex`, then `codex login`), with access to `gpt-6.2-astra`. `astra-advisor` runs it in a read-only sandbox, reports `STATUS: unavailable` if the CLI or model access is missing, and never substitutes its own opinion. Without Codex, the architect sends consults to `fable-advisor` on Fable; implementation and review do not need Codex at all.
- **Optional Codex plugin:** the [Codex plugin for Claude Code](https://github.com/openai/codex-plugin-cc) (`/plugin marketplace add openai/codex-plugin-cc`, then `/plugin install codex@openai-codex`). When enabled, the orchestration skill can use `/codex:adversarial-review` before the `fable-advisor` gate on sensitive deliverables and `/codex:rescue` for user-driven delegation. It is optional; `astra-advisor` calls `codex exec` directly.
- **Heads-up:** if the model requested for `fable-advisor` is unavailable, or is overridden by `CLAUDE_CODE_SUBAGENT_MODEL`, Claude Code silently falls back to the session model. The call can also error outright, e.g. on a Fable usage limit (HTTP 429). To make a silent fallback visible, `fable-advisor` reports the model it actually ran on in a `MODEL:` line. When Fable was requested, an Opus verdict stands and is marked `(Fable requested, unavailable)`. On an error, the architect re-invokes with `model: "opus"`. Any model other than Fable or Opus is surfaced to you instead of accepted. `astra-advisor` fails loudly with a structured error instead of falling back.

Model resolution order in Claude Code: `CLAUDE_CODE_SUBAGENT_MODEL` env var → per-invocation `model` parameter → agent frontmatter → session model. **If `CLAUDE_CODE_SUBAGENT_MODEL` is set, it overrides both the advisor's frontmatter and the `model: "fable"` parameter, so your review silently runs on another model.** Check the `env` block of `~/.claude/settings.json` too. Effort resolution: `CLAUDE_CODE_EFFORT_LEVEL` env var → agent frontmatter `effort` → session `/effort`; a per-invocation `effort` parameter overrides the frontmatter. `fable-advisor` sets `effort: medium` (the architect passes `effort: "high"` per call when the risk warrants it) and `sonnet-implementer` sets `effort: high`; Astra takes its effort from the memo's optional `EFFORT:` line, `high` by default.

## Use it

With the plugin installed, ask for work in the usual way — the orchestration skill routes it:

```
Add rate limiting to our public API. Design it, delegate the
implementation, and verify the evidence before you call it done.
```

The architect states the design decision and consults `astra-advisor` before committing to it, writes the spec, labels and announces the routing decision, sends substantial implementation to `sonnet-implementer`, and makes small, local changes directly. It reads the diff and verification evidence, accepts the working tree (lanes never commit), sends the finished work through `fable-advisor`, and reports done only after a verdict.

To make the doctrine always-on, add one line to your project's `CLAUDE.md`:

```
You are the architect. Delegate substantial implementation through the
orchestration skill's routing table and make small, local changes
directly, as its "Delegate or implement directly" section defines;
label each delegation with its model, delegate broad codebase exploration
to read-only agents, consult `astra-advisor` at commitment boundaries,
verify evidence before accepting any lane's report, and get
`fable-advisor`'s verdict before reporting any deliverable done.
```

## The final review

Every deliverable ends at `fable-advisor`, the review gate. It runs on Claude Opus for routine work. It runs on Fable for two-failures takeovers, for hard security work (designing or changing auth, authorization, crypto, or secret-handling logic; routine changes on those paths stay on Opus), for migration, API-contract, or concurrency work, and for anything high-value or complex. These categories apply whether the lane or the architect wrote the change. It reads the accumulated diff in a clean context, re-runs the verification, and returns ship / fix-first / rethink, at medium effort unless the architect raises it to high. There is one kind of review. Lane-written code also gets held-back cases the implementer never saw; the architect's own changes do not, since cases it withholds from itself measure nothing. When `astra-advisor` is unavailable, `fable-advisor` on Fable also takes the consults (CONSULT mode, proceed / revise / rethink). It has no CLI or relay to fail; if Fable is unavailable, Claude Opus stands in, and the advisor's `MODEL:` line says so. Each brief names the author and the routed model, so a misrouted review comes back asking for Fable instead of ruling.

## FAQ

**Why keep the session model open?** The architect's job is to make requirements, routing, and verification decisions. Choose the model that fits your work; Opus 5.5 is a typical choice for this fork. Fable remains available as a clean-context advisor and reviewer.

**Why Sonnet for implementation?** A native Claude lane writes the code itself: no CLI, no vendor availability to fail, and no wrapper between the spec and the code. The review's value comes from what doesn't depend on who wrote the code: a clean-context reviewer, re-run verification, and held-back cases.

**Why is the outside voice a GPT model, and why not the review gate too?** Personal preference for a second vendor's read on decisions before they are committed; it is not an accuracy claim. A consult only offers an opinion the architect checks, so a relayed verdict is acceptable there. The gate decides what ships, so it stays on the native Claude path with no relay. Fable stands in for Astra when the Codex CLI is unavailable.

**Why not Fable for every review?** Fable is Claude's most capable model and the scarcest. Routine lane code is written by Sonnet, so an Opus reviewer is already a second model reading in a clean context. Fable is kept for the reviews where it matters most. An Opus architect's routine direct changes go to Opus and accept a fresh-eyes check instead of a second model. Hard or high-risk work is where a missed defect costs the most. Merely touching a security-sensitive path is not enough, since in a security-heavy codebase that describes nearly every change.

**Upstream versions?** This fork's lineage: upstream v4 (Opus architect, Codex routine lane, Fable escalation + review) → v5 (Fable architect, Codex implementation lane, native Claude final review) → v6 (one fixed arrangement, Codex implements and Claude reviews; profiles removed) → v6.1 (adds a Sol escalation lane) → v6.2 (updates the escalation model) → v6.3 (`medium` escalation baseline and a separate routing rule) → v7.0.0: rename the routine Codex lane, high-complexity Codex lane, and earlier Claude review agent to `luna-implementer`, `sol-implementer`, and `fable-advisor` on GPT-6 Luna, GPT-6 Sol, and Fable 5.1, and stop assuming the architect runs on Fable → v8.0.0 (remove `luna-implementer`; `sol-implementer` becomes the default lane with effort-rung escalation; `opus-implementer` becomes `sonnet-implementer`, a fallback used only when Sol is unavailable; parallel same-spec lanes removed) → v8.1.0 (with an Opus-led session the norm, architect token volume no longer decides routing; the architect makes small, local changes directly and delegates substantial work) → v9.0.0 (remove `sol-implementer`; `sonnet-implementer` becomes the implementation lane; the outside voice moves to `astra-advisor` on GPT-6.2 Astra, with `fable-advisor` on Fable as its fallback; `fable-advisor` keeps the review gate). For the original pattern, see [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor).

## License

MIT
