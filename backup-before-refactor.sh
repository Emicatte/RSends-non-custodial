#!/bin/bash
# ============================================================================
# RSends Refactor — Safety Backup Script
# ============================================================================
set -e

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
  echo "ERROR: not inside a git repository."
  exit 1
fi
cd "$REPO_ROOT"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_BRANCH="backup/pre-refactor-$TIMESTAMP"
BACKUP_TAG="backup-pre-refactor-$TIMESTAMP"

echo ""
echo "=========================================="
echo "  RSends Refactor — Safety Backup"
echo "=========================================="
echo ""
echo "Repo root: $REPO_ROOT"
echo "Current branch: $(git branch --show-current)"
echo ""

if ! git diff-index --quiet HEAD --; then
  echo "WARNING: you have uncommitted changes."
  echo "Commit or stash them first, then rerun this script."
  echo ""
  git status --short
  exit 1
fi

echo "Creating backup branch: $BACKUP_BRANCH"
git branch "$BACKUP_BRANCH"

echo "Creating backup tag: $BACKUP_TAG"
git tag "$BACKUP_TAG"

echo "Pushing backup to remote..."
git push origin "$BACKUP_BRANCH" 2>&1 | grep -v "^remote:" || true
git push origin "$BACKUP_TAG" 2>&1 | grep -v "^remote:" || true

cat > RECOVERY.md <<EOF
# Emergency Recovery

If the visual refactor goes wrong, run ONE of these to restore the site:

## Option 1 — Hard reset current branch to backup (destroys uncommitted changes)

\`\`\`bash
git fetch origin
git reset --hard $BACKUP_TAG
git push origin main 
\`\`\`

This wipes main and replaces it with the pre-refactor state. Vercel will auto-deploy the original site within 2-3 minutes.

## Option 2 — Create a new branch from backup for review

\`\`\`bash
git checkout -b recovery-\$(date +%Y%m%d) $BACKUP_TAG
\`\`\`

This creates a new branch at the backup point without touching main. Use this if you want to compare before vs after.

## Option 3 — Revert specific commits

\`\`\`bash
git log --oneline $BACKUP_TAG..HEAD
# identify the commit(s) to revert
git revert <commit-sha>
git push origin main
\`\`\`

## Verify backup exists

\`\`\`bash
git branch -a | grep $BACKUP_BRANCH
git tag | grep $BACKUP_TAG
\`\`\`

## Created

- Date: $(date)
- Commit: $(git rev-parse HEAD)
- Branch at backup: $(git branch --show-current)
- Backup branch: $BACKUP_BRANCH
- Backup tag: $BACKUP_TAG
EOF

echo ""
echo "=========================================="
echo "  Backup complete."
echo "=========================================="
echo ""
echo "Local backup branch: $BACKUP_BRANCH"
echo "Local backup tag:    $BACKUP_TAG"
echo "Remote:              pushed to origin"
echo ""
echo "Recovery instructions saved to: RECOVERY.md"
echo ""
echo "To recover after refactor (if needed):"
echo "  git reset --hard $BACKUP_TAG && git push origin main --force"
echo ""
echo "You can now safely proceed with the refactor."
echo ""
