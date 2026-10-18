#!/usr/bin/env bash
# Run locally in your trusted terminal only after reviewing all files.
set -euo pipefail
repo=Jun516/oss-agent-contributor
command -v gh >/dev/null || { echo 'Install GitHub CLI first' >&2; exit 2; }
command -v git >/dev/null || { echo 'Install Git first' >&2; exit 2; }
gh auth status
[[ "$(gh api user --jq .login)" == Jun516 ]] || { echo 'Wrong GitHub account' >&2; exit 2; }
cd "$(dirname "$0")"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git init -b main
  git add .
  git -c user.name=Jun516 -c user.email=Jun516@users.noreply.github.com commit -m 'chore: add autonomous OSS contributor pipeline'
fi
if gh repo view "$repo" >/dev/null 2>&1; then
  echo 'Repository exists. No push performed; review git status and remote before proceeding.'
else
  gh repo create "$repo" --public --source . --remote origin --push
fi
echo 'Configure OPENAI_API_KEY and OSS_BOT_TOKEN in Actions Secrets. Autonomous publication is enabled unless PAUSE_AUTOPUBLISH=true.'
