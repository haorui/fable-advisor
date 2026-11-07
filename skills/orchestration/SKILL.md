---
name: orchestration
description: 'Routing doctrine for the architect-as-orchestrator pattern — how a session on any model delegates substantial implementation to the default `sol-implementer` lane while making small, local changes directly, uses `sonnet-implementer` only when Sol is unavailable, consults `fable-advisor` at commitment boundaries, and gets every deliverable reviewed by `fable-advisor` before reporting done. USE WHEN delegating implementation work, deciding whether to delegate or implement directly, routing to the Sonnet fallback, turning architect mode off ("solo mode", "不用车道", "关闭 architect 模式", or the `fable-advisor lane profile: off` line in CLAUDE.md), turning it back on ("architect mode on", "use lanes", "开启 architect 模式"), choosing a reasoning effort for sol-implementer, writing a spec for a subagent, deciding whether to consult or invoke fable-advisor, using the Codex plugin''s review skills, managing session cost or token spend, or running any multi-task build where the session is the architect.'
---

# Orchestration — the architect's routing doctrine

The session is the architect, running on whatever model the user chose. It owns requirements, architecture, decomposition, specs, routing, and verification. Substantial implementation goes to `sol-implementer`, the default lane; small, local changes the architect makes directly (see "Delegate or implement directly"). `sonnet-implementer` is the fallback only when Sol is unavailable. Every finished deliverable, delegated or direct, gets a review from `fable-advisor` before the architect reports done.

## Delegate or implement directly

This doctrine began with a Fable architect driving cheaper Codex lanes, where the architect's tokens were the premium to protect and "never type code" followed from that. The typical session is now Opus-led, and architect token volume no longer decides routing. A handoff has real costs. The architect writes a spec, the lane runs, and the architect reads the diff and checks the report against it. Each handoff also drops some context the architect had. A lane is worth those costs when it buys at least one of these:

- **Vendor diversity**: GPT-6.1 Sol writes and Claude/Fable judges, so a second model family catches what one vendor's models jointly miss.
- **Parallelism**: independent specs run at the same time.
- **Context isolation**: a long implementation run, with its exploration and test output, stays out of the architect's context.

**Delegate to `sol-implementer`** for multi-file features and new modules, for work where the code will be much larger than the spec that describes it, for independent pieces that can run in parallel, and for security-sensitive or wide-blast-radius changes where a cross-vendor author is worth having.

**Implement directly** when the handoff would cost more than the work. That covers a change of a few lines in one or two files; doc, config, or prompt edits where the exact wording is the decision; small follow-up fixes to a lane diff the architect has already read; and a change tied so closely to the architect's current reasoning that a spec would have to restate the code. Announce it in one line (`→ direct · <session model>: <task>`) so routing stays visible. If a direct change grows past that size, stop and write the spec. A substantive defect in a lane's diff is not a small follow-up fix. Send it back as a corrected spec, where it counts under the two-failures takeover.

Either way, the rest of this doctrine holds. Verification evidence comes before acceptance, and the `fable-advisor` gate comes before done. A direct change skips the delegation prompt, not the spec's acceptance list and verification command: write both before the edit, because the review brief carries them. A direct change has no cross-vendor author; say so in the report.

**Keep the context lean.** Delegate broad exploration, codebase searches, and log-grepping to a read-only agent and keep only its conclusions. Read files yourself only when the decision genuinely depends on the exact code. Don't paste long files, full diffs, or verbose command output into the conversation when a path reference or an excerpt will do.

**Reason once, then hand off.** Do the hard thinking (the architecture, the interface design, the debugging hypothesis) in one pass, capture it in the spec, and let the lane carry it from there. Re-deriving decisions across turns wastes the work and lets the spec drift.

Whatever the routing, these stay with the architect: decomposition, interface design, hypothesis selection when debugging, spec writing, lane routing, and judging verification evidence.

## The lanes

Three agents, with the cross-vendor check on the default implementation side:

| Agent | Producer | Role | Notes |
|---|---|---|---|
| `sol-implementer` | GPT-6.1 Sol (`REASONING:` required; `medium` baseline) | Default implementation lane | Drives codex to write all delegated implementation code, including mechanical and routine work. Requires the codex CLI. |
| `sonnet-implementer` | Claude Sonnet (high effort) | Fallback only when Sol is unavailable | Writes the code itself from the six-part spec. No external dependency. |
| `fable-advisor` | Fable 5.1 (Claude model `fable`, high effort; LIGHT reviews run at medium) | Reviewer + outside voice | Two modes: REVIEW (`ship / fix-first / rethink`, FULL or LIGHT tier) and CONSULT (`proceed / revise / rethink`). No CLI or relay; falls back to Claude Opus when Fable is unavailable (see the final-review section). |

All delegated implementation goes to `sol-implementer`; what varies with judgment and risk is the `REASONING:` rung, not the lane.

## Lane statuses

Every lane report ends in one status. Each status maps to one action:

| Status | Action | Counts toward two-failures |
|---|---|---|
| `complete` | Run the Verification checks, then go on to the gate | — |
| `partial` (spec unmet, including Sonnet's second attempt) | Corrected spec to the same lane; may raise `REASONING:` | yes |
| `incomplete` | Codex is still running under budget: tell the same agent to resume waiting on the `PID=… FINAL=… LOG=…` its report carries | no |
| `timeout` | The lane killed codex, so only the partial diff survives. Re-run with a larger `BUDGET:`, split the spec, or keep the piece yourself. Never send it to Sonnet | no |
| `unavailable`: codex missing, an auth error, or no model access | Sonnet fallback for the rest of the session (see below) | no |
| `unavailable`: unsupported effort | A spec defect: fix `REASONING:` and re-run in Sol | no |
| `refused`: codex declined the task itself | Corrected spec to the same lane | yes |
| `refused`: declined over machine-wide config (the `~/.codex/AGENTS.md` case) | Fix the cause and re-invoke | no |
| `blocked` | A permission denial: surface it verbatim to the user, and never re-send or reword the prompt | no |

Before counting any row as a failure, apply the two checks in the two-failures takeover below. Whatever the status, name it and any cost change in your report to the user; never quietly absorb it.

## Sonnet fallback

The fallback is an explicit architect routing decision, never done inside the Sol lane. The only trigger is `STATUS: unavailable` from `sol-implementer`: codex missing, an auth error, or no `gpt-6.1-sol` access. Unsupported effort is **not** a trigger, even though the lane reports it as `unavailable` — that is a spec defect to fix and re-run in Sol.

Once triggered, route the rest of the session's implementation directly to `sonnet-implementer`; such unavailability usually persists for the session. An `unavailable` does not consume an attempt, so Sonnet starts at attempt 1. A first failure in the active Sonnet fallback gets a corrected spec in Sonnet; a second failure of the same task in any lane still triggers the two-failures takeover.

No other status triggers the fallback; see Lane statuses.

Label the Agent `description` as `Claude Sonnet (Sol fallback) · high: <task>` and announce `→ sonnet-implementer · Claude Sonnet · high (Sol fallback)`. Tell the user the deliverable lost its cross-vendor check: Claude wrote it and a Claude model reviewed it. `/codex:adversarial-review` cannot substitute when codex itself is what is unavailable.

## Showing which model runs each step

Claude Code's UI shows each subagent call by its agent name and the `description` passed to it. The `sol-implementer` wrapper runs on Sonnet while GPT-6.1 Sol writes the code; `sonnet-implementer` runs on Sonnet and writes the code itself. Label each Agent `description` with the model and effort in the form `<Model> · <effort>: <task>` — for example `GPT-6.1 Sol · medium: add pagination to /orders`, `Fable 5.1 · full: final review`, or `Claude Sonnet (Sol fallback) · high: update the checkout flow`.

Announce each routing decision in one line before delegating: `→ sol-implementer · GPT-6.1 Sol · medium`, `→ fable-advisor · Fable 5.1 · full` (or `· light`, or `· consult`), or `→ sonnet-implementer · Claude Sonnet · high (Sol fallback)`. Keep the lane's `LANE:` line when summarizing its report; it identifies the model and effort that actually ran.

The lane agents carry UI colours: Sol orange, `fable-advisor` purple, and `sonnet-implementer` green. Sol's effort is always named explicitly by the architect in the required `REASONING:` line.

## Turning the pattern off

Set the pattern off in either of two ways:

1. **In session** — say "solo mode", "不用车道", or "关闭 architect 模式". It takes effect immediately for that scope.
2. **Persistent** — put this line in the project's or the user's `CLAUDE.md`:

```
fable-advisor lane profile: off
```

`off` is the only value that line recognises. While it is active, nothing in this skill applies: the session reads, implements, and verifies directly, with no lane delegation, no mandatory consult, and no mandatory review gate. The three lane agents run only when the user explicitly asks for one, and running one does not turn the pattern back on. The session announces it once, at the first implementation step ("architect mode off: implementing directly"). In-session beats the `CLAUDE.md` line, and a project's line beats the user's. To turn the pattern back on in-session, say "architect mode on", "use lanes", or "开启 architect 模式".

**The two-failures takeover.** A task that fails its spec once gets a corrected spec back to `sol-implementer`, and the architect may raise its `REASONING:` one or more rungs — this is the escalation path. If the session is already using the Sonnet fallback, send the corrected spec back to Sonnet instead. A second failure of the same task, in any lane, triggers the takeover: the architect implements it personally, whatever its size. The budget is two attempts per task, not two per lane. The takeover is announced explicitly ("taking this over after two lane failures"), kept to the failing piece, and the resulting diff still goes through the review gate like everyone else's. **What counts as a failure is narrow**: a structured report whose evidence shows the spec unmet. The "Counts toward two-failures" column of Lane statuses decides each status. An empty, placeholder, or free-text report is *not* failure evidence — before counting any failure, check the working tree yourself (`git status`, read the diff, re-run the verification command). If the work actually landed, the response is a follow-up message to the *same* lane agent demanding its structured report — naming any unreported scope you found in the diff — not a failure tally and not a redo.

## Commitment boundaries — the outside voice

The architect owns its decisions, but owning a decision and making it unexamined are different things. At a commitment boundary, do both of the following:

1. **Make the boundary explicit**: state the decision, the options considered, and the deciding risk in one short block before committing.
2. **Consult the outside voice**: send that decision memo to `fable-advisor` in CONSULT mode. It returns proceed / revise / rethink with fresh eyes, judged against the memo rather than the conversation. The non-Anthropic perspective still sits at the implementation lane — GPT writes, Claude/Fable judges.

Consult at these moments:

- Before committing to an architecture, data migration, API shape, or refactor strategy
- Whenever the same problem has resisted two distinct attempts — including after a two-failures takeover that is itself struggling
- Any time the architect notices it is about to bet an hour of lane work on an assumption it hasn't tested

Act on the verdict or surface the disagreement — never silently ignore it. A consult costs cents and runs read-only; skipping it to save a minute is the wrong economy.

## The spec contract

Implementers share none of your conversation context. Every delegation prompt carries the six core parts below — this is "the six-part spec" every lane refers to. A `sol-implementer` spec adds the Sol lane lines that follow them: `REASONING:` always, `MODEL:` and `BUDGET:` only when needed.

1. **Objective** — what to build or change, one paragraph
2. **Files** — exact paths to create or modify
3. **Interfaces** — signatures, types, or API shapes the code must match
4. **Constraints** — project conventions, things not to touch
5. **Acceptance** — the observable behaviors that define done, one line each in "given X → Y" form, written by the architect before any lane starts. Every item must be checkable from outside the implementation (a command, an HTTP call, a CLI invocation, a file on disk). This list is the standard the deliverable is measured against; it goes to the implementer and, verbatim, to the reviewer.
6. **Verification** — the command(s) that prove the acceptance items hold

Sol lane lines (`sol-implementer` only, the only codex lane):

- **Reasoning** — required on every `sol-implementer` spec: the architect must provide one line, `REASONING: <effort>`, chosen from the rungs below. `sonnet-implementer` ignores it and uses its frontmatter effort.
- **Model** — optional: one line, `MODEL: <slug>`, only when the architect deliberately wants a codex model other than the lane's default. The lane ignores model names that appear anywhere else in the spec — mentioning another model in an objective does not switch the model.
- **Budget** — optional: one line, `BUDGET: <minutes>`, only when the task needs a wall clock other than the lane's 60-minute default. The lane ignores durations that appear anywhere else in the spec. Raise it for work you expect to run long rather than absorbing a `timeout` report and re-running from scratch; a spent budget kills codex mid-flight, and only the partial diff survives.

`medium` is the architect's baseline for every `sol-implementer` spec — and the table lists the reasons to move up. Mechanical and routine work stays at `medium`.

| Sol rung | Move up when |
|---|---|
| `medium` | Baseline. Every Sol spec starts here, including mechanical and routine work. |
| `high` | Ordinary features with a couple of design decisions left to the lane. |
| `xhigh` | Tricky logic, multi-file changes with interactions, or the corrected-spec second attempt. |
| `max` | Concurrency, security-sensitive paths, gnarly debugging, wide-blast-radius refactors, or problems that have resisted two attempts. |

If the verification command fully covers the acceptance list — no item the lane would have to report as `not-checkable-by-command` — and a failure costs one re-run, stay at `medium`.

`medium` is the floor, not a starting point to shave — the architect does not write `REASONING: low`; the lane still accepts `low` when the user names it explicitly. Effort is cost and wall-clock, not a quality dial to leave at max.

These rungs were set for GPT-6 Sol and carried over unchanged to GPT-6.1 Sol (same tier, same five rungs, verified 2026-10-01); re-derive them if the lane is re-pointed to a different tier.

The `REASONING:` line is required on every `sol-implementer` spec — the lane never picks its own effort. If it is omitted the lane runs at the user's configured default and flags that in `GAPS`; treat that flag as a spec defect to correct, not a valid state.

A spec you can't finish writing is a signal the decision isn't made yet — that's architect work, not a reason to hand the ambiguity to the lane.

An acceptance list the architect can't write before implementation is the same signal — the outcome hasn't been decided, and handing that to the lane means the lane will define done for itself, which is exactly what the list exists to prevent. Keep the list at the level of behaviors, not test cases — the concrete inputs and expected outputs used to check each item are the architect's to hold back for the review (see the final-review section).

## Parallelism

Independent specs (no shared files, no ordering dependency) launch as parallel agents in a single message. Sequential chains and single-file surgery stay serial.

## The final review — mandatory

**Always, once, at the end of a deliverable:** invoke `fable-advisor`, the review gate, with the stated goal, the constraints, and where to find the changes. It reads the accumulated diff with fresh eyes, judged against the goal rather than the conversation, and returns ship / fix-first / rethink. The architect does not report done before this review. **The architect never substitutes its own self-review for the gate** — the gate is an agent invocation with a returned verdict, or it did not happen.

The gate has two tiers, chosen by **who wrote the change**, not by how big it is. Small delegated changes are no more reliable than large ones, so a lane diff never gets the light tier.

- **FULL** — every deliverable containing a lane diff, and any direct change that touches a security-sensitive path, a migration, or an API shape. The brief carries the spec's acceptance list verbatim, plus held-back cases — one to three concrete inputs with expected outputs, chosen by the architect and never shown to the implementer — that the reviewer runs before reading the diff. An implementer that has seen the exact checks can satisfy the checks without satisfying the behavior; cases it never saw measure the behavior. When the deliverable has no black-box surface (a pure internal refactor, say), the architect says so in the brief instead of inventing cases.
- **LIGHT** — only a deliverable made entirely of small, local direct changes by the architect. The brief starts with `TIER: light` and carries the goal, the acceptance list, the verification command, and where to find the diff; no held-back cases, since cases the architect withholds from itself measure nothing. Invoke it with the Agent `effort: "medium"` parameter. The reviewer still re-runs the verification command and reads the diff.

The reviewer may decline a LIGHT brief whose diff is not small and local — multi-file, risky, or containing lane work — by returning `insufficient-brief` and asking for a FULL brief; supply it and re-invoke. Announce the tier: `→ fable-advisor · Fable 5.1 · full` or `· light`, and label the Agent `description` the same way.

`fable-advisor` has no CLI or relay; its only non-verdict status is `STATUS: insufficient-brief`, and the architect supplies what's missing and re-invokes. **Fable unavailable → Claude Opus.** Claude Code silently substitutes another model when the `fable` pin is unavailable, so read the report's `MODEL:` line on every consult and review. Any Fable version is the normal case — match the family, not the version number, since the `fable` alias moves to newer releases. Any Opus version is the accepted fallback: the verdict stands, and the architect tells the user it came from Opus because Fable was unavailable. Any other model — or an invocation that errors because Fable is unavailable — means re-invoking `fable-advisor` with the same brief and the Agent `model: "opus"` parameter, labelled `Claude Opus (Fable fallback): <task>`; a usage-limit error usually lasts the session, so after one, pass `model: "opus"` directly for the rest of it. A `CLAUDE_CODE_SUBAGENT_MODEL` override beats that parameter too; if the re-invoked report still names neither Fable nor Opus, surface it to the user instead of accepting the verdict.

A `ship` verdict is itself a claim, not evidence. Before reporting done on a ship, confirm the reviewer judged the actual change set — its findings, or the files it cites, must be consistent with the real diff. A ship rendered against an empty or wrong change set is void: fix the brief (usually the instructions for locating the changes) and re-invoke.

What the review buys depends on the session model. When the architect is not a Fable model, the consult and review are a second model, typically a stronger one reading in a clean context. When the architect is also a Fable model — or the review fell back to Opus while the architect runs on Opus — the review is a fresh-eyes check, not an independent-model check. Act on the verdict or surface the disagreement — never silently ignore it. `fix-first` findings are routed like any other change: substantive defects go back to the lane that produced the change as corrected specs; small ones the architect fixes directly and announces.

## The Codex plugin (optional)

If the official OpenAI Codex plugin for Claude Code is installed (`codex@openai-codex` under `enabledPlugins` in the user's Claude Code settings; `/plugin list` shows it), its commands become available in the session. It talks to the local `codex` binary over its app-server protocol, so it shares the same install and login as the lanes. The doctrine uses it three ways:

- **`/codex:adversarial-review`** — run it on the accumulated diff *before* the `fable-advisor` final review gate on any deliverable that touched a security-sensitive path, a migration, or an API shape. Pass its findings to `fable-advisor` in the review brief, labelled as unverified third-party claims that the advisor re-checks itself — they are input to its own read of the diff, not a substitute for it. `/codex:review` is the lighter pass for ordinary deliverables when the user wants cross-vendor review. Since this fork's reviewer (`fable-advisor`) is a Claude model, the Codex plugin's adversarial review is the only non-Anthropic check available on the review side of the pipeline — which is why it is recommended, not required, specifically on those deliverables.
- **`/codex:rescue --model <slug> --effort <rung>`** — a write-capable delegation the user can drive directly, with `/codex:status`, `/codex:result`, and `/codex:cancel` for background jobs. Use it when the user asks for it, or for a long-running investigation you want off the session's critical path. Its output is not a lane report, so the architect still reads the diff and re-runs verification itself. Whenever you want the structured report and the empty-diff check, use `sol-implementer` (or `sonnet-implementer` under the fallback).
- **`/codex:setup`** — point the user here when a lane reports `unavailable`; it diagnoses the codex binary, version, and login.

The plugin's optional stop-time review gate (`/codex:setup --enable-review-gate`) runs a Codex review every time the session stops; it overlaps with the mandatory `fable-advisor` end-of-deliverable gate and can loop, so leave it off under this pattern unless the user chooses otherwise. Without the plugin the pattern is unchanged — it adds a reviewer and a manual delegation path, it is not a dependency.

## Verification

Reports are claims, not evidence, so the same diff is checked by three parties. The lane runs the verification, the architect checks the report against the working tree, and the review gate re-runs verification again. The architect's part is a consistency check, not a third re-run. Before accepting any lane's work:

- `git diff --stat` plus `git status --short` must match the report's CHANGES (same files, no unreported scope), and the diff must be non-empty.
- The quoted VERIFIED output must be consistent with that diff: the test names, counts, and files it mentions exist in the change.

The architect still re-runs the verification command itself in three cases. The first is before writing a spec that builds on this lane's result, because a bad result must not become the next task's foundation. The second is before any commit made ahead of the gate. The third is before counting a failure (see the two-failures takeover). For direct changes, the architect runs verification itself, since no lane did. "Should work", "tests should pass", or a report with no command output means the task is not done. The lane's ACCEPTANCE block must account for every acceptance item; an item marked unmet, or a report whose VERIFIED block quotes a command run without an ACCEPTANCE block mapping it to the items, means the task is not done. A lane that reports a spec gap gets a corrected spec, not a "use your judgment".


**Packaging is the architect's.** No lane commits — a lane's report describes a verified working tree, not a commit. Once the gate has ruled `ship`, you write the commit. A commit you need before the gate (to hand the next spec a clean base, say) waits until you have re-run the verification yourself. Either way: the party that accepts the work records it, and commit granularity and message conventions were yours to set in the spec anyway. Never write "commit it yourself" into a spec — beyond blurring that ownership, the codex lane is sandboxed to the working tree while a git worktree's `.git` metadata lives outside it under the main checkout, so it structurally cannot, and asking spends a round trip to be told so.
