#!/usr/bin/env bash
set -euo pipefail
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
existing="$(git -C "$repository_root" config --get core.hooksPath || true)"
if [[ -n "$existing" && "$existing" != ".githooks" ]]; then
  echo "Existing core.hooksPath=$existing; left unchanged. Integrate make verify into that hook."
  exit 1
fi
if [[ -z "$existing" ]]; then
  default_hook="$(git -C "$repository_root" rev-parse --git-path hooks/pre-push)"
  [[ "$default_hook" = /* ]] || default_hook="$repository_root/$default_hook"
  if [[ -f "$default_hook" ]]; then
    echo "Existing pre-push at $default_hook; left unchanged. Integrate make verify into that hook."
    exit 1
  fi
fi
git -C "$repository_root" config --local core.hooksPath .githooks
echo "Configured repository pre-push: make verify"
