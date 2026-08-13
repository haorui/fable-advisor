---
name: orchestration
description: Routing doctrine for the architect-as-orchestrator pattern — how a Fable session delegates implementation to the active lane profile's implementer, optionally races it against the other vendor, consults the profile's reviewer as the outside voice at commitment boundaries, and gets every deliverable reviewed by it before reporting done. USE WHEN delegating implementation work, choosing between opus-implementer/codex-implementer lanes, switching or asking about lane profiles ("use profile B", "反转车道", the `fable-advisor lane profile:` line in CLAUDE.md), writing a spec for a subagent, deciding whether to consult or invoke a reviewer, managing session cost or token spend, or running any multi-task build where the session is the architect.
---

# Orchestration — the architect's routing doctrine

The session is the architect, running on Fable — the most capable model available. It owns requirements, architecture, decomposition, specs, routing, and verification. It should almost never type implementation code. Every implementation task gets delegated to the active profile's implementation lane, and every finished deliverable gets a review from the active profile's reviewer before the architect reports done.

## Cost discipline — the prime directive

The economics of this pattern: Fable orchestrates (judgment-heavy, volume-light), the implementation lane at high effort does the typing (volume-heavy, cheaper per token), and one of the two producing seats always runs off-Anthropic — the typing under Profile A, the review under Profile B. The architect is the most expensive seat in the system, and everything in its context is re-read at Fable prices on every turn — the discipline below matters *more* here than in any cheaper-architect arrangement. Three rules follow.

**Emit judgment, not volume.** The architect's output is decomposition, specs, routing decisions, verdicts on diffs, and short reports. It does not type implementation code, test bodies, boilerplate, or config files. A code block longer than an interface signature or a few illustrative lines is a spec that hasn't been delegated yet — stop and delegate it. Fixing a lane's bug by hand is the same failure in disguise: send a corrected spec back to the lane instead. (One narrow exception: the two-failures takeover, below.)

**Keep the context lean.** Delegate broad exploration, codebase searches, and log-grepping to a cheap read-only agent and keep only the conclusions; read files yourself only when the decision genuinely depends on the exact code. Don't paste long files, full diffs, or verbose command output into the conversation when a path reference or an excerpt will do.

**Reason once, then hand off.** Do the hard thinking — the architecture, the interface design, the debugging hypothesis — in one pass, capture it in the spec, and let the lane carry it from there. Re-deriving decisions across turns burns the premium twice.

What stays with the architect regardless of cost: decomposition, interface design, hypothesis selection when debugging, spec writing, lane routing, and judging verification evidence. Those tokens are what the premium is for — everything else is a candidate for delegation.

## The lanes

Four agents, two roles each side of the vendor line:

| Agent | Producer | Role | Notes |
|---|---|---|---|
| `opus-implementer` | Claude Opus (high effort) | Implementation | Writes the code itself from the five-part spec. No external dependency. |
| `codex-implementer` | GPT-5.6 Luna (max reasoning) | Implementation | Drives codex to write the code. Requires the codex CLI. |
| `codex-reviewer` | GPT-5.6 Sol (high reasoning) | Reviewer + outside voice | Two modes: REVIEW (`ship / fix-first / rethink`) and CONSULT (`proceed / revise / rethink`). Relays codex's verdict; requires the codex CLI. |
| `opus-reviewer` | Claude Opus (high effort) | Reviewer + outside voice | Same two modes and same verdict vocabularies, judged natively. No external dependency. |

## Lane profiles

Which two of those four are standing lanes is set by the active **lane profile**:

| Profile | Implementation lane | Reviewer + outside voice | Where the cross-vendor check sits |
|---|---|---|---|
| **A** (default) | `codex-implementer` | `opus-reviewer` | The implementation lane — GPT writes, Claude judges (the upstream-v4 shape) |
| **B** | `opus-implementer` | `codex-reviewer` | The review gate — Claude writes, GPT judges |

Selection is **manual only**, two ways:

1. **In session** — the user says so ("use profile B", "切到 profile B", "反转车道"). Takes effect immediately, for the rest of the session.
2. **Persistent** — a line in the project's or the user's `CLAUDE.md` of the form `fable-advisor lane profile: B`.

Absent both, Profile A. In-session beats the `CLAUDE.md` line. After a switch, the architect **announces the active profile** the next time it routes work ("Profile B active: implementation → opus-implementer, review → codex-reviewer"). The architect **never switches profiles on its own** — not to route around a failing lane, not to save cost, not because a task "feels" better suited to the other vendor. A lane that keeps failing is a spec problem or a takeover, not a profile change.

**The two-failures takeover.** A task that fails its spec once in the active profile's implementation lane gets a corrected spec; twice, the architect implements it personally — the sole exception to "never type code". Repetition is evidence the task needs judgment the spec can't carry, and the architect *is* the strongest implementer in the system. The takeover is announced explicitly ("taking this over after two lane failures"), kept to the failing piece, and the resulting diff still goes through the profile's review gate like everyone else's. **What counts as a failure is narrow**: a structured report whose evidence shows the spec unmet. An empty, placeholder, or free-text report is *not* failure evidence — before counting any failure, check the working tree yourself (`git status`, read the diff, re-run the verification command). If the work actually landed, the response is a follow-up message to the *same* lane agent demanding its structured report — naming any unreported scope you found in the diff — not a failure tally and not a redo.

## Commitment boundaries — the outside voice

The architect owns its decisions — it is the most capable model in the session, and there is no stronger Claude to escalate to. But owning a decision and making it unexamined are different things. At a commitment boundary, do both of the following:

1. **Make the boundary explicit**: state the decision, the options considered, and the deciding risk in one short block before committing.
2. **Consult the outside voice**: send that decision memo to the active profile's reviewer — `opus-reviewer` under Profile A, `codex-reviewer` under Profile B — in CONSULT mode. It returns proceed / revise / rethink with fresh eyes, judged against the memo rather than the conversation. Honest trade-off: under Profile A the consult comes from the architect's own vendor, so the non-Anthropic perspective sits at the implementation lane instead of at the decision.

Consult at these moments:

- Before committing to an architecture, data migration, API shape, or refactor strategy
- Whenever the same problem has resisted two distinct attempts — including after a two-failures takeover that is itself struggling
- Any time the architect notices it is about to bet an hour of lane work on an assumption it hasn't tested

Act on the verdict or surface the disagreement — never silently ignore it. A consult costs cents and runs read-only; skipping it to save a minute is the wrong economy. Under Profile B, if the codex CLI is unavailable the decision may proceed, but the architect says so explicitly at the boundary — same loud-degradation rule as the final review.

## The spec contract

Implementers share none of your conversation context. Every delegation prompt carries all five parts:

1. **Objective** — what to build or change, one paragraph
2. **Files** — exact paths to create or modify
3. **Interfaces** — signatures, types, or API shapes the code must match
4. **Constraints** — project conventions, things not to touch
5. **Verification** — the command(s) that prove it works

A spec you can't finish writing is a signal the decision isn't made yet — that's architect work, not a reason to hand the ambiguity to the lane.

## Parallelism

Independent specs (no shared files, no ordering dependency) launch as parallel agents in a single message. Sequential chains and single-file surgery stay serial.

For high-stakes work, race the two implementation lanes on the same spec and let the architect pick the stronger diff — two model families, one judged result. The race is the mirror image of the active profile: under Profile A the standing `codex-implementer` gets raced against the optional `opus-implementer`; under Profile B the standing `opus-implementer` gets raced against the optional `codex-implementer`. Either way both diffs go to the profile's reviewer as one deliverable, not two.

## The final review — mandatory

**Always, once, at the end of a deliverable:** invoke the active profile's reviewer — `opus-reviewer` under Profile A, `codex-reviewer` under Profile B — with the stated goal, the constraints, and where to find the changes. It reads the accumulated diff with fresh eyes, judged against the goal rather than the conversation, and returns ship / fix-first / rethink. The architect does not report done before this review. **In both profiles, the architect never substitutes its own self-review for the gate** — the gate is an agent invocation with a returned verdict, or it did not happen.

Degradation policy is profile-specific, because only the codex-backed seat has an external dependency (CLI install, auth, model access) — and that seat is the implementation lane under Profile A, the review gate under Profile B:

- **Profile A.** `opus-reviewer` has no external dependency, so unavailability is not an expected failure mode at the gate. The only non-verdict outcome is `STATUS: insufficient-brief` — the architect supplies what is missing (usually the stated goal) and re-invokes.
- **Profile B.** `STATUS: unavailable | timeout | refused` → the review did not happen. Fix the cause and re-invoke if you can (auth, transient timeout, answering codex's clarifying question). If it genuinely cannot run, the architect may report the deliverable **done-but-unreviewed, saying exactly that and why** — loud degradation. Never silently skip the gate, never quietly swap `opus-reviewer` in for the Profile-B gate and call it the review, and never let a `refused` (no parseable verdict) pass as a completed review. Switching profiles to route around a broken CLI is a user decision, not the architect's.

A `ship` verdict is itself a claim, not evidence. Before reporting done on a ship, confirm the reviewer judged the actual change set — its findings, or the files it cites, must be consistent with the real diff. A ship rendered against an empty or wrong change set is void: fix the brief (usually the instructions for locating the changes) and re-invoke.

Act on the verdict or surface the disagreement — never silently ignore it. `fix-first` findings go back through the profile's implementation lane as corrected specs.

## Verification

Reports are claims, not evidence. Before accepting any lane's work: read the diff, and re-run the verification command (or spot-check its quoted output against the working tree). "Should work", "tests should pass", or a report with no command output means the task is not done. A lane that reports a spec gap gets a corrected spec, not a "use your judgment". `STATUS: incomplete` from either codex lane is neither a failure nor a done — codex is still running under budget: reply to that same agent telling it to resume waiting on the PID and FINAL/LOG paths its report carries.
