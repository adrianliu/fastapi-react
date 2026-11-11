#!/usr/bin/env bash
# PreToolUse(Bash) hook: block creating/editing a PR whose body has no image
# when the branch changes anything under frontend/. See CLAUDE.md "Pull requests".
set -euo pipefail

cmd=$(jq -r '.tool_input.command // empty')

# Only gh / gh-axi `pr create` and `pr edit` that set a body.
echo "$cmd" | grep -qE '(^|[;&| ])(gh|gh-axi)[[:space:]]+pr[[:space:]]+(create|edit)\b' || exit 0
echo "$cmd" | grep -qE -- '--body(-file)?([[:space:]=]|$)' || exit 0

cd "${CLAUDE_PROJECT_DIR:-.}"
base=$(git merge-base HEAD origin/main 2>/dev/null || echo origin/main)
git diff --name-only "$base"...HEAD 2>/dev/null | grep -q '^frontend/' || exit 0

# Body text = the command itself (covers --body "...") + any --body-file contents.
body="$cmd"
while read -r f; do
  f=${f%\"}; f=${f#\"}; f=${f%\'}; f=${f#\'}
  [ -f "$f" ] && body+=$'\n'"$(cat "$f")"
done < <(echo "$cmd" | grep -oE -- '--body-file[[:space:]=]+[^[:space:];&|]+' | sed -E 's/^--body-file[[:space:]=]+//')

if echo "$body" | grep -qE '!\[[^]]*\]\([^)]+\)|<img[[:space:]]'; then
  exit 0
fi

jq -n '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",
  permissionDecisionReason:"This branch changes frontend/ files, so the PR description must include a screenshot. Capture the running app in the user'\''s existing Chrome, upload it as a GitHub attachment (see CLAUDE.md > Screenshots), and put the <img> or ![..](..) in the body."}}'
