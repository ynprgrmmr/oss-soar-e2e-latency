#!/usr/bin/env bash
# Export a history-free snapshot of this private repo for the public repo.
#
#   tools/export-public.sh --dest DIR [--ref main]
#
# - First run (DIR missing or empty): creates DIR as a new git repo with ONE
#   commit authored by the GitHub noreply address.
# - Later runs (DIR is a clone of the public repo): replaces the working tree
#   with the snapshot and adds ONE new commit on top.
# - Excludes paths listed in EXCLUDES (internal-only files).
# - Runs tools/scan-sensitive.sh inside DIR and fails if anything is found.
# - NEVER pushes. Creating the GitHub repo / pushing / changing visibility is a
#   separate, explicitly approved step.
set -euo pipefail

EXCLUDES=(CLAUDE.md .claude)          # internal working rules, not part of the release
REF=main; DEST=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --ref)  REF="$2";  shift 2 ;;
    *) echo "usage: $0 --dest DIR [--ref REF]" >&2; exit 2 ;;
  esac
done
[[ -n "$DEST" ]] || { echo "--dest is required" >&2; exit 2; }

SRC="$(git rev-parse --show-toplevel)"
SHA="$(git -C "$SRC" rev-parse --short "$REF")"
EMAIL="$(git -C "$SRC" config --local user.email || true)"
NAME="$(git -C "$SRC" config user.name)"
[[ "$EMAIL" == *@users.noreply.github.com ]] || { echo "set a GitHub noreply address with: git config --local user.email" >&2; exit 1; }

mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"
case "$DEST/" in "$SRC/"*) echo "--dest must be outside this repository" >&2; exit 1 ;; esac

if [[ -d "$DEST/.git" ]]; then
  mode=update
  git -C "$DEST" diff --quiet && git -C "$DEST" diff --cached --quiet || { echo "$DEST has uncommitted changes" >&2; exit 1; }
  find "$DEST" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
else
  [[ -z "$(ls -A "$DEST")" ]] || { echo "$DEST is not empty and not a git repo" >&2; exit 1; }
  mode=init
  git -C "$DEST" init -q -b main
fi

pathspec=(.)
for e in "${EXCLUDES[@]}"; do pathspec+=(":(exclude)$e"); done
git -C "$SRC" archive --format=tar "$REF" -- "${pathspec[@]}" | tar -x -C "$DEST"

git -C "$DEST" config user.name "$NAME"
git -C "$DEST" config user.email "$EMAIL"
git -C "$DEST" add -A
if git -C "$DEST" diff --cached --quiet; then
  echo "no changes since the last snapshot"; exit 0
fi
msg="Release snapshot of $SHA"
[[ $mode == init ]] && msg="Initial public release (snapshot of $SHA)"
git -C "$DEST" commit -q -F - <<MSG
$msg

Exported with tools/export-public.sh (history-free; internal files excluded:
${EXCLUDES[*]}).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
MSG

echo "== $mode: $(git -C "$DEST" rev-list --count HEAD) commit(s), $(git -C "$DEST" ls-files | wc -l) files"
for e in "${EXCLUDES[@]}"; do [[ ! -e "$DEST/$e" ]] || { echo "excluded path present: $e" >&2; exit 1; }; done
(cd "$DEST" && ./tools/scan-sensitive.sh)
echo "== snapshot ready at $DEST (not pushed)"
