#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'Required command not found: uv' >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'Required command not found: docker' >&2
  exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

printf '%s\n' 'Reinstalling ductor from this worktree...'
uv tool install --force --from "$repo_root" ductor

printf '%s\n' \
  'Starting the verified Docker rebuild.' \
  'Docker subprocess output is intentionally suppressed.' \
  'The first full tool build may remain quiet for up to 40 minutes.'

exec ductor docker rebuild
