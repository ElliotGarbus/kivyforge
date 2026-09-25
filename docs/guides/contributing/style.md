---
title: Documentation style
sources:
  - AGENTS.md
---

# Documentation style

These guides follow the conventions of Google's developer documentation. This
page is the rulebook. Read it before you write or edit a page.

## Source of truth

The design documents under `docs/design/` are the source of truth for how
kivyforge behaves. These guides *distill* that behavior into day-to-day tasks;
they do not restate the rationale. A second copy of a fact is a copy that goes
stale.

- Every page carries a `sources:` list in its front-matter, naming the design
  documents it was derived from. This is metadata for maintainers. It is not
  rendered, and site pages never link into `docs/design/` because those files
  are not published.
- Anything that can be generated is generated, not copied: the CLI reference,
  the exit-code and `KF-*` tables, and the host matrix all come from
  kivyforge's own code through `docs/hooks/kf_generated.py` and `mkdocs-click`.
- Pages describe the latest release on PyPI. Behavior that exists on `main` but
  has not been released yet is marked with a "Preview" note (see below).

## Voice and grammar

- Address the reader as "you". Use present tense and active voice.
- Write headings in sentence case: "Sign an Android app", not "Signing An
  Android App".
- Task headings start with a bare verb: "Run the app on a device", not
  "Running the app".
- Keep sentences short. Prefer a period to a semicolon.
- Link text is descriptive. Never write "click here" or "this link".

## Page types

Every page is one of four types. Say which one it is by how you structure it.

Concept
:   Explains how something works and why it matters. No numbered steps.

Task (how-to)
:   Gets one job done. Uses the task skeleton below.

Tutorial (quickstart)
:   Takes the reader end to end, from nothing to a running result.

Reference
:   Lists facts to look up. Tables, not prose.

## The task-page skeleton

A task page follows this fixed shape:

1. A one-paragraph introduction: what the reader will accomplish.
2. **Before you begin**: prerequisites, as a short list.
3. Numbered steps. One action per step.
4. **Verify** (or **Expected output**): how the reader knows it worked.
5. **What's next**: two or three links to the logical follow-ups.

## Admonitions

Use only these four Material admonition types:

```markdown
!!! note
    Neutral, useful aside.

!!! tip
    A shortcut or a better way.

!!! warning
    Something that will bite the reader if ignored.

!!! danger
    Data loss, irreversible actions, or a security risk.
```

Write a "Preview" as a titled note:

```markdown
!!! note "Preview"
    This describes behavior that is on `main` but not yet in a released
    version. It will ship in a future release.
```

## Code and commands

- Every code block is copyable. Do not include shell prompt characters
  (`$`, `>`, `PS>`).
- Placeholders use `UPPER_SNAKE_CASE` and are explained immediately after the
  block.
- Where a command differs by operating system, show both in content tabs:

```markdown
=== "PowerShell"
    ```powershell
    kivyforge build -p windows
    ```

=== "bash"
    ```bash
    kivyforge build -p linux
    ```
```

- Product output belongs on stdout; progress and tool logs go to stderr. When
  you show expected output, show only what the reader will actually see.

## Cross-linking

- Pages do not repeat each other. Link instead.
- Every task and concept page ends with a "What's next" section.
- Use relative links between pages (`../reference/cli.md`), never an absolute
  site URL. The site moves hosts over time, and relative links survive the move.

## What's next

- [How kivyforge works](../concepts/how-it-works.md)
- [CLI reference](../reference/cli.md)
