Date created: 2026-06-15
Date last updated: 2026-06-15

# Purpose

This folder packages the `babysit-pr` agent command as a shareable, repo-neutral skill.

# What It Does

`babysit-pr` takes an open GitHub pull request from "created" to "ready for human merge":

- Trigger an automated review only when the current PR head has not already been reviewed.
- Poll for both review shapes: formal PR reviews and plain issue-comment verdicts.
- Fix valid review comments, decline invalid or low-value comments with reasoning, and push the smallest correct patch.
- Re-run review only after new commits.
- Resolve merge conflicts with the base branch without rebasing or force-pushing.
- Add a `ready_to_merge` label and handoff comment.
- Watch briefly for late automated reviews after handoff.
- Never merge the PR.

# Install

Copy `SKILL.md` into an agent skill directory named `babysit-pr`.

For Codex-style local skills:

```bash
mkdir -p ~/.agents/skills/babysit-pr
cp SKILL.md ~/.agents/skills/babysit-pr/SKILL.md
```

For Claude-style local skills:

```bash
mkdir -p ~/.claude/skills/babysit-pr
cp SKILL.md ~/.claude/skills/babysit-pr/SKILL.md
```

# Prerequisites

- GitHub CLI installed and authenticated: `gh auth status`
- Local `git` checkout of the target repository
- Permission to comment on PRs, push to the PR branch, create labels, and resolve review threads
- Automated GitHub reviewer installed/enabled for the target repository; the default skill uses `chatgpt-codex-connector[bot]`

# Invocation

Use natural language:

```text
babysit PR 123
```

```text
take this PR through review
```

```text
babysit the open PRs
```

# Operating Contract

- The agent may autonomously edit, commit, push, comment, and resolve handled review threads.
- The agent must not merge.
- The final human gate is the pull request merge button.
- The agent must leave unresolved any review comment it did not actually handle.
