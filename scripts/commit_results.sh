#!/usr/bin/env bash
# Commit generated evidence files back to the branch the workflow runs on (used by the workflows only).
# usage: scripts/commit_results.sh "message" path [path...]
set -euo pipefail
msg="$1"; shift
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -f "$@"
if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
git commit -m "$msg"
for i in 1 2 3 4 5; do
  git pull --rebase origin "${GITHUB_REF_NAME}" && git push origin "HEAD:${GITHUB_REF_NAME}" && exit 0
  sleep $((RANDOM % 10 + 3))
done
echo "could not push results" >&2; exit 1
