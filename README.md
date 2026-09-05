# Fable Advisor (Fable-architect fork)

**Fable runs the show. By default Codex does the typing and Claude Opus reviews everything before it ships.**

> Experimental fork of [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor) (v4). The upstream pattern puts Opus in the architect seat to save tokens; this fork spends the premium on the architect instead — Fable owns every judgment call — while keeping the cross-vendor check where upstream had it, on the implementation side.

Claude Code lets every subagent run on a different model — and lets the session itself run on a different model than its subagents. This fork exploits that with the **architect pattern**: your session runs on **Fable 5**, acting as a full-time architect. It owns requirements, decomposition, specs, and verification — delegates the typing to an implementation lane — and gets a **fresh-eyes review** of the finished work before calling anything done. This fixed arrangement uses cross-vendor GPT-5.6 Luna typing (with GPT-6 Astra as a one-off escalation lane for judgment-heavy work) and a native Claude Opus review:

| Agent | Producer | Role | Lane |
|---|---|---|---|
| `codex-implementer` | **GPT-5.6 Luna** (max reasoning) | Implementation — drives codex to write the code from the architect's six-part spec | Standing implementation lane |
| `astra-implementer` | **GPT-6 Astra** (effort named per task, up to `ultra`) | Implementation — high-complexity one-offs where judgment the spec can't capture decides the outcome | Escalation lane, never the default |
| `opus-implementer` | **Claude Opus** (high effort) | Implementation — writes the code itself | Optional race lane for high-stakes specs |
| `opus-reviewer` | **Claude Opus** (high effort) | Reviewer + outside voice — consults at commitment boundaries (proceed / revise / rethink) and the mandatory end-of-deliverable review (ship / fix-first / rethink), judged natively — no CLI, no relay | Standing reviewer + outside voice |

The architect names Astra's effort per task with a `REASONING:` line in the spec; Luna (`codex-implementer`) stays pinned at max.

The architect does not report done before the review gate returns a verdict. Tokens route by capability: Fable emits judgment and specs (volume-light, the priciest seat kept lean), the implementation lane emits the bulk of the code, and the cross-vendor seat is always the implementation lane — GPT writes, Claude judges. The architect and reviewer are both Claude, so the implementation lane being a *different model family* is what keeps the system honest — every diff crosses a vendor line before it can ship, and same-family blind spots never get to write the code unchallenged. A judgment-heavy one-off can also escalate to `astra-implementer`, GPT-6 Astra at the effort named per task, before it ever fails once — the architect routes it there when the spec can't fully capture what decides the outcome. When a task fails its spec twice in whichever lane it ran, the architect — the strongest implementer in the system — takes it over personally, and that diff still goes through the review.

The plugin ships the **orchestration skill** — the routing doctrine, the cost discipline that keeps the Fable seat volume-light (emit judgment not volume, keep context lean, reason once then hand off), the six-part spec contract that makes context-free delegation safe, and the verification rules that keep every lane honest.

## Turning it off

Set the pattern off in either of two ways:

- **In session** — say "solo mode", "不用车道", or "关闭 architect 模式". It takes effect immediately for that scope.
- **Persistent** — put this line in the project's or the user's `CLAUDE.md`:

```
fable-advisor lane profile: off
```

`off` is the only value that line recognises. While it is active, the session reads, implements, and verifies directly, with no lane delegation, no mandatory consult, and no mandatory review gate. The four lane agents run only when you ask for one by name, which does not turn the pattern back on. Your session says so once at its first implementation step ("architect mode off: implementing directly"). In-session beats the `CLAUDE.md` line; a project's line beats your user-level one. To turn the pattern back on in-session, say "architect mode on", "use lanes", or "开启 architect 模式".

## Install

```
claude plugin marketplace add haorui/fable-advisor
claude plugin install fable-advisor@fable-advisor
```

Then start your session as the architect:

```
/model fable
```

## Requirements

- **Claude Code ≥ 2.1.170** with a subscription that includes Fable 5 (Pro, Max, Team, or Enterprise — all current consumer plans qualify), since the session itself runs on Fable.
- **Codex lane:** the [OpenAI Codex CLI](https://github.com/openai/codex) installed and authenticated (`npm i -g @openai/codex`, then `codex login`) — required for both codex-driven lanes: the standing implementation lane (`codex-implementer`, **GPT-5.6 Luna** as `gpt-5.6-luna` with `model_reasoning_effort=max`) and the high-complexity escalation lane (`astra-implementer`, **GPT-6 Astra** as `gpt-6-astra` with effort set by the architect's `REASONING:` line). A high-stakes race also needs the CLI because it includes the standing lane. Without an installed, authenticated CLI or model access, the codex agent reports `STATUS: unavailable` — it never silently falls back to a Claude model. That stops the work at the implementation lane.
- **Optional Codex plugin:** the [Codex plugin for Claude Code](https://github.com/openai/codex-plugin-cc) (`/plugin marketplace add openai/codex-plugin-cc`, then `/plugin install codex@openai-codex`). When enabled, the orchestration skill uses `/codex:adversarial-review` as a cross-vendor pre-check before the `opus-reviewer` gate on sensitive deliverables (security-sensitive paths, migrations, API shapes), with `/codex:rescue` available for manual user-driven delegation.
- Heads-up: if a pinned Claude model isn't available on your account, Claude Code silently falls back to your session model. If `model: opus` in `opus-reviewer` quietly becomes Fable, the review gate becomes the architect's own model judging its own deliverable — the self-review the doctrine forbids, arriving as a clean verdict with nothing to signal it. In `opus-implementer`, the same fallback makes the optional race lane *more* expensive than intended; if costs feel off, check your plan. (This quiet fallback applies only to Claude model pins — the codex lane always fails loudly with a structured error.)

Model resolution order in Claude Code: `CLAUDE_CODE_SUBAGENT_MODEL` env var → per-invocation `model` parameter → agent frontmatter → session model.
Effort resolution: `CLAUDE_CODE_EFFORT_LEVEL` env var → agent frontmatter `effort` → session `/effort`.
The Claude agents (`opus-implementer` and `opus-reviewer`) set `effort: high` in their frontmatter; neither codex agent has a frontmatter effort field — `codex-implementer` pins GPT-5.6 Luna to max, while `astra-implementer` passes through the effort named in the spec's `REASONING:` line.

## Use it

With the session on Fable, just ask for work — the orchestration skill routes it:

```
Add rate limiting to our public API. Design it, delegate the
implementation, and verify the evidence before you call it done.
```

The architect writes the spec, delegates to `codex-implementer` (escalating to `astra-implementer` for judgment-heavy one-offs, or racing the routed lane against `opus-implementer` on a high-stakes spec), reads the diff and verification evidence when the report comes back, sends the finished work through `opus-reviewer` for the final review, and only then reports done.

To make the doctrine always-on, add one line to your project's `CLAUDE.md`:

```
You are the architect — minimize your own token volume. Delegate all
implementation through the orchestration skill's routing table (never
type code yourself, except the documented two-failures takeover),
delegate broad codebase exploration to cheap read-only agents, consult
`opus-reviewer` at commitment boundaries, verify
evidence before accepting any lane's report, and get `opus-reviewer`'s
verdict before reporting any deliverable done.
```

## The final review

Every deliverable ends at `opus-reviewer`, the review gate. Claude Opus reads the accumulated diff itself, with fresh eyes and no accumulated conversational assumptions, against the stated goal rather than the conversation — and returns ship / fix-first / rethink. It runs natively, with no CLI in the path; the cross-vendor check sits at the implementation lane instead, where GPT-5.6 Luna (or GPT-6 Astra on an escalation) writes the code Claude then judges. **The architect never substitutes its own self-review for the gate** — the gate is an agent invocation with a returned verdict, or it did not happen.

`opus-reviewer` has no external dependency, so unavailability is not an expected failure mode; the only non-verdict outcome is `STATUS: insufficient-brief`, and the architect supplies what's missing and re-invokes.

`opus-reviewer` doubles as the **outside voice** before anything is committed. At commitment boundaries — architecture choices, migrations, API shapes, refactor strategies, or a problem that has resisted two attempts — the architect writes a short decision memo (decision, options, deciding risk) and sends it to `opus-reviewer` in CONSULT mode for a proceed / revise / rethink verdict. The decision stays with the Fable architect — there is no stronger Claude to escalate to — but it is never made unexamined.

## FAQ

**Why put the most expensive model in the architect seat?** Because the architect seat is where judgment concentrates: decomposition, interface design, debugging hypotheses, and verdicts on evidence. This fork bets that better judgment there beats cheaper tokens there — while the cost discipline (delegate the volume, keep the context lean) keeps the Fable seat from ever carrying the token bulk. It is still far cheaper than running a single Fable session that does its own typing.

**Why is the implementation lane a GPT model?** Vendor diversity, concentrated where the code gets written. Fable architects and Opus judges — both Anthropic — so the producer is deliberately the other family, and every diff crosses a vendor line before it can ship. That is the upstream shape, and the honest trade is stated plainly: the code now rides on GPT-5.6 Luna (GPT-6 Astra for judgment-heavy escalations), while the gate *and* the commitment-boundary consults stay inside Anthropic, judged by the architect's own vendor.

**What happened to fable-implementer and fable-advisor?** Both collapsed into the architect. The session *is* Fable now, so a Fable escalation lane and a Fable advisor would be the same model reviewing itself at extra hand-off cost. Hard tasks that defeat the implementation lane twice go to the architect directly; fresh-eyes review goes to `opus-reviewer`.

**Upstream versions?** This fork's lineage: upstream v4 (Opus architect, Codex routine lane, Fable escalation + review) → v5 (Fable architect, Codex implementation lane, native Opus review, keeping v4's producing pair with the architect seat upgraded) → v6 (one fixed arrangement — codex implements, opus reviews; profiles removed) → v6.1 (adds `sol-implementer`, a GPT-5.6 Sol escalation lane for judgment-heavy one-offs) → this v6.2 (swaps the escalation lane to `astra-implementer`, GPT-6 Astra, same six effort rungs). For the original pattern, use [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor).

## License

MIT
