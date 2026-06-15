---
name: babysit-pr
description: Drive one or more open GitHub pull requests through the post-PR review loop until ready for final human merge. Triggers automated review only when needed, waits for review verdicts, fixes valid comments, declines invalid comments with reasoning, resolves merge conflicts without rebasing or force-pushing, labels ready_to_merge, and never merges.
---

# Babysit PR

Take an open GitHub pull request from "created" to "ready for final human merge".
Works in any repository where the local checkout can use `git` and authenticated
`gh`.

## Hard Rules

- Never merge the PR. Do not run `gh pr merge` or any merge mutation.
- Never rebase or force-push the PR branch. Sync with the base branch via merge
  commits only.
- Run review follow-through autonomously: fix valid comments, decline invalid
  comments, commit, push, reply, and resolve only handled threads.
- Maximum 3 requested review rounds. If actionable comments remain after round
  3, stop and report the open items.
- Never re-trigger a clean review. Only post a review request when the current
  PR head differs from the latest automated-review commit.

## Scope

Decide single vs. multi from the invocation:

- Specific PR: `babysit PR 123`, `babysit this PR`, or `take this PR through review`.
- Multiple PRs: `babysit the open PRs` or `babysit all my PRs`.

For multiple PRs:

```bash
gh pr list --state open --author "@me" --json number,title,headRefName --jq '.[]'
```

Drop `--author "@me"` only if the requester explicitly means every open PR in
the repository. For 2 or more PRs, process one worker per PR concurrently when
the agent environment supports sub-agents or parallel workers. Each worker must
follow this same skill for one PR only. Aggregate final state per PR: rounds,
fixed, declined, conflicts, checks, and final status.

## 0. Resolve Repo And PR

```bash
OWNER_REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
```

Resolve the PR number from the argument, URL, or current branch:

```bash
gh pr list --head "$(git branch --show-current)" --json number,title --jq '.[0]'
```

Stop if no PR is found. Confirm it is open:

```bash
gh pr view <PR> --json state,title,headRefName,baseRefName,headRefOid
```

The automated reviewer identity defaults to:

```text
chatgpt-codex-connector[bot]
```

If the repository uses a different automated reviewer identity or trigger phrase,
substitute that login and trigger consistently below.

## 1. Trigger Review With Clean-HEAD Guard

Record the trigger point:

```bash
TRIGGER_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
HEAD_SHA=$(gh pr view <PR> --json headRefOid --jq .headRefOid)
LAST_REVIEWED_SHA=$(gh api repos/<OWNER>/<REPO>/pulls/<PR>/reviews \
  --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]")] | last | .commit_id // ""')
```

Only post a review request when the reviewer has not already reviewed the current head:

```bash
if [ -n "$LAST_REVIEWED_SHA" ] && [ "$LAST_REVIEWED_SHA" = "$HEAD_SHA" ]; then
  echo "Current HEAD already reviewed; skipping redundant trigger."
else
  gh api repos/<OWNER>/<REPO>/issues/<PR>/comments -f body="@codex review" --jq .html_url
fi
```

## 2. Wait For The Verdict

Poll for both delivery shapes:

- Formal PR review: `pulls/<PR>/reviews`
- Plain issue-comment verdict: `issues/<PR>/comments`

Clean no-issue verdicts often arrive only as issue comments.

```bash
end=$((SECONDS+900))
while [ $SECONDS -lt $end ]; do
  reviews=$(gh api repos/<OWNER>/<REPO>/pulls/<PR>/reviews \
    --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]") | select(.submitted_at > "'$TRIGGER_ISO'")] | length')
  comments=$(gh api repos/<OWNER>/<REPO>/issues/<PR>/comments \
    --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]") | select(.created_at > "'$TRIGGER_ISO'")] | length')
  [ "$reviews" -gt 0 ] || [ "$comments" -gt 0 ] && exit 0
  sleep 60
done
exit 1
```

If the reviewer does not respond within 15 minutes, post `@codex review` one more time
and wait another 15 minutes. If it still does not respond, stop and report that
the reviewer may not be installed or enabled.

## 3. Clap Back Autonomously

Fetch the verdict, inline comments, and issue-comment verdicts:

```bash
gh api repos/<OWNER>/<REPO>/pulls/<PR>/reviews \
  --jq '.[] | select(.user.login=="chatgpt-codex-connector[bot]")'
gh api repos/<OWNER>/<REPO>/pulls/<PR>/comments --paginate \
  --jq '.[] | select(.user.login=="chatgpt-codex-connector[bot]") | {id,path,line,body,created_at}'
gh api repos/<OWNER>/<REPO>/issues/<PR>/comments --paginate \
  --jq '.[] | select(.user.login=="chatgpt-codex-connector[bot]") | {body,created_at}'
```

Only consider comments after `TRIGGER_ISO` for the current round. For every
comment:

- Fix valid correctness, clarity, performance, or maintainability issues.
- Decline invalid comments or low-value nitpicks with a concise reply.
- If the suggested fix is wrong but the critique is valid, make the right fix.
- Read referenced files before judging the comment.

After fixes:

```bash
git status --short
# run focused tests, lint, build, or repo verifier as appropriate
git add <files>
git commit -m "fix: address Codex review round <N> on PR #<PR>"
git push
```

Reply on fixed and declined threads. Resolve only threads actually handled.
Post one round summary on the PR:

```markdown
## Review round <N> addressed

### Fixed
- <item>: <what changed>

### Declined
- <item>: <why>

### Validation
- <command>: <result>
```

If the verdict has zero actionable comments and no code was pushed, do not
trigger another review. Continue to readiness checks.

## 4. Re-Review Loop

Only return to step 1 if step 3 pushed code changes. Repeat until the reviewer returns
zero actionable comments or the 3-round cap is reached.

Do not request review again after a clean verdict, declined-only verdict, or any
round where the PR head did not change.

## 5. Sync With Base And Resolve Conflicts

Check mergeability:

```bash
gh pr view <PR> --json mergeable,mergeStateStatus,headRefName,baseRefName
```

If conflicting:

1. Reuse an existing worktree for the PR branch if available.
2. Otherwise fetch the head branch and create a sibling worktree.
3. Merge the base branch into the PR branch with `--no-commit --no-ff`.
4. Resolve conflicts, commit, and push.
5. If conflict resolution touched meaningful logic, run one more review round.

Example:

```bash
git fetch origin <HEAD_BRANCH>
git worktree add ../<repo>--<head-branch> <HEAD_BRANCH>
git -C ../<repo>--<head-branch> fetch origin
git -C ../<repo>--<head-branch> merge origin/<BASE_BRANCH> --no-commit --no-ff
# resolve conflicts
git -C ../<repo>--<head-branch> commit -m "Resolve merge conflicts: merge origin/<BASE_BRANCH> into <HEAD_BRANCH>"
git -C ../<repo>--<head-branch> push
```

## 6. Readiness And Handoff

Before declaring ready, verify:

- Latest automated-review verdict has zero unaddressed actionable comments.
- Every handled inline thread has a reply and is resolved.
- Mergeability is clean.
- Required checks are green or there are no required checks.

```bash
gh pr checks <PR>
```

Ensure the label exists and apply it:

```bash
gh label list --json name -q '.[].name' | grep -qx 'ready_to_merge' || \
  gh label create ready_to_merge --description "Review loop done; awaiting human merge" --color "0e8a16"
gh pr edit <PR> --add-label ready_to_merge
```

If `gh pr edit` fails because of repository metadata issues, use the issues API
label endpoint instead.

Post a handoff comment:

```markdown
## Ready for final review

- Review rounds: <N>
- Fixed: <count>
- Declined: <count>
- Conflicts: <none/resolved>
- Checks: <green/no required checks>

Awaiting human merge.
```

## 7. Late-Review Watch

After handoff, watch for a late automated-review verdict for 15 minutes, polling every 3
minutes. Check both formal reviews and issue comments.

```bash
LAST_HANDLED_ISO=<timestamp-of-latest-handled-verdict>
watch_end=$((SECONDS+900))
while [ $SECONDS -lt $watch_end ]; do
  sleep 180
  new_rev=$(gh api repos/<OWNER>/<REPO>/pulls/<PR>/reviews \
    --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]") | select(.submitted_at > "'$LAST_HANDLED_ISO'")] | length')
  new_com=$(gh api repos/<OWNER>/<REPO>/issues/<PR>/comments \
    --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]") | select(.created_at > "'$LAST_HANDLED_ISO'")] | length')
  [ "$new_rev" -gt 0 ] || [ "$new_com" -gt 0 ] && exit 0
done
exit 1
```

If a late verdict lands, process it through step 3, then return to readiness and
restart the 15-minute watch. Stop only after a full clean watch window.

## Final Report

Report:

- PR number, title, and URL
- Review rounds
- Fixed and declined counts
- Conflict status
- Check status
- Whether `ready_to_merge` was applied
- Any unresolved blockers

Do not merge.
