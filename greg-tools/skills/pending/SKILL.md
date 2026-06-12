---
name: pending
description: Use when the user wants to check for uncommitted changes, open GitHub issues, unfinished action items, or any loose ends from the current conversation
---

# Pending Next Steps

Check for any unfinished work or loose ends in the current conversation and working directory.

## Checks to Perform

1. **Uncommitted git changes** - Run `git status` and `git diff --stat` to find staged/unstaged changes or untracked files that should be committed.

2. **GitHub issues discussed** - Review the conversation for any GitHub issues that were referenced, created, or investigated. Check if they need labels updated, descriptions edited, or should be closed. List each with its current status.

3. **Pull requests** - Check if there are changes on a feature branch that need a PR created. Run `git log --oneline main..HEAD` if on a non-main branch.

4. **Conversation action items** - Review the full conversation for any tasks the user mentioned, agreed to, or that were identified as needed but not yet done. This includes cleanup tasks, deployments, re-runs, file deletions, config changes, etc.

5. **CHANGELOG updates** - If code was changed in any service directory, check whether the corresponding `CHANGELOG.md` was updated.

## Output Format

**Start with a one-line verdict** indicating whether there are pending items:
- If nothing is pending: `**Status: All clear — no pending items.**` and stop. Do not list completed items.
- If something is pending: `**Status: N pending item(s).**` followed immediately by the pending items at the top.

Only list items that are actually pending. Completed work is not a pending item — omit it. The exception: if a completed action this session has a non-obvious follow-up implication worth surfacing, include it as a pending item, not as a `[x]` line.

Group pending items by category (Git, GitHub Issues, PRs, Action Items, Changelog). Use `- [ ]` bullets.

Example (pending):
```
**Status: 3 pending items.**

### Git
- [ ] 2 files modified but not committed (src/main.py, src/config.py)

### GitHub Issues
- [ ] #1213 — still needs investigation

### Action Items
- [ ] Re-trigger pipeline after Stage 5 fix deploys
```

Example (clean):
```
**Status: All clear — no pending items.**
```
