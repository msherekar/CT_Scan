#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/git_folder.sh "your commit message"

What it does:
  1) Shows git status
  2) Adds all changes
  3) Commits with your message
  4) Pushes current branch to origin
EOF
}

require_git_repo() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    echo "Error: not inside a git repository."
    exit 1
  }
}

main() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -eq 0 ]]; then
    usage
    exit 0
  fi

  local commit_message="$1"
  require_git_repo

  echo "==> Current status"
  git status --short
  echo

  echo "==> Staging all changes"
  git add .

  echo "==> Creating commit"
  git commit -m "$commit_message"

  echo "==> Pushing to origin"
  local branch
  branch="$(git branch --show-current)"
  git push -u origin "$branch"

  echo "Done: changes committed and pushed."
}

main "$@"
