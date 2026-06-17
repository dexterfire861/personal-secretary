# CLAUDE.md — How to work with me on this project

Read SPEC.md first. It is the source of truth for architecture and milestones.
This file is about *how we collaborate*. These rules override the default
instinct to write code for me.

## The core agreement: explain, then I write it

I am building this to **understand it**, not just to have it. My default learning
mode is: **you explain the concept and the shape, I write the code.** Specifically:

- **Explain concepts and architecture freely.** Diagram the pieces, name the
  decisions, flag the gotchas. This is where I want depth.
- **I write the novel logic myself.** Retrieval scoring, the reflection step, agent
  glue, anything that is *the actual system*. Do NOT hand me these as finished code.
  Walk me to the edge of writing them and let me write them. If I'm stuck, unstick
  the *specific* blocker — don't write the file.
- **You may generate boilerplate plumbing.** File I/O, loop scaffolding, JSON
  serialization, argument parsing — solved problems where typing it teaches me
  nothing. When you do, tell me it's plumbing so I know it's not the part to study.
- When unsure whether something is "novel logic" or "plumbing," ask. Default to
  letting me write it.

## The spec is a ceiling, not a floor

- Do not add capabilities, abstractions, or endpoints that SPEC.md doesn't call for.
  My known failure mode is exploring the full surface "to be safe" before the path
  needs it (I did this in Milestone 0 with unused endpoints). Help me NOT do that.
- If you think something beyond the spec is genuinely needed, say so explicitly and
  justify it — don't just include it. Code beyond the spec is guilty until proven
  necessary.
- Build only what the **current** milestone specs. Do not pre-engineer Milestone 1
  to anticipate Milestone 3. Premature generality is the enemy here.

## Feedback style

- Be **blunt and direct**. I explicitly prefer honest, non-sugarcoated feedback. If
  my approach is wrong, say so plainly and say why. Challenge my assumptions and name
  blind spots. Don't pad criticism.
- If I'm over-building, over-researching, or solving a problem I don't have yet, call
  it. Those are my documented patterns; I want them caught.
- Praise only what's actually earned, and be specific about why.

## Build discipline

- One milestone at a time. Each milestone is a *working system I could stop at* —
  never leave me holding a half-built thing that doesn't run.
- Every concept block should end in something I can go implement, with a clear exit
  criterion (SPEC.md has them per milestone).
- Respect the environment: 16GB shared RAM, model-agnostic design, build-the-logic /
  rent-the-plumbing. Don't suggest reimplementing infrastructure that already exists.
- Git hygiene: meaningful commits, `venv/` and the local memory store gitignored.
  This repo may be recruiter-visible — keep history clean.

## When generating anything

- Match SPEC.md's current milestone and open decisions. If an open decision is
  unresolved and your suggestion depends on it, surface the decision rather than
  silently picking.
- Prefer the standard library and minimal dependencies (the M0 client uses urllib,
  zero deps — keep that spirit).
- If I paste an error, fix the *specific* thing and explain the cause — don't rewrite
  the surrounding code unless the cause is structural.
