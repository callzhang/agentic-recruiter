#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

print_help() {
  cat <<'EOF'
Usage:
  ./vercel_safe.sh doctor
  ./vercel_safe.sh dev [vercel dev options...]
  ./vercel_safe.sh deploy [vercel deploy options...]
  ./vercel_safe.sh <any vercel args...>

What it does:
  - Runs from the `vercel/` directory (so you can launch it from anywhere)
  - Detects macOS/iCloud "dataless" lockfiles in parent directories that can
    block reads and make `vercel dev` / `vercel --prod` appear to hang.
EOF
}

check_macos_dataless_lockfiles() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    return 0
  fi

  local dir="$SCRIPT_DIR"
  local -a lockfiles=("package-lock.json" "pnpm-lock.yaml" "yarn.lock")

  # Walk up directories and check for lockfiles that are iCloud "dataless" placeholders.
  # Vercel/Node tooling sometimes searches upward for lockfiles; if any of them are
  # "dataless", reading can block while iCloud downloads the file contents.
  for _ in {1..12}; do
    for lock in "${lockfiles[@]}"; do
      local path="$dir/$lock"
      if [[ -f "$path" ]]; then
        # Example output includes: "compressed,dataless"
        if ls -lO "$path" 2>/dev/null | grep -qE '(^|[[:space:]])dataless([[:space:]]|,|$)'; then
          cat >&2 <<EOF
ERROR: Found an iCloud "dataless" lockfile that can cause Vercel CLI to hang:
  $path

Fix options:
  1) In Finder, download this file (or mark the parent folder as "Always Keep on This Device")
  2) Move this repo out of iCloud-managed folders (avoid ~/Documents if iCloud Drive is enabled)
  3) If this lockfile is not needed, remove/rename it so tooling won't try to read it
EOF
          return 2
        fi
      fi
    done

    local parent
    parent="$(dirname "$dir")"
    if [[ "$parent" == "$dir" ]]; then
      break
    fi
    dir="$parent"
  done
}

main() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    print_help
    exit 0
  fi

  check_macos_dataless_lockfiles

  if [[ "${1:-}" == "doctor" ]]; then
    echo "OK: no iCloud dataless lockfiles detected in parent directories."
    exit 0
  fi

  if [[ $# -eq 0 ]]; then
    exec vercel dev
  fi

  exec vercel "$@"
}

main "$@"

