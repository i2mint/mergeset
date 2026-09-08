#!/bin/zsh
# Evaluate one merged tree: $1 = commit sha, $2 = label
# Runs the local equivalent of cosmograph CI's Lint + Unit Tests jobs.
set -u
REPO=/Users/thorwhalen/Dropbox/py/proj/c/_worktrees/c-mergeset-test/repo
WT=/Users/thorwhalen/Dropbox/py/proj/c/_worktrees/c-mergeset-test/eval
WORK=/Users/thorwhalen/Dropbox/py/proj/c/_worktrees/c-mergeset-test/work
SHA=$1; LABEL=$2
mkdir -p "$WORK/logs"
LOG="$WORK/logs/$LABEL.log"
: > "$LOG"
start=$(date +%s)
if [ ! -d "$WT" ]; then
  git -C "$REPO" worktree add --detach "$WT" "$SHA" >>"$LOG" 2>&1 || { echo "WORKTREE_FAIL"; exit 90; }
else
  git -C "$WT" checkout --detach "$SHA" >>"$LOG" 2>&1 || { echo "CHECKOUT_FAIL"; exit 90; }
  git -C "$WT" clean -xfd -e node_modules -e '**/node_modules' >>"$LOG" 2>&1
fi
cd "$WT" || exit 91
echo "=== pnpm install ===" >>"$LOG"
pnpm install --frozen-lockfile >>"$LOG" 2>&1 || pnpm install --no-frozen-lockfile >>"$LOG" 2>&1
echo "=== build:cosmos ===" >>"$LOG"
pnpm run build:cosmos >>"$LOG" 2>&1; BUILD=$?
echo "=== test ===" >>"$LOG"
pnpm run test --reporter=dot >>"$LOG" 2>&1; TEST=$?
echo "=== lint:ci ===" >>"$LOG"
pnpm run lint:ci >>"$LOG" 2>&1; LINT=$?
end=$(date +%s)
echo "RESULT label=$LABEL sha=$SHA build=$BUILD test=$TEST lint=$LINT secs=$((end-start))"
