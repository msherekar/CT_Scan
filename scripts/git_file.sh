#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/git_file.sh <file_path> "your commit message"

Examples:
  ./scripts/git_file.sh README.md "docs: update readme"
  ./scripts/git_file.sh src/tests/test_qubit.py "test: add qubit checks"

What it does:
  1) Shows git status
  2) Adds only the given file
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
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 2 ]]; then
    usage
    exit 0
  fi

  local file_path="$1"
  local commit_message="$2"
  require_git_repo

  if [[ ! -e "$file_path" ]]; then
    echo "Error: file does not exist -> $file_path"
    exit 1
  fi

  echo "==> Current status"
  git status --short
  echo

  echo "==> Staging file: $file_path"
  git add "$file_path"

  echo "==> Creating commit"
  git commit -m "$commit_message"

  echo "==> Pushing to origin"
  local branch
  branch="$(git branch --show-current)"
  git push -u origin "$branch"

  echo "Done: file committed and pushed."
}

main "$@"
