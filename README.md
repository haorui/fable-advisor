# Fable Advisor (Fable-architect fork)

**Fable runs the show. By default Codex does the typing and Claude Opus reviews everything before it ships — or flip the lanes: Profile B puts Opus on the typing and GPT-5.6 Sol on the gate.**

> Experimental fork of [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor) (v4). The upstream pattern puts Opus in the architect seat to save tokens; this fork spends the premium on the architect instead — Fable owns every judgment call — while keeping the cross-vendor check where upstream had it, on the implementation side. Profile B moves it to the review side.

Claude Code lets every subagent run on a different model — and lets the session itself run on a different model than its subagents. This fork exploits that with the **architect pattern**: your session runs on **Fable 5**, acting as a full-time architect. It owns requirements, decomposition, specs, and verification — delegates the typing to an implementation lane — and gets a **fresh-eyes review** of the finished work before calling anything done. Which vendor takes which seat is a **lane profile** you pick; the default is cross-vendor GPT-5.6 Luna typing and a native Claude Opus review:

| Agent | Producer | Role | Standing lane in |
|---|---|---|---|
| `codex-implementer` | **GPT-5.6 Luna** (max reasoning) | Implementation — drives codex to write the code from the architect's six-part spec | Profile A (default); the optional race lane under B |
| `opus-implementer` | **Claude Opus** (high effort) | Implementation — writes the code itself | Profile B; the optional race lane under A |
| `opus-reviewer` | **Claude Opus** (high effort) | Reviewer + outside voice — consults at commitment boundaries (proceed / revise / rethink) and the mandatory end-of-deliverable review (ship / fix-first / rethink), judged natively — no CLI, no relay | Profile A (default) |
| `codex-reviewer` | **GPT-5.6 Sol** (high reasoning) | Same two modes, same verdicts, relayed from codex | Profile B |

The architect does not report done before the active profile's review gate returns a verdict. Tokens route by capability: Fable emits judgment and specs (volume-light, the priciest seat kept lean), the implementation lane emits the bulk of the code, and one producing seat always runs off-Anthropic. In the default profile the architect and reviewer are both Claude, so the implementation lane being a *different model family* is what keeps the system honest — every diff crosses a vendor line before it can ship, and same-family blind spots never get to write the code unchallenged. There is no separate escalation lane: when a task fails its spec twice in the implementation lane, the architect — the strongest implementer in the system — takes it over personally, and that diff still goes through the review.

The plugin ships the **orchestration skill** — the routing doctrine, the cost discipline that keeps the Fable seat volume-light (emit judgment not volume, keep context lean, reason once then hand off), the six-part spec contract that makes context-free delegation safe, and the verification rules that keep every lane honest.

## Lane profiles

Which vendor implements and which reviews is a **profile**, and you pick it:

| Profile | Implementation lane | Reviewer + outside voice | Cross-vendor check sits at |
|---|---|---|---|
| **A** (default) | `codex-implementer` | `opus-reviewer` | the implementation lane — GPT writes, Claude judges (the upstream-v4 shape) |
| **B** | `opus-implementer` | `codex-reviewer` | the review gate — Claude writes, GPT judges |

Two ways to switch, both manual:

- **In session** — just say it: "use profile B", "切到 profile B", "反转车道". It takes effect immediately, and the architect announces the active profile the next time it routes work.
- **Persistent** — one line in your project's or user's `CLAUDE.md`:

```
fable-advisor lane profile: B
```

Absent both, you get Profile A. An in-session switch overrides the `CLAUDE.md` line for that session, and a project's line overrides your user-level one. **The architect never switches profiles on its own** — not to route around a failing lane, not to save cost. Flipping vendors is your call, not a recovery strategy.

**Turning it off.** `fable-advisor lane profile: off` in a `CLAUDE.md` — or an in-session "solo mode" / "不用车道" — switches the architect pattern off for that scope: your session does the work itself, with no lane delegation and no mandatory consult or review gate, and the four agents run only when you ask for one by name, which does not turn the pattern back on. Your session says so once at its first implementation step ("architect mode off: implementing directly"). "use profile A" or "use profile B" turns it back on. In-session beats the `CLAUDE.md` line; a project's line beats your user-level one.

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
- **Codex lanes:** the [OpenAI Codex CLI](https://github.com/openai/codex) installed and authenticated (`npm i -g @openai/codex`, then `codex login`) — needed under **both** profiles, just on a different seat. Under **Profile A** (the default) it drives the implementation lane (`codex-implementer`, **GPT-5.6 Luna** as `gpt-5.6-luna` with `model_reasoning_effort=max`) and the review gate is native Claude; under **Profile B** it drives the review gate (`codex-reviewer`, **GPT-5.6 Sol** as `gpt-5.6-sol` at `high`) and the implementation lane is native Claude. Racing the two implementation lanes needs the CLI under either profile. Without an installed, authenticated CLI or model access, the codex agents report `STATUS: unavailable` — they never silently fall back to a Claude model. Under Profile A that stops the work at the implementation lane; under Profile B the review gate instead degrades *loudly*: the architect reports the deliverable done-but-unreviewed, saying exactly that.
- Heads-up: if a pinned Claude model isn't available on your account, Claude Code silently falls back to your session model. Under the **default Profile A** that slip costs more than money: `model: opus` in `opus-reviewer` quietly becoming Fable turns the review gate into the architect's own model judging its own deliverable — the self-review the doctrine forbids, arriving as a clean verdict with nothing to signal it. Under **Profile B** the same fallback in `opus-implementer` makes the typing lane *more* expensive than intended; if costs feel off, check your plan. (This quiet fallback applies only to Claude model pins — the codex lanes always fail loudly with a structured error.)

Model resolution order in Claude Code: `CLAUDE_CODE_SUBAGENT_MODEL` env var → per-invocation `model` parameter → agent frontmatter → session model.

## Use it

With the session on Fable, just ask for work — the orchestration skill routes it:

```
Add rate limiting to our public API. Design it, delegate the
implementation, and verify the evidence before you call it done.
```

The architect writes the spec, delegates to the active profile's implementation lane (or races the two lanes on a high-stakes spec), reads the diff and verification evidence when the report comes back, sends the finished work through the profile's reviewer for the final review, and only then reports done.

To make the doctrine always-on, add one line to your project's `CLAUDE.md`:

```
You are the architect — minimize your own token volume. Delegate all
implementation through the orchestration skill's routing table (never
type code yourself, except the documented two-failures takeover),
delegate broad codebase exploration to cheap read-only agents, consult
the active lane profile's reviewer at commitment boundaries, verify
evidence before accepting any lane's report, and get that reviewer's
verdict before reporting any deliverable done.
```

## The final review

Every deliverable ends at the active profile's review gate. Under the default Profile A that is `opus-reviewer`: Claude Opus reads the accumulated diff itself, with fresh eyes and no accumulated conversational assumptions, against the stated goal rather than the conversation — and returns ship / fix-first / rethink. It runs natively, with no CLI in the path and no `unavailable` failure mode to degrade around; the cross-vendor check sits at the implementation lane instead, where GPT-5.6 Luna writes the code Claude then judges.

Under Profile B the gate is `codex-reviewer` instead — GPT-5.6 Sol in a read-only sandbox, same two modes, same verdicts, relayed intact. Under that profile it is the system's one non-Anthropic check: the architect and implementer share a vendor, the reviewer deliberately doesn't. A missing or unparseable verdict counts as *no review*, never as a pass — the failure modes (`unavailable`, `timeout`, `refused`) are structured and loud by design.

Whichever agent holds the gate doubles as the **outside voice** before anything is committed. At commitment boundaries — architecture choices, migrations, API shapes, refactor strategies, or a problem that has resisted two attempts — the architect writes a short decision memo (decision, options, deciding risk) and sends it to that reviewer in CONSULT mode for a proceed / revise / rethink verdict. The decision stays with the Fable architect — there is no stronger Claude to escalate to — but it is never made unexamined.

## FAQ

**Why put the most expensive model in the architect seat?** Because the architect seat is where judgment concentrates: decomposition, interface design, debugging hypotheses, and verdicts on evidence. This fork bets that better judgment there beats cheaper tokens there — while the cost discipline (delegate the volume, keep the context lean) keeps the Fable seat from ever carrying the token bulk. It is still far cheaper than running a single Fable session that does its own typing.

**Why is the implementation lane a GPT model?** Vendor diversity, concentrated where the code gets written. In the default profile Fable architects and Opus judges — both Anthropic — so the producer is deliberately the other family, and every diff crosses a vendor line before it can ship. That is the upstream shape, and the honest trade is stated plainly: the code now rides on GPT-5.6 Luna, while the gate *and* the commitment-boundary consults stay inside Anthropic, judged by the architect's own vendor. If you'd rather concentrate the diversity at the gate instead, Profile B inverts it — `opus-implementer` writes and `codex-reviewer` judges, putting a non-Anthropic verdict on Claude-written code.

**What happened to fable-implementer and fable-advisor?** Both collapsed into the architect. The session *is* Fable now, so a Fable escalation lane and a Fable advisor would be the same model reviewing itself at extra hand-off cost. Hard tasks that defeat the implementation lane twice go to the architect directly; fresh-eyes review moved to the profile's review gate.

**Upstream versions?** This fork's lineage: upstream v4 (Opus architect, Codex routine lane, Fable escalation + review) → this v5 (Fable architect, Codex implementation lane, native Opus review — that's Profile A, the default, keeping v4's producing pair with the architect seat upgraded; Profile B swaps the producing pair, Opus typing and a GPT-5.6 Sol gate). For the original pattern, use [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor).

## License

MIT
