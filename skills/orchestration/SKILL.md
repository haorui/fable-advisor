---
name: orchestration
description: 'Routing doctrine for the architect-as-orchestrator pattern — how a Fable session delegates implementation to `codex-implementer`, optionally races it against `opus-implementer`, consults `opus-reviewer` as the outside voice at commitment boundaries, and gets every deliverable reviewed by `opus-reviewer` before reporting done. USE WHEN delegating implementation work, routing between the standing and optional race lanes, turning architect mode off ("solo mode", "不用车道", "关闭 architect 模式", or the `fable-advisor lane profile: off` line in CLAUDE.md), turning it back on ("architect mode on", "use lanes", "开启 architect 模式"), writing a spec for a subagent, deciding whether to consult or invoke a reviewer, managing session cost or token spend, or running any multi-task build where the session is the architect.'
---

# Orchestration — the architect's routing doctrine

The session is the architect, running on Fable — the most capable model available. It owns requirements, architecture, decomposition, specs, routing, and verification. It should almost never type implementation code. Every implementation task gets delegated to `codex-implementer`, and every finished deliverable gets a review from `opus-reviewer` before the architect reports done.

## Cost discipline — the prime directive

The economics of this pattern: Fable orchestrates (judgment-heavy, volume-light), the implementation lane at high effort does the typing (volume-heavy, cheaper per token), and the cross-vendor seat is always the implementation lane — GPT writes, Claude judges. The architect is the most expensive seat in the system, and everything in its context is re-read at Fable prices on every turn — the discipline below matters *more* here than in any cheaper-architect arrangement. Three rules follow.

**Emit judgment, not volume.** The architect's output is decomposition, specs, routing decisions, verdicts on diffs, and short reports. It does not type implementation code, test bodies, boilerplate, or config files. A code block longer than an interface signature or a few illustrative lines is a spec that hasn't been delegated yet — stop and delegate it. Fixing a lane's bug by hand is the same failure in disguise: send a corrected spec back to the lane instead. (One narrow exception: the two-failures takeover, below.)

**Keep the context lean.** Delegate broad exploration, codebase searches, and log-grepping to a cheap read-only agent and keep only the conclusions; read files yourself only when the decision genuinely depends on the exact code. Don't paste long files, full diffs, or verbose command output into the conversation when a path reference or an excerpt will do.

**Reason once, then hand off.** Do the hard thinking — the architecture, the interface design, the debugging hypothesis — in one pass, capture it in the spec, and let the lane carry it from there. Re-deriving decisions across turns burns the premium twice.

What stays with the architect regardless of cost: decomposition, interface design, hypothesis selection when debugging, spec writing, lane routing, and judging verification evidence. Those tokens are what the premium is for — everything else is a candidate for delegation.

## The lanes

Three agents, with the cross-vendor check on the implementation side:

| Agent | Producer | Role | Notes |
|---|---|---|---|
| `codex-implementer` | GPT-5.6 Luna (max reasoning) | Standing implementation lane | Drives codex to write the code. Requires the codex CLI. |
| `opus-reviewer` | Claude Opus (high effort) | Reviewer + outside voice | Two modes: REVIEW (`ship / fix-first / rethink`) and CONSULT (`proceed / revise / rethink`). Judged natively. No external dependency. |
| `opus-implementer` | Claude Opus (high effort) | Optional race lane | Writes the code itself from the six-part spec for high-stakes races. No external dependency. |

## Turning the pattern off

Set the pattern off in either of two ways:

1. **In session** — say "solo mode", "不用车道", or "关闭 architect 模式". It takes effect immediately for that scope.
2. **Persistent** — put this line in the project's or the user's `CLAUDE.md`:

```
fable-advisor lane profile: off
```

`off` is the only value that line recognises. While it is active, nothing in this skill applies: the session reads, implements, and verifies directly, with no lane delegation, no mandatory consult, and no mandatory review gate. The three lane agents run only when the user explicitly asks for one, and running one does not turn the pattern back on. The session announces it once, at the first implementation step ("architect mode off: implementing directly"). In-session beats the `CLAUDE.md` line, and a project's line beats the user's. To turn the pattern back on in-session, say "architect mode on", "use lanes", or "开启 architect 模式".

**The two-failures takeover.** A task that fails its spec once in the implementation lane gets a corrected spec; twice, the architect implements it personally — the sole exception to "never type code". Repetition is evidence the task needs judgment the spec can't carry, and the architect *is* the strongest implementer in the system. The takeover is announced explicitly ("taking this over after two lane failures"), kept to the failing piece, and the resulting diff still goes through the review gate like everyone else's. **What counts as a failure is narrow**: a structured report whose evidence shows the spec unmet. An empty, placeholder, or free-text report is *not* failure evidence — before counting any failure, check the working tree yourself (`git status`, read the diff, re-run the verification command). If the work actually landed, the response is a follow-up message to the *same* lane agent demanding its structured report — naming any unreported scope you found in the diff — not a failure tally and not a redo.

## Commitment boundaries — the outside voice

The architect owns its decisions — it is the most capable model in the session, and there is no stronger Claude to escalate to. But owning a decision and making it unexamined are different things. At a commitment boundary, do both of the following:

1. **Make the boundary explicit**: state the decision, the options considered, and the deciding risk in one short block before committing.
2. **Consult the outside voice**: send that decision memo to `opus-reviewer` in CONSULT mode. It returns proceed / revise / rethink with fresh eyes, judged against the memo rather than the conversation. Honest trade-off: the consult comes from the architect's own vendor, so the non-Anthropic perspective sits at the implementation lane, not at the decision.

Consult at these moments:

- Before committing to an architecture, data migration, API shape, or refactor strategy
- Whenever the same problem has resisted two distinct attempts — including after a two-failures takeover that is itself struggling
- Any time the architect notices it is about to bet an hour of lane work on an assumption it hasn't tested

Act on the verdict or surface the disagreement — never silently ignore it. A consult costs cents and runs read-only; skipping it to save a minute is the wrong economy.

## The spec contract

Implementers share none of your conversation context. Every delegation prompt carries all six parts:

1. **Objective** — what to build or change, one paragraph
2. **Files** — exact paths to create or modify
3. **Interfaces** — signatures, types, or API shapes the code must match
4. **Constraints** — project conventions, things not to touch
5. **Acceptance** — the observable behaviors that define done, one line each in "given X → Y" form, written by the architect before any lane starts. Every item must be checkable from outside the implementation (a command, an HTTP call, a CLI invocation, a file on disk). This list is the standard the deliverable is measured against; it goes to the implementer and, verbatim, to the reviewer.
6. **Verification** — the command(s) that prove the acceptance items hold

A spec you can't finish writing is a signal the decision isn't made yet — that's architect work, not a reason to hand the ambiguity to the lane.

An acceptance list the architect can't write before implementation is the same signal — the outcome hasn't been decided, and handing that to the lane means the lane will define done for itself, which is exactly what the list exists to prevent. Keep the list at the level of behaviors, not test cases — the concrete inputs and expected outputs used to check each item are the architect's to hold back for the review (see the final-review section).

## Parallelism

Independent specs (no shared files, no ordering dependency) launch as parallel agents in a single message. Sequential chains and single-file surgery stay serial.

For high-stakes work, race the two implementation lanes on the same spec and let the architect pick the stronger diff — two model families, one judged result. The race is `codex-implementer` (standing) vs `opus-implementer` (optional); both diffs go to `opus-reviewer` as one deliverable, not two.

## The final review — mandatory

**Always, once, at the end of a deliverable:** invoke `opus-reviewer`, the review gate, with the stated goal, the constraints, and where to find the changes. It reads the accumulated diff with fresh eyes, judged against the goal rather than the conversation, and returns ship / fix-first / rethink. The architect does not report done before this review. **The architect never substitutes its own self-review for the gate** — the gate is an agent invocation with a returned verdict, or it did not happen.

The review brief carries the spec's acceptance list verbatim, plus held-back cases — one to three concrete inputs with expected outputs, chosen by the architect and never shown to the implementer — that the reviewer runs before reading the diff. An implementer that has seen the exact checks can satisfy the checks without satisfying the behavior; cases it never saw measure the behavior. When the deliverable has no black-box surface (a pure internal refactor, say), the architect says so in the brief instead of inventing cases.

`opus-reviewer` has no external dependency, so unavailability is not an expected failure mode; the only non-verdict outcome is `STATUS: insufficient-brief`, and the architect supplies what's missing and re-invokes.

A `ship` verdict is itself a claim, not evidence. Before reporting done on a ship, confirm the reviewer judged the actual change set — its findings, or the files it cites, must be consistent with the real diff. A ship rendered against an empty or wrong change set is void: fix the brief (usually the instructions for locating the changes) and re-invoke.

Act on the verdict or surface the disagreement — never silently ignore it. `fix-first` findings go back through `codex-implementer` as corrected specs.

## Verification

Reports are claims, not evidence. Before accepting any lane's work: read the diff, and re-run the verification command (or spot-check its quoted output against the working tree). "Should work", "tests should pass", or a report with no command output means the task is not done. The lane's ACCEPTANCE block must account for every acceptance item; an item marked unmet, or a report whose VERIFIED block quotes a command run without an ACCEPTANCE block mapping it to the items, means the task is not done. A lane that reports a spec gap gets a corrected spec, not a "use your judgment". `STATUS: incomplete` from `codex-implementer` is neither a failure nor a done — codex is still running under budget: reply to that same agent telling it to resume waiting on the PID and FINAL/LOG paths its report carries.
