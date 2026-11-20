# Agent factory

Tooling that runs AI coding agents unattended on a repository, one ticket at a time, while the owner sets standards and reviews.

## Language

**Factory**:
The kit plus the repositories it works on.
_Avoid_: Pipeline, orchestrator

**Ticket**:
One unit of work with acceptance criteria, handed to one fresh agent.
_Avoid_: Task, issue (when the tracker is not GitHub)

**Tracker**:
The single place a repository's tickets live, chosen per repository and never duplicated across two. GitHub Issues by default; beads only for the stock project.
_Avoid_: Backlog, board

**Gate**:
The one script whose pass or fail decides whether a ticket's work is accepted.
_Avoid_: CI (unless it is literally a hosted service), tests

**Frontier**:
The tickets that are ready: unblocked, marked safe for an agent, not already claimed, and not an epic.
_Avoid_: Queue, backlog

**Epic**:
A ticket that other tickets name as their parent, such as a PRD. It groups work and is never built itself.
_Avoid_: Parent ticket, umbrella

**Integration branch**:
The long-running branch every ticket merges into, kept apart from main until the owner merges it.
_Avoid_: Develop, trunk

**Ticket branch**:
The branch one ticket's work is built on, kept after merging as the record of that ticket.
_Avoid_: Feature branch, PR branch

**Attempt**:
One fresh agent session working one ticket; a ticket that fails its gate twice is blocked for a human.
_Avoid_: Run, try

**Loop**:
The unattended cycle that claims a ready ticket, runs an agent on it, applies the gate, and repeats until a stop condition.
_Avoid_: Run (for the whole cycle), pipeline

**Done**:
A ticket is done when the agent has built it test-first, reviewed its own diff against the ticket, and the gate passes on the ticket branch and again after merging.
_Avoid_: Finished, complete

**Dashboard**:
The one local page that shows every repository's tickets, issues, pull requests and agent branches, updating while the owner watches.
_Avoid_: Board, report

**Source**:
One origin of dashboard data: the tracker, GitHub, or the local branches. Each Source has its own age and can fail without affecting the others.
_Avoid_: Feed, provider

**Stale**:
A Source whose latest refresh failed, so the Dashboard shows its last good data marked with its age rather than empty.
_Avoid_: Broken, offline

## Relationships

- A **Tracker** holds many **Tickets**; each repository has exactly one **Tracker**
- A **Ticket** is built on exactly one **Ticket branch** and merges into the **Integration branch**
- The **Gate** is applied twice per **Ticket**: on the **Ticket branch**, then after the merge
- The **Loop** only picks **Tickets** from the **Frontier**, and may work several at once because a **Ticket** only enters the **Frontier** when its blockers are done

## Example dialogue

> **Dev:** "The agent says the **Ticket** is built. Can the **Loop** close it?"
> **Owner:** "Only once it is **Done**: reviewed against the ticket, and the **Gate** passes on the **Ticket branch**. Then it merges, and the **Gate** runs again on the **Integration branch**."
> **Dev:** "And if the agent committed nothing?"
> **Owner:** "That is a failure, not a pass. The **Gate** passing on unchanged code proves nothing."

## Flagged ambiguities

- "CI" was used for both the **Gate** script and a hosted service — resolved: the **Gate** is the local script; hosted CI is a separate thing and is not the judge here.
- "run" was used for both a single agent invocation and the whole **Loop** — resolved: a **Loop** is the whole cycle; one agent invocation is just that.
