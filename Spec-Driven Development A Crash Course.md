-   [](/)
-   [Getting Started: Crash Courses](/docs/getting-started)
-   [General Agents](/docs/general-agents)
-   Spec-Driven Development

# Spec-Driven Development: A Crash Course

*13 Concepts · Agree on the **what** before you generate the **how***

You ask an AI to build something. It hands you back code that *looks* right. You run it. It breaks. Or worse, it works, but it solves a slightly different problem than the one in your head. So you explain again. It fixes that part and quietly undoes something it got right two messages ago. An hour later you have a pile of code you do not fully trust and cannot cleanly change.

That loop has a name: **vibe coding**. You give the AI a vague idea and hope it guesses correctly. For a throwaway prototype, that is fine. For anything you intend to keep, deploy, or hand to someone else, it is a trap.

**Spec-Driven Development (SDD)** is the way out. Instead of describing what you want and hoping, you *write it down*, clearly enough that you and the AI agree **before any code exists.** That written agreement is the **spec**. Code becomes what the spec produces, not the other way around.

This course covers the discipline end to end. By the end you can run a full spec-driven build yourself, three ways: in **claude.ai** (the web app, your main tool here), in **Claude Code**, and in **OpenCode**. The same discipline transfers to all three.

In SDD, **the spec is the source of truth, and code is a build output.** Every concept in this course is a way to write a better spec, agree on it sooner, or keep it true as the project grows.

This is already how agentic coding works in practice

You don't have to take this on faith. Anthropic's 2026 analysis of about 400,000 agentic coding sessions found a clear division of labor: people make most *planning* decisions (what to build), the agent most *execution* decisions (how to build it). And the strongest predictor of a session's **success** wasn't coding skill; it was **domain expertise**: how precisely the person framed the work, what they asked the agent to verify, and whether they could steer it back when it drifted. SDD is the discipline that makes you good at the half that stays yours. See Anthropic's [*Agentic coding and persistent returns to expertise*](https://www.anthropic.com/research/claude-code-expertise).

Who decides what — across ~400,000 sessionsYou (the person)The agentPlanning— what to build70%30%Execution— how to build it20%80%

*The what/how split, measured across ~400,000 sessions (Anthropic, 2026). SDD is how you get good at the planning half.*

Prerequisite: [AI Prompting in 2026](/docs/ai-prompting-2026)

That course taught you how to talk to AI: giving context, asking clearly, checking the work. This course teaches what to do **before** you ask for anything: how to turn a fuzzy idea into a written spec precise enough to build from. It pairs naturally with the [**Agentic Coding Crash Course**](/docs/agentic-coding-crash-course), the companion you have already met for the coding tools in depth.

### You do not need to be a programmer for this[​](#not-a-programmer)

SDD is a **thinking discipline**, not a coding skill. You practise it almost entirely in plain language, in a normal chat window. The output is a clearly written document, then a working result built from it, whether an app, a script, a report generator, or an automation. If you can write a clear brief for a capable colleague, you can write a spec. (See [Code You Never Write](/docs/code-you-never-write-crash-course) for why this is now a general skill, not a developer one.)

The study makes this concrete: coding background barely changed whether a session succeeded; **domain expertise did.** You are not asked to write code; you are asked to know your problem well enough to write it down: the rules, the edge cases, what "done" means. **The spec is where your expertise goes.** An accountant who can state every reconciliation rule out-builds a developer who doesn't understand the books, because the spec carries the knowledge and the agent supplies the code.

* * *

## Three tools, one discipline[​](#three-ways)

Everything below works in three tools. We lead with **claude.ai** because it needs nothing installed (you can do real spec-driven work in the browser today) and because the chat-and-document loop makes the *thinking* visible. The same moves map cleanly onto the two coding agents.

**claude.ai** (main)

**Claude Code**

**OpenCode**

**What it is**

The web/desktop chat app

Anthropic's coding agent (terminal/IDE)

Open-source coding agent, any model

**Where the spec lives**

An **Artifact** (an editable doc beside the chat) in a **Project** (a saved workspace)

Files in your repo (`CLAUDE.md`, `specs/`)

Files in your repo (`AGENTS.md`, `specs/`)

**Best for**

Thinking, drafting, non-coders, getting started

Building real software, end-to-end

Same, with model choice and cost control

**Alternatives**

**ChatGPT** (Projects + Canvas) and **Gemini** (Gems + Canvas) run the same discipline

(none)

(none)

Want the full version of any topic?

This is a crash course: the whole discipline in one read. Each concept has a full, code-level lesson in the deep dive, [**Chapter 16: Spec-Driven Development**](/docs/General-Agents-Foundations/spec-driven-development): [Why Specs Beat Vibe Coding](/docs/General-Agents-Foundations/spec-driven-development/why-specs-beat-vibe-coding), [The Three Levels of SDD](/docs/General-Agents-Foundations/spec-driven-development/three-levels-of-sdd), [The Project Constitution](/docs/General-Agents-Foundations/spec-driven-development/the-project-constitution), [Parallel Research with Subagents](/docs/General-Agents-Foundations/spec-driven-development/parallel-research), [Writing Effective Specifications](/docs/General-Agents-Foundations/spec-driven-development/writing-effective-specs), [Refinement via Interview](/docs/General-Agents-Foundations/spec-driven-development/refinement-via-interview), [Task-Based Implementation](/docs/General-Agents-Foundations/spec-driven-development/task-based-implementation), [The Decision Framework](/docs/General-Agents-Foundations/spec-driven-development/decision-framework), and [SDD Exercises](/docs/General-Agents-Foundations/spec-driven-development/sdd-exercises).

### What this course covers[​](#what-this-course-covers)

Part

Topic

What you learn

**1**

[The Shift](#part-1-the-shift)

Why vibe coding fails, what a spec actually is, the three levels of SDD

**2**

[The Method](#part-2-the-method)

The constitution, then the four phases: Research → Specify → Clarify → Build

**3**

[The Three Ways](#part-3-the-three-ways)

Running the loop in claude.ai, Claude Code, and OpenCode

**4**

[A Complete Worked Example](#part-4-a-complete-worked-example)

One feature, start to finish, in claude.ai then in Claude Code

**5**

[Judgment](#part-5-judgment)

When SDD pays off, when it is overkill, and how to keep a spec alive

The 15-minute spine (if you only have a few minutes)

New to this and short on time? Read Concept 1 (why vibe coding fails), Concept 2 (the spec is the product), Concept 7 (Clarify by interview), the four-prompt block at the end of Part 2, and the [worked example](#part-4-a-complete-worked-example) in Part 4. That is the minimal viable read; everything else deepens it later. When you want the discipline to actually become yours, the [Practice](#practice) ladder at the end is where you run the full loop on something real. (This split is itself an SDD move: the spine is the spec, the rest is the plan.)

* * *

## Part 1: The Shift[​](#part-1-the-shift)

Three ideas reframe how you work with AI. Get these and the rest is mechanics.

### 1\. Vibe coding vs. spec-driven development[​](#1-vibe-vs-spec)

The difference is **when you do the thinking.**

In vibe coding, you think *while* the AI builds, discovering what you actually want by reacting to what it hands you. That feels fast: something appears on screen immediately. But each round trip loses a little context, the AI fills gaps with reasonable-but-wrong assumptions, and the result rarely matches the rest of your project. The cost shows up later, all at once, when you try to change or trust the thing.

In spec-driven development, you do the thinking *first* and write it down. The AI does not start building until you both agree on what "done" means. The build is then mostly mechanical: it is executing an agreement, not guessing at one.

Two loopsVibe codingpromptcode"notquite"No shared "done." Cost lands later.Spec-drivenWrite & agree the specbuildcheck vsspecThinking first. Build executes the agreement.

*Two loops: vibe coding spins between prompt, code, and “not quite”; SDD front-loads the spec, then runs a short build-and-check loop against it.*

This is the same move you learned in prompting (context first, then ask), but with the stakes raised: the AI is now **writing code into your project**, not just answering a question.

**Rule of thumb:** if you would be annoyed to throw the result away, you are past the point where vibe coding is safe. Write the spec.

### 2\. The spec is the product; code is a build output[​](#2-spec-is-the-product)

This is the mental flip that gives SDD its name. For decades the spec served the code: you wrote a brief, built the thing, and discarded the brief. SDD inverts that. **The spec is the durable artifact you maintain; code is generated from it,** and re-generated when the spec changes. "Re-generated" means re-running the build loop over the updated spec and reviewing the result, not pressing a magic compile button: the spec guides a fallible agent you still supervise.

The inversionOLD — code is kingspecguidesCODEspec thrown awayonce coding startsSDD — the spec is kingSPECsource of truthgeneratescode (output)change the spec → re-derive the code.the spec never gets thrown away.

*The inversion: the old way treats the spec as scaffolding for the code; SDD makes the spec the source of truth and code a re-derivable output.*

A good spec answers three questions, in order:

1.  **Why:** what problem are we solving, and for whom? (The thing most vibe sessions never state.)
2.  **What:** what must be true when this is done? Behaviours, inputs, outputs, rules, edge cases, and explicitly **what is out of scope.**
3.  **What *not* to build:** the boundaries. This single section prevents most "it did too much / it did the wrong thing" failures.

Notice what is *missing*: the **how**. A spec describes behaviour, not implementation. "Users can reset a forgotten password via an emailed link that expires in 30 minutes" is spec. "Use a JWT and a Postgres `tokens` table" is implementation, and belongs in the *plan*, a later phase. Mixing the two too early is the most common beginner mistake: you lock in a technical choice before agreeing on the behaviour it is supposed to deliver.

The test for every line of a spec

Ask: *"Could a competent person build the wrong thing and still technically satisfy this line?"* If yes, the line is too vague, so tighten it. A spec is finished not when there is nothing left to add, but when there is nothing left to **misread**.

### 3\. The three levels of SDD[​](#3-three-levels)

SDD is not all-or-nothing. There are three levels, and you choose based on how much the work matters.

Level

What it means

Use it when

**Spec-First**

Write the spec once, up front, then build from it. The spec may drift afterward.

Most features. The default.

**Spec-Anchored**

The spec stays the source of truth; you update it whenever behaviour changes, and re-derive from it.

Anything you will maintain for months.

**Spec-as-Source**

The spec is *the* source; code is fully regenerated from it, treated like a re-derivable output you still re-run and review.

Mature, high-discipline teams and tooling.

For this course, **start at Spec-First and grow into Spec-Anchored.** Spec-as-Source is where the field is heading, but you earn it by mastering the first two. The *discipline* is identical at every level; only how religiously you keep the spec in sync changes.

* * *

## Part 2: The Method[​](#part-2-the-method)

The workflow has one foundation (the constitution) and four phases (Research → Specify → Clarify → Build):

The constitution sits above every phasePHASE 0 — The Constitutionproject-wide rules that guide every spec and build1 · ResearchUnderstand theproblem & theexisting codebefore youdecide anything2 · SpecifyWrite the what& why — and theout-of-scopenever the how3 · ClarifyAI interviewsyou to surfaceambiguitycheapest placeto fix mistakes4 · BuildPlan → Tasks →Implement →Verifyone task at a time,checked vs the specFind a gap while building? Go back, fix the spec, then continue — the spec stays true.

*The method at a glance: the constitution sits above four phases (Research, Specify, Clarify, Build), and any gap found while building sends you back to fix the spec.*

### 4\. The constitution: the rules above every spec[​](#4-the-constitution)

Before any one feature, you write a short document of persistent rules for **all** of them: the **constitution**. In the coding agents it is the rules file (`CLAUDE.md` / `AGENTS.md`); in claude.ai, your **Project instructions**. Same idea everywhere: the principles, constraints, and conventions you want every spec and build to follow.

One honest caveat, because it changes how you use it: a constitution is **persistent context, not enforced law.** The agent loads it every session and follows it more reliably the more specific and concise it is, but "loaded" is not "guaranteed." For rules that must *never* be broken (don't touch production data, never commit secrets), don't rely on the prose alone; back them with tests, pre-commit or tool hooks, CI checks, tightened permissions, or a human reviewing the diff. The constitution sets intent; those mechanisms enforce it.

A constitution is **principles, not an encyclopedia.** It answers "what is always true here?" and not "how does feature X work?" Keep it tight; the AI re-reads it constantly, so bloat is expensive and buries the rules that matter. Good constitution lines look like:

```
# Constitution — Smart Notes## Principles- Plain language over cleverness. A new contributor should understand any file in 5 minutes.- Prefer well-established libraries over custom code. Research before reinventing.- Every feature ships with its spec in `specs/`. The spec is the source of truth.## Constraints- Stack: keep it to what's already here. Propose, don't add, new dependencies.- Never touch `published/` or anything in `src/generated/`.## Definition of done- Behaviour matches the spec, edge cases included.- A human has reviewed the diff against the spec before merge.
```

A too-strict constitution poisons everything downstream

A constitution sets the tone for everything after it: if it demands enterprise-grade testing, performance budgets, and ceremony for a weekend project, **every later phase inherits that weight** and a to-do app turns into a cathedral. Match the constitution to the stakes; you can raise the bar later.

You can watch this happen. Give a weekend habit-tracker a constitution that demands 90% test coverage, a performance budget, and a written decision record for every change, and the first feature ships with a benchmark harness, three layers of abstraction, and a decision log: a week of ceremony for a button that adds a row to a list. Nobody asked for that; the constitution did, and every phase after it inherited the weight.

But the opposite failure is just as common: a constitution so vague it says nothing. Three versions of the same project:

Too light (useless)

Too strict (suffocating)

Just right

"Write clean code. Be consistent. Use best practices."

12 rules on test coverage %, performance budgets, commit-message format, and review ceremony, all for a weekend app

The 6–8 lines above: principles the AI can't infer, constraints that actually bite, one clear "done"

The test for every rule is the same as for every line of a spec: **would removing it let the AI make a mistake?** "Write clean code" fails, because the AI already tries to, so the line does nothing. "Never touch `published/`" passes, because there is no way the AI could have known that on its own.

### 5\. Phase 1: Research before you write[​](#5-research)

You cannot spec what you do not understand. Before writing a line of spec, get the AI to map the territory: the problem, the users, the constraints, and (for an existing project) how the current code works and where the new thing has to fit.

The power move here is **parallel research**: instead of one long back-and-forth, have the AI investigate several questions at once and report back. In a chat you ask for a structured findings document; in the coding agents you do it literally, with **subagents** that each research one area in their own context window and hand back a summary (keeping your main conversation clean, the context discipline from the [Agentic Coding Crash Course](/docs/agentic-coding-crash-course)).

The output is **not** code and **not** yet a spec. It is a short findings document, what exists, the options, the unknowns, and it feeds the spec. A prompt that works in any of the three tools:

> Research what's involved in building **\[feature\]**. Investigate these separately and report each on its own: (1) how this kind of thing is usually done, (2) the main approaches and their trade-offs, (3) anything in our existing project it has to fit, (4) the failure modes and edge cases I should worry about. Give me a one-page findings doc: what exists, the options, and what's still unknown. Don't propose a final design or write any code yet.

### 6\. Phase 2: Write the spec (the *what* and *why*, never the *how*)[​](#6-specify)

Now write the spec, grounded in the research. Do not start from a blank page: draft it *with* the AI, then make it precise. The three questions from Concept 2 (why, what, and what *not* to build) expand into six concrete sections. A workable spec has, at minimum:

-   **Goal:** the why, in two or three sentences.
-   **User scenarios:** "when a user does X, they get Y" walkthroughs.
-   **Functional requirements:** the testable musts, each specific enough to fail a build that ignores it.
-   **Edge cases & rules:** input that is empty, huge, duplicate, malformed, unauthorized.
-   **Out of scope:** what this explicitly does *not* do. Do not skip this.
-   **Acceptance criteria:** the checklist that says "done" (the constitution's project-wide definition of done still applies on top).

Anatomy of a specspec.mdGoalthe why, in 2–3 sentencesUser scenarios"when a user does X, they get Y"Functional requirementsthe testable mustsEdge cases & rulesempty, huge, duplicate, unauthorizedOut of scopewhat this does NOT do — don't skipAcceptance criteriathe checklist that says "done"Not in here: the HOWNo database.No framework.No file layout.All of that is the plan (Phase 4).

*Anatomy of a spec: six sections that describe behaviour and, deliberately, no HOW (that belongs in the plan).*

Draft it with a prompt like this, then tighten by hand:

> Using the research above and our constitution, draft `spec.md` for **\[feature\]**. Include: goal (the why), user scenarios, functional requirements, edge cases & rules, out-of-scope, and acceptance criteria. Describe **behaviour only**, no databases, frameworks, or file layout. Make each requirement specific enough that a build which ignored it would visibly fail.

**What "tighten by hand" means.** The precision test from Concept 2, doing real work. Watch one requirement go from something the AI could satisfy wrongly to something it can only satisfy correctly:

> **Before:** "Users can reset their password."
> 
> **After:** "A signed-out user can request a password reset by email. The link works once, expires after 30 minutes, and a used or expired link shows a 'request a new link' message. The response never reveals whether an email is registered."

The first line would pass a build that emails a plaintext password to anyone who asks. The second can only pass the thing you actually meant. Every detail you leave out, the AI gets to decide for you, so decide the ones that matter, here, in words.

Keeping the spec implementation-free is what lets you change your mind about tooling later without rewriting your intent.

Skip that discipline and the tool choice becomes the requirement by accident. A spec says "store uploads in S3"; the plan and code follow; a month later a compliance deal needs on-prem storage. The behaviour anyone actually cared about (uploads stay durable and retrievable) was never written down, only the vendor was, so switching means a refactor instead of a one-line change to the plan.

### 7\. Phase 3: Clarify by interview (make the AI ask *you*)[​](#7-clarify)

This is the highest-leverage, most-skipped step. Before building, **turn the questioning around**: instead of instructing the AI, have it interview *you* to surface everything the spec left ambiguous. One prompt does most of the work:

> Before we build anything, interview me about this spec. Ask one question at a time, focusing on ambiguities, missing edge cases, and unstated assumptions. Keep going until you could hand this spec to a stranger and trust they'd build exactly what I mean. Don't write any code yet.

You will be surprised how many "obvious" things were never actually stated. Every ambiguity you resolve *here*, in words, is one you do not resolve later by deleting wrong code. This is the cheapest place in the entire process to fix a mistake: fixing it in the spec costs a sentence; fixing it after implementation costs a rebuild.

Skip it and the questions get answered anyway, just later, in code. A team specs "users can upload a profile photo," everyone nods, and it ships. Within a day: someone uploads a 40 MB TIFF (no size or type limit was ever stated), two users overwrite each other's photos (no uniqueness rule), and a broken file renders blank across the site (no fallback). Three unstated assumptions, each one a question the interview would have asked in a single sentence, each now a bug instead.

### 8\. Phase 4: Build from the spec[​](#8-build)

The spec is agreed. Now you build from it, and the amount of process you add scales with the change. There is no fixed pipeline to run every time: do the smallest amount of planning the change needs, then supervise the build against the spec.

-   A change you could describe in one sentence (a typo, one rule, one new field): just ask for it. Skip the plan. Forcing ceremony on a one-line fix is the overkill side of the same mistake.
-   A change where the approach is uncertain, or it touches a few files: plan first. Have the agent propose the approach, and review it before any code.
-   A multi-file or architectural change: the full loop, plan then build then verify, with the work broken into small checkable steps.

Two things stay constant at every size: you review the approach before code, and you check the result against the spec. Verify is never the step you skip.

**Who breaks the work into tasks? The agent does.** This is the part that changed. You do not hand-write a task list. Claude Code and OpenCode plan and decompose the work into their own tracked checklist and work through it, marking each item done as they go. Your leverage is reviewing that breakdown and checking each step against the spec, not authoring it. (In claude.ai, which has no task tool, you capture the plan and tasks as Artifacts yourself: that is the one place the old "write a tasks file" still fits.)

**Plan** (when the change earns it):

> Based on the agreed spec, propose a technical plan: stack, structure, and the key decisions, each with its trade-off. Match our constitution and reuse what already exists rather than adding new dependencies. Don't write code yet; I'll review the plan first.

**Build** (supervised):

> Implement the agreed plan in small, checkable steps. Do one step at a time, and after each, check it against the spec and stop for me to confirm before the next. Commit after each so every step has a clean rollback point.

Plan with a strong model, implement with a cheaper one

The expensive thinking is the plan. Once the approach is agreed, building is "follow the steps," which a cheaper or faster model does well. In the coding agents this is one setting; in claude.ai you do the planning in your most capable chat and keep the spec and plan as the handoff. (Same Plan/Execute split as the [Agentic Coding Crash Course](/docs/agentic-coding-crash-course).)

Close the loop: verify against the spec

Code that runs is not the same as code that does what you agreed. Turn your **acceptance criteria into actual checks** (automated tests where you can write them, a manual run-through where you can't, or a short list of review questions) and run them after each step. If a check fails because the *spec* was vague rather than the code wrong, fix the spec first, then the code. Skip this and SDD quietly degrades into the thing it was meant to prevent: polished documentation next to code nobody has verified.

### Part 2 on one screen[​](#part-2-on-one-screen)

The whole method, copyable. Screenshot the checklist; keep the prompts in a snippet.

**Is my spec done?**

-    **Goal:** the why, in 2–3 sentences
-    **User scenarios:** "when a user does X, they get Y"
-    **Functional requirements:** each one specific enough that ignoring it fails the build
-    **Edge cases & rules:** empty, huge, duplicate, malformed, unauthorized
-    **Out of scope:** what this explicitly does *not* do
-    **Acceptance criteria:** the checklist that says "done"
-    **No HOW:** no database, framework, or file layout (that's the plan)

**The four prompts, in order:**

```
RESEARCH:  Research what's involved in building [feature]. Investigate separately and           report each on its own: (1) how this is usually done, (2) the main approaches           and trade-offs, (3) what in our existing project it must fit, (4) failure modes           and edge cases. One-page findings doc. No design or code yet.SPECIFY:   Using the research and our constitution, draft spec.md for [feature]: goal,           user scenarios, functional requirements, edge cases & rules, out-of-scope,           acceptance criteria. Behaviour only — no tech choices. Make each requirement           specific enough that a build ignoring it would visibly fail.CLARIFY:   Before we build anything, interview me about this spec, one question at a           time — ambiguities, missing edge cases, unstated assumptions — until there's           nothing left to misread. No code yet.BUILD:     Right-size it. Tiny change: just ask. Otherwise: have the agent propose a           plan and review it, then let it build in small steps, checking each against           the spec and committing as you go. Turn acceptance criteria into checks.
```

* * *

## Part 3: The Three Ways[​](#part-3-the-three-ways)

Same constitution, same four phases, three places to run them. We start with **claude.ai** (nothing to install), then the two coding agents.

Tools move; the discipline doesn't

The specific mechanics in this part, keybindings (`Shift+Tab`, `Tab`), slash commands (`/init`, `/undo`), model names, and product features (Projects, Artifacts, Canvas, Gems), are current as of June 2026 and may shift. The four-phase discipline they run does not.

One discipline, three homes for the specConstitution → Research → Specify → Clarify → Buildclaude.aithe main methodspec lives in:Projects + ArtifactsChatGPT & Geminisame loop, other UIClaude Codein your repospec lives in:CLAUDE.md + filesversion-controlled,reviewable in PRsOpenCodein your repo, any modelspec lives in:AGENTS.md + filesplan with a strong model,build with a cheap one

*One discipline, three homes: the same loop runs in claude.ai, Claude Code, and OpenCode; only where the spec lives changes.*

### 9\. Way 1: claude.ai, the main method[​](#9-way-1-claude-ai)

In the web app, your two building blocks are **Projects** (a persistent workspace with custom instructions and uploaded knowledge) and **Artifacts** (editable documents that live beside the chat). SDD maps onto them directly.

**Set up once, the constitution:**

1.  Create a **Project** for your work (e.g. "Smart Notes").
2.  Put your constitution in the Project's **custom instructions**. Upload research, existing docs, or screenshots to **Project knowledge** so every chat in the project can see them.

**Run the four phases, each producing an Artifact:**

-   **Research** → ask Claude to investigate and produce a *findings* Artifact. (No subagents in the web app, so ask for several questions covered in one structured document.)
-   **Specify** → ask Claude to draft `spec.md` as an Artifact. Edit it directly in the Artifact panel until it is right.
-   **Clarify** → paste the interview prompt from Concept 7. Answer the questions; have Claude fold the answers back into the spec Artifact.
-   **Build** → ask for a `plan.md` Artifact, then a `tasks.md` Artifact, then implement task by task. Each code file is its own Artifact you can preview and download.

**Why a Project matters:** the constitution and spec stay loaded across every chat, so you can open a fresh conversation for implementation without re-explaining the project. The Artifacts *are* your spec files; copy them into a repo when you graduate to a coding agent.

ChatGPT and Gemini can run the same discipline

If you prefer another web assistant, the *discipline* carries over even though the mechanics differ. **ChatGPT:** **Projects** for the constitution, **Canvas** as your editable spec/plan documents. **Gemini:** a **Gem** for the constitution, **Canvas** for the documents. The loop (constitution, then Research → Specify → Clarify → Build) is the same; only the buttons, and how persistent each "project" memory is, differ. claude.ai is our default because Artifacts + Projects map most cleanly onto spec files, but nothing here is Claude-only.

Before you paste anything into a browser tool

A chat window is easy, which is exactly the risk. Don't upload private source code, customer data, secrets, credentials, or confidential business material into any web assistant unless your organization's policy allows it. For sensitive work, run a repo-based agent inside your approved environment and use sanitized, fictional examples (as the Smart Notes feature below does). The discipline is the same; the data boundary is not.

### 10\. Way 2: Claude Code, the discipline in your repo[​](#10-way-2-claude-code)

When your project is real software, Claude Code removes the copy-paste: spec, plan, and tasks live as files in your repo, next to the code they generate. The native features below are all you need, no extra frameworks. What it adds over the chat loop is built-in machinery for each phase:

-   **The constitution is a file Claude reads every session.** `CLAUDE.md` loads at the start of every conversation, so you re-paste nothing, but treat it as persistent guidance, not a hard guarantee (back must-never rules with hooks or tests, per Concept 4). Run `/init`, then trim to real rules.
-   **Plan mode is your Specify/Clarify gate, enforced.** `Shift+Tab` into plan mode puts Claude in read-only: it can study your code and draft the spec, but cannot write a line until you approve. That is "agree before you build," built into the tool.
-   **Subagents do parallel research without polluting your context.** Each investigates one area in its own window and hands back only a summary, so Phase 1 stays fast and your main session lean.
-   **The agent maintains its own task list; you supervise it.** Once you approve the plan, Claude breaks the work into its own tracked checklist and works through it, marking each item done as it goes. You do not author that list; your job is to review the breakdown, then after each step run the relevant checks against the spec and commit before the next, so every step has a clean rollback point. That commit-after-each rhythm is a workflow you drive (and can bake into the constitution); if it must happen every time, enforce it with a hook.

Because all four artifacts are plain files, your spec is now under version control: you can diff it, review it in a pull request, and see exactly when behaviour was supposed to change. That is the jump from "a spec I wrote once" to "a spec that governs the repo." The deep-dive [Chapter 16](/docs/General-Agents-Foundations/spec-driven-development) teaches this native path in full.

### 11\. Way 3: OpenCode, any model[​](#11-way-3-opencode)

Everything in Concept 10 applies to OpenCode too: the rules file (`AGENTS.md`) as the constitution (OpenCode also reads an existing `CLAUDE.md` when there is no `AGENTS.md`), **Plan** mode (`Tab`) as the read-only gate, subagents for research, and a git-backed `/undo` between build steps. As in Claude Code, the agent self-tracks its task list and works through it while you review the breakdown and check each step against the spec; `Tab` toggles into **Build** mode once you approve. The one thing OpenCode adds is **model choice**, which pairs with SDD's natural split: the spec and plan phases reward a strong reasoning model, while building a clear, agreed task list runs fine on a cheap one like `deepseek-v4-flash`. You decide where every dollar of "thinking" goes. (Setup details for both agents are in the [Agentic Coding Crash Course](/docs/agentic-coding-crash-course).)

* * *

## Part 4: A Complete Worked Example[​](#part-4-a-complete-worked-example)

### 12\. One feature, start to finish, twice[​](#12-worked-example)

Let us run the whole loop on a small, real feature: **a "weekly digest" that emails each user a summary of their notes every Monday.** It touches several files (a scheduled job, the notes query, the mailer), so by the right-sizing rule from Concept 8 it earns the full loop. We do it **twice**: first in claude.ai, where the thinking is visible, then in Claude Code, where the loop runs against real files in a repo.

**In claude.ai**

**Phase 0: Constitution (already set in the Project).** Principles: plain language, prefer existing libraries, every feature ships with a spec, never touch `published/`.

**Phase 1: Research.** Prompt:

> Research what's involved in a "weekly digest email" for our notes app. Cover: how we'd select which notes to include, scheduling options, email-sending approaches, and the main failure modes (no notes that week, send failures, time zones). Give me a one-page findings doc. Don't propose a final design yet.

Claude returns a findings Artifact. You skim it; the time-zone question is one you had not considered.

**Phase 2: Specify.** Prompt:

> Using those findings and our constitution, draft `spec.md` for the weekly digest. Include goal, user scenarios, functional requirements, edge cases, out-of-scope, and acceptance criteria. Describe behaviour only, no tech choices yet.

You get a spec Artifact. It is good, but generic in places.

**Phase 3: Clarify.** Prompt:

> Before we plan anything, interview me about this spec, one question at a time, until there's nothing left to misread.

The interview surfaces decisions you never stated: digests use the user's local Monday, not UTC; a week with zero notes sends nothing rather than an empty email; unsubscribed users are skipped. You answer; Claude folds each answer into the spec Artifact. *This is the moment SDD earns its keep*: three future bugs just died as sentences.

**Phase 4: Build.**

> Now write `plan.md`: the technical approach for this spec, given our existing stack. Then `tasks.md`: an ordered, checkable task list.

You review the plan (it reuses your existing mailer, matching the constitution), approve it, then implement task by task, checking each against the spec and saving as you go. When a task reveals the spec was silent on something (say, the email subject line), you **update the spec first**, then continue. The spec stays true.

**The same feature, in Claude Code**

Same four phases, same prompts; what changes is that every artifact is a **file** and the tool enforces the gates you self-imposed in the browser.

-   **Research:** instead of one findings doc, spin up **subagents**, one per area, so your main session stays lean. Findings land in `specs/weekly-digest/research.md`.
-   **Specify:** `Shift+Tab` into **plan mode** (read-only): the "don't build yet" rule, now enforced by the tool, not your willpower.
-   **Build:** Claude plans the work into its own tracked task list and builds through it; you review each step against the spec and commit after each, so `git log` reads like that task list and every step is a clean rollback point.

The one real difference is where the spec ends up: in claude.ai it lived in an Artifact you copy forward; in Claude Code it lives in `specs/`, version-controlled next to the code it produced. (OpenCode is identical: swap `CLAUDE.md` for `AGENTS.md` and `Shift+Tab` for `Tab`.)

The result is not just working code; it is working code **plus a spec that explains and governs it**, ready for the next person (or the next you) to change safely. For more practice like this, see the deep dive's [SDD Exercises](/docs/General-Agents-Foundations/spec-driven-development/sdd-exercises).

See the shape of the artifacts: a compact `spec.md`, `plan.md`, and `tasks.md`

The method is abstract until you see what falls out of it. Here are trimmed versions of the three artifacts, written out so you can see the shape. In claude.ai you create all three as Artifacts; with a coding agent you keep `spec.md` and `plan.md` as files, while the task list is usually the agent's own (written out here so a good one is visible). Real ones are longer; the shape is what matters.

```
# spec.md — Weekly Digest## GoalEmail each user a once-a-week summary of their own notes so theyre-engage without opening the app. Reduce silent churn.## User Scenarios- A user with notes this week gets a Monday-morning digest listing them.- A user with no notes this week gets nothing (not an empty email).- An unsubscribed user gets nothing, ever.## Functional RequirementsFR-1 Digest sends on the user's local Monday at 8:00am.FR-2 Include only notes created or edited in the prior 7 days.FR-3 Zero qualifying notes → no email is sent.FR-4 Unsubscribed users are skipped.FR-5 A send failure is retried once, then logged; it never blocks others.## Edge Cases & Rules- Time zone missing → fall back to UTC.- 50+ notes → list the 10 most recent, then "and N more."## Out of Scope- Digest customization, frequency options, non-email channels.## Acceptance Criteria- [ ] A user in Asia/Karachi receives the digest at their local Monday 8am.- [ ] An empty week sends no email (verified in logs).- [ ] Unsubscribed users receive nothing.- [ ] One simulated send failure retries once, then logs, others still send.
```

```
# plan.md — Weekly Digest## ApproachReuse the existing mailer service (constitution: prefer what exists).A scheduled job runs hourly, selects users whose local time is Mon 08:00,builds the digest from the notes query, and hands it to the mailer.## Key Decisions- Scheduling: hourly cron + per-user timezone check (no per-user timers).- Templating: reuse existing email template system.- Failure handling: wrap each send; retry-once lives in the job, not the mailer.## Touch Points- new: jobs/weekly_digest.\* | reuse: services/mailer, models/note- no schema change required
```

```
# tasks.md — Weekly Digest1. Note-selection query: notes per user from the last 7 days. [FR-2]2. Eligibility check: local Monday 08:00 + subscribed. [FR-1, FR-4]3. Digest builder: top 10 + "and N more"; skip if empty. [FR-3, edge]4. Wire to mailer with retry-once + logging. [FR-5]5. Tests for each acceptance criterion. [Verify]
```

Notice the threads: every task cites the requirement it satisfies, and the final task is verification, derived straight from the acceptance criteria.

* * *

## Part 5: Judgment[​](#part-5-judgment)

### 13\. When SDD pays off, and when it is overkill[​](#13-when-to-use-sdd)

SDD is a discipline, and discipline has a cost: expect Specify and Clarify to feel slow, tens of minutes of thinking where vibe coding would already be showing you code, and know that gap is exactly the trade you are making (beginners abandon the method at the moment it feels worst, right before it pays). Spending it on a one-line fix is as wrong as skipping it on a payment system. The skill is knowing which is which.

Reach for SDD when…

Skip it (just vibe) when…

The work touches multiple files, modules, or data

It is a one-off script or a tiny tweak

Someone else (or future-you) will maintain it

You will throw the result away today

Getting it wrong is expensive (money, data, trust)

The cost of a wrong guess is "press undo"

Requirements are fuzzy and need to be pinned down

The task is fully clear in one sentence

Several people need to agree on what "done" means

You are exploring to *learn* what you even want

Running *"make this button blue"* through the full constitution-to-implement ceremony is absurd. But the moment a task involves state, permissions, data models, money, or anyone else's expectations, the structure starts paying for itself, and it pays more the longer the thing lives.

Where the threshold sitslower stakeshigher stakesthe threshold← Just vibe itone-line fixthrowaway scriptexploring to learnWrite the spec →multi-file featureanything maintainedmoney · data · permissionsThe line sits low on purpose — most work you actually keep lands on the right.

*The threshold sits low on purpose: tiny throwaway work stays on the left, but most work you keep lands on the right, where a spec pays off.*

There is a second payoff beyond getting it right the first time: it gets you *unstuck*. In Anthropic's session data, when a build went sideways, the least-experienced users gave up, abandoning troubled sessions at several times the rate of everyone else; what experience mainly bought was the ability to steer the agent back on track. A spec you have already agreed on is that steering wheel: when something breaks, you have a fixed point to debug against instead of a vague memory of what you wanted. The recovery move is concrete: when the agent drifts from the spec mid-build, re-ground it by pasting the specific requirement it ignored (the FR), shrinking the task to just that one thing, then pointing it back at the acceptance criteria.

**Keep the spec alive (the part everyone forgets).** A spec is only the source of truth if it stays true. When behaviour changes (a new rule, a removed feature, a fixed edge case), change the **spec first**, then re-derive the code. This is the move that turns Spec-First into Spec-Anchored, and it is the difference between a spec that compounds in value and one that becomes a lie in your repo within a month.

What drift looks like in practice: someone tweaks the digest email's subject line directly in the code and ships it. The spec still describes the old subject. Three weeks later a new teammate reads the spec, "fixes" the code to match it, and quietly breaks the thing that was working. Nobody lied; the spec just stopped being true, and it cost a bug to find out. The fix is cheap and boring: the change goes into `spec.md` in the same commit as the code, every time.

**What changes when you have many specs.** One spec is a document; a folder of dozens is a system. With a whole `specs/` directory, the live question stops being "is this spec clear?" and becomes "do these specs still agree?" Features interact, so a change to one can ripple into others, and when two specs imply conflicting choices the constitution is the arbiter that settles it. Keeping the corpus coherent as it grows is the real jump from "I can spec a feature" to "I run a repo on SDD."

* * *

## Practice[​](#practice)

Reading SDD is not learning SDD. The discipline only becomes yours once you have run the full loop on something real and felt the Clarify phase catch a mistake you would otherwise have shipped. Do these in order. Each one raises the stakes, and each is deliberately past the "just vibe it" line so the structure has to earn its keep.

For every project, produce the same four artifacts (**constitution**, **`spec.md`**, **`plan.md`**, **`tasks.md`**) plus the working result. The single success test is the one from Concept 2: *could a stranger build the right thing from your spec alone, without asking you a single question?*

**Warm-up: feel the interview (claude.ai, ~30 min).** Pick the smallest real thing you have been meaning to build: a study planner, a CSV-to-summary tool, a habit tracker. Make a Project, paste a three-line constitution, and run all four phases. The one rule: **do not skip Concept 7.** Make Claude interview you before any code. Count how many decisions surface that you never thought to state. That number is why SDD exists.

**Project 1: a feature with real rules (claude.ai, ~1 hr).** Spec and build a **"tag and filter" feature for Smart Notes** (the app from the worked example): users add tags to notes and filter by them. It sounds trivial until you spec it, and that is the point. Force yourself to pin down the edge cases in the spec: What happens with no tags? Duplicate tags? A filter that matches nothing? Case sensitivity? Renaming a tag that is in use? **Done when** your spec answers all five before you write a line of implementation.

**Project 2: move it into a repo (Claude Code or OpenCode, ~2 hrs).** Take Project 1 out of the chat window and run the same loop in a coding agent. Put the constitution in `CLAUDE.md` / `AGENTS.md`, keep `spec.md`, `plan.md`, and `tasks.md` as files in the repo, and use plan mode as your specify/clarify gate. Implement **one task at a time, committing after each.** **Done when** `git log` shows one clean commit per task and the spec lives in version control next to the code it produced.

**Project 3: keep the spec alive (the hard one, ~1 hr).** Now change your mind. Add a new requirement to Project 2: say, *tags can be colour-coded*, or *filtering supports "any of" and "all of" modes.* Resist the urge to just tell the agent to add it. Instead: **edit `spec.md` first**, re-run Clarify on the changed section, update the plan and tasks, then implement. **Done when** the diff on `spec.md` and the diff on the code tell the same story. This is the move that turns Spec-First into Spec-Anchored, and it is the one most people never practise.

**Project 4: work inside code you didn't write (Claude Code or OpenCode, ~2 hrs).** Greenfield is the easy case. Clone any small open-source project you've never seen, or pick up someone else's repo, and add one modest feature using SDD. This time **Phase 1 carries the weight**: before you spec anything, make the agent research how the existing code is structured, where your feature has to fit, and what conventions it must respect; use subagents so each maps one area and reports back. Your spec must include a "fits the existing system" section that names the patterns you're matching. **Done when** your feature reads like it was always part of the codebase, not bolted on, and your spec explains *why* it fits.

**Project 5: SDD with no code at all (claude.ai, ~45 min).** Prove to yourself this is a thinking discipline, not a coding one (Concept "not a programmer"). Pick a repeatable *process*, not an app: a weekly status report assembled from raw notes, a content-repurposing pipeline, an inbox-triage routine, a grading rubric applied to submissions. Run the exact same loop (constitution, research, spec, clarify, build) where "build" produces the **process and its prompts**, not source code. **Done when** you (or a teammate) can run the process from the spec and get a consistent result every time, no improvisation.

**Project 6: the stranger test, for real (capstone, ~1.5 hrs).** Everything so far you checked yourself, which is the weakest possible reviewer; you know what you meant. So remove yourself. Write a spec for a feature, then hand it to a **fresh, empty AI session** (a brand-new chat with no memory of your discussion) or to a peer, and have them build it with **zero questions allowed.** Wherever they build the wrong thing, the fault is the spec's, not theirs: fix the spec, not the code, and try again. **Done when** a cold reader builds what you actually meant on the first pass. Pass this and you have the real skill: writing intent precisely enough that it survives leaving your head.

Stuck or want more reps?

The deep dive has a graded set in [SDD Exercises](/docs/General-Agents-Foundations/spec-driven-development/sdd-exercises).

* * *

## Where this leads[​](#where-this-leads)

You now have the whole discipline: agree on the *what* before you generate the *how*, keep the spec as the source of truth, and run the constitution → Research → Specify → Clarify → Build loop in whichever of the three tools fits the moment.

This is the thinking layer under everything else in the book. You met the coding tools that run this loop, Claude Code and OpenCode, in the [**Agentic Coding Crash Course**](/docs/agentic-coding-crash-course), and saw the discipline at work in the [**Cowork Crash Course**](/docs/cowork-crash-course); revisit either for the mechanics in depth. From here, the Mode tracks put this loop to work: every build course you take, [Python in the AI Era](/docs/python-crash-course), [Build AI Agents](/docs/build-agents-crash-course), [AI Searchable Context](/docs/postgres-ai-crash-course), and [Building a Digital FTE](/docs/digital-fte-crash-course), is just this same loop, applied to bigger and bigger systems.

Remember the thesis of the whole book: **General Agents build Custom Agents.** Spec-Driven Development is *how* you point a general agent at a hard problem and get a reliable system back instead of a pile of guesses.

* * *

## Flashcards Study Aid

In AI-assisted building, what is vibe coding?

Click to flip

1 / 30 cards

Space flip1 missed2 got it←→ navigateEsc exit

[ⓘ Guide](/guide#flashcards "How flashcards work")

* * *

## Test Your Understanding

Test what you learned. Each session shows a fresh set of 18 questions, so you get new questions every time you retake it.

## Spec-Driven Development Crash Course Assessment

Question 1 of 18

### Why implement one task at a time and commit after each?

Answered: 0 / 18

You are on the first question. Cannot go back.Please answer the question first to proceed to the next question.

---
Source: https://agentfactory.panaversity.org/docs/spec-driven-development-crash-course