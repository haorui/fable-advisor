# Fable Advisor

**Your session runs on whichever model you choose (often Claude Opus 5.5). GPT-6 does the typing through Codex, and Fable 5.1 reviews every deliverable.**

> Experimental fork of [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor). This fork keeps the architect model open: the session owns requirements, decomposition, specs, routing, and verification, while specialized lanes implement and review the work.

Claude Code lets each subagent run on a different model from the session. This plugin uses that to route routine and judgment-heavy implementation through Codex, with a Claude reviewer in a clean context before anything is called done:

| Agent | Producer | Role | Lane |
|---|---|---|---|
| `luna-implementer` | **GPT-6 Luna** (`gpt-6-luna`, effort pinned at `max`) | Routine implementation via the Codex CLI | Standing implementation lane |
| `sol-implementer` | **GPT-6 Sol** (`gpt-6-sol`, `medium` baseline) | High-complexity one-offs; the architect names the effort per task in the `REASONING:` line | Escalation lane, never the default |
| `opus-implementer` | **Claude Opus** (high effort) | Writes the code itself | Optional race lane for high-stakes specs |
| `fable-advisor` | **Fable 5.1**, Claude model alias `fable` (high effort) | Outside voice and reviewer; REVIEW returns ship / fix-first / rethink, CONSULT returns proceed / revise / rethink | Commitment boundaries and final review; no external dependency |

Luna stays pinned at `max`; it ignores any `REASONING:` line and has no default-versus-override distinction. Sol uses the architect's `medium` baseline and requires the architect to name its effort explicitly for each task. The optional Opus lane is for high-stakes races against the routed implementation lane.

The cross-vendor perspective sits at implementation — GPT writes, Claude/Fable judges. The session model remains the user's choice. When the architect is not Fable 5.1, the advisor consult and final review are a second model, typically a stronger one reading in a clean context; when the architect is also Fable 5.1, the review is a fresh-eyes check rather than an independent-model check. The architect does not report done before the final review returns a verdict.

The plugin ships the **orchestration skill** — routing guidance, model labels for each delegation, the six-part spec contract, the two-failures takeover, and verification rules that keep each lane honest.

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

Choose whichever model you want for the architect session. Claude Opus 5.5 is a typical choice; this plugin does not select the session model for you. The advisor remains pinned to Fable 5.1.

## Requirements

- **Claude Code ≥ 2.1.170** and an account with access to Fable 5.1 for the `fable` model alias used by `fable-advisor`. The session itself can use any model.
- **Codex lanes:** the [OpenAI Codex CLI](https://github.com/openai/codex) installed and authenticated (`npm i -g @openai/codex`, then `codex login`). `luna-implementer` runs **GPT-6 Luna** (`gpt-6-luna`) at pinned `max` effort; `sol-implementer` runs **GPT-6 Sol** (`gpt-6-sol`) with `medium` as the architect's baseline and effort named for each task in its required `REASONING:` line. Both report `STATUS: unavailable` if the CLI or model access is unavailable; neither silently falls back to Claude. Without Codex, the implementation lanes cannot run.
- **Optional Codex plugin:** the [Codex plugin for Claude Code](https://github.com/openai/codex-plugin-cc) (`/plugin marketplace add openai/codex-plugin-cc`, then `/plugin install codex@openai-codex`). When enabled, the orchestration skill can use `/codex:adversarial-review` before the `fable-advisor` gate on sensitive deliverables and `/codex:rescue` for user-driven delegation. It is optional; the implementation lanes call `codex exec` directly.
- **Heads-up:** if the `fable` pin used by `fable-advisor` is unavailable, or is overridden by `CLAUDE_CODE_SUBAGENT_MODEL`, Claude Code silently falls back to the session model. `fable-advisor` then runs on the architect's own session model, so the review gate becomes the architect's own model judging its own deliverable — the self-review the doctrine forbids — with nothing in the transcript to signal it happened. Codex lanes fail loudly with a structured error instead of falling back.

Model resolution order in Claude Code: `CLAUDE_CODE_SUBAGENT_MODEL` env var → per-invocation `model` parameter → agent frontmatter → session model. **If `CLAUDE_CODE_SUBAGENT_MODEL` is set, it overrides the advisor's `fable` pin, so your Fable review silently runs on another model.** Check the `env` block of `~/.claude/settings.json` too. Effort resolution: `CLAUDE_CODE_EFFORT_LEVEL` env var → agent frontmatter `effort` → session `/effort`. `fable-advisor` and `opus-implementer` set `effort: high`; Luna pins GPT-6 Luna to `max`, while Sol passes the effort from the required `REASONING:` line.

## Use it

With the plugin installed, ask for work in the usual way — the orchestration skill routes it:

```
Add rate limiting to our public API. Design it, delegate the
implementation, and verify the evidence before you call it done.
```

The architect writes the spec, labels and announces the routing decision, and sends routine work to `luna-implementer`. Use `sol-implementer` for high-complexity work and name its effort in `REASONING:`; race the chosen lane against `opus-implementer` for high-stakes specs. The architect reads the diff and verification evidence, accepts the working tree (lanes never commit), sends the finished work through `fable-advisor`, and reports done only after a verdict.

To make the doctrine always-on, add one line to your project's `CLAUDE.md`:

```
You are the architect — minimize your own token volume. Delegate all
implementation through the orchestration skill's routing table (never
type code yourself, except the documented two-failures takeover),
label each delegation with its model, delegate broad codebase exploration
to cheap read-only agents, consult `fable-advisor` at commitment boundaries,
verify evidence before accepting any lane's report, and get
`fable-advisor`'s verdict before reporting any deliverable done.
```

## The final review

Every deliverable ends at `fable-advisor`, the review gate. It runs on Claude model alias `fable` (Fable 5.1), reads the accumulated diff in a clean context, and returns ship / fix-first / rethink. It also serves as the outside voice at commitment boundaries through CONSULT mode (proceed / revise / rethink). It has no external dependency — no CLI, relay, or vendor availability to fail. The architect can use any model, often Opus 5.5; if the architect is already Fable 5.1, the review is fresh eyes rather than an independent-model check.

## FAQ

**Why keep the session model open?** The architect's job is to make requirements, routing, and verification decisions. Choose the model that fits your work; Opus 5.5 is a typical choice for this fork. Fable 5.1 remains available as a clean-context advisor and reviewer.

**Why is the implementation lane a GPT model?** Vendor diversity sits where the code is written. The implementation lanes use a different model family, and Claude/Fable reviews their work before it ships.

**Why use Fable 5.1 for review?** The advisor brings a clean-context Claude review at commitment boundaries and before the architect reports a deliverable done. If the session itself is Fable, the review still supplies fresh eyes, though it is not an independent-model check.

**Upstream versions?** This fork's lineage: upstream v4 (Opus architect, Codex routine lane, Fable escalation + review) → v5 (Fable architect, Codex implementation lane, native Claude final review) → v6 (one fixed arrangement, Codex implements and Claude reviews; profiles removed) → v6.1 (adds a Sol escalation lane) → v6.2 (updates the escalation model) → v6.3 (`medium` escalation baseline and a separate routing rule) → this v7.0.0: rename the routine Codex lane, high-complexity Codex lane, and earlier Claude review agent to `luna-implementer`, `sol-implementer`, and `fable-advisor` on GPT-6 Luna, GPT-6 Sol, and Fable 5.1, and stop assuming the architect runs on Fable. For the original pattern, see [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor).

## License

MIT
