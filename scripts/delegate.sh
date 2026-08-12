#!/usr/bin/env bash
#
# delegate.sh — hand a self-contained subtask to OpenCode, keeping the full
# transcript out of the calling agent's context window.
#
# Usage:
#   delegate.sh [options] "<task prompt>"
#   delegate.sh [options] path/to/task.md
#
#   -m <model>   provider/model      (default: kimi-for-coding/k3)
#   -a <agent>   opencode agent      (default: worker)
#   -d <dir>     workspace root      (default: current directory)
#   -l <label>   log filename slug   (default: derived from the prompt)
#   -q           quiet: print only the log path
#   -h           help
#
# Prints the log path plus the tail of the reply. Read the file for detail.
#
# Logs are written OUTSIDE the workspace, to
#   ${DELEGATE_LOG_DIR:-$HOME/.claude/delegate-logs/<workspace-name>}
# so a dispatch never dirties `git status` — the handoff Verify step relies on
# `git diff` being a clean signal of what workers actually changed.
#
# Behaviours this works around (verified on opencode 1.16.2, macOS):
#   * Without --thinking, `opencode run` prints NO answer text at all.
#   * `kimi-for-coding/k3` intermittently returns a completely empty run
#     (no output, exit 0). Retried once, then failed over to FALLBACK_MODEL.
#   * `-f` is an array flag: it swallows any positional that follows it, so the
#     message must be passed BEFORE -f.
#   * macOS has no `timeout`/`gtimeout` by default — no wrapper is used.
#   * Exit status is 0 even on an empty run; it is NOT a success signal.

set -uo pipefail

DEFAULT_MODEL="kimi-for-coding/k3"
FALLBACK_MODEL="opencode-go/kimi-k3"
DEFAULT_AGENT="worker"

MODEL="$DEFAULT_MODEL"
AGENT="$DEFAULT_AGENT"
WORKDIR="$(pwd)"
LABEL=""
QUIET=0

usage() { sed -n '2,31p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while getopts ":m:a:d:l:qh" opt; do
  case "$opt" in
    m) MODEL="$OPTARG" ;;
    a) AGENT="$OPTARG" ;;
    d) WORKDIR="$OPTARG" ;;
    l) LABEL="$OPTARG" ;;
    q) QUIET=1 ;;
    h) usage 0 ;;
    \?) echo "delegate: unknown option -$OPTARG" >&2; usage 2 ;;
    :)  echo "delegate: -$OPTARG requires a value" >&2; usage 2 ;;
  esac
done
shift $((OPTIND - 1))

[ $# -ge 1 ] || { echo "delegate: no task given" >&2; usage 2; }
[ -d "$WORKDIR" ] || { echo "delegate: no such directory: $WORKDIR" >&2; exit 2; }
WORKDIR="$(cd "$WORKDIR" && pwd)"
TASK="$*"

# A readable file argument is attached with -f; anything else is a literal prompt.
TASK_FILE=""
if [ $# -eq 1 ] && [ -f "$TASK" ]; then
  TASK_FILE="$(cd "$(dirname "$TASK")" && pwd)/$(basename "$TASK")"
fi

if [ -z "$LABEL" ]; then
  if [ -n "$TASK_FILE" ]; then
    LABEL="$(basename "$TASK_FILE" | sed 's/\.[^.]*$//')"
  else
    LABEL="$(printf '%s' "$TASK" | tr '[:upper:]' '[:lower:]' \
             | sed 's/[^a-z0-9]\{1,\}/-/g; s/^-//; s/-$//' | cut -c1-40)"
  fi
  [ -n "$LABEL" ] || LABEL="task"
fi

LOG_DIR="${DELEGATE_LOG_DIR:-$HOME/.claude/delegate-logs/$(basename "$WORKDIR")}"
mkdir -p "$LOG_DIR" || { echo "delegate: cannot create $LOG_DIR" >&2; exit 2; }
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/$STAMP-$LABEL.md"

# --- run -------------------------------------------------------------------
# $1 = model. Appends the reply to $LOG, sets REPLY_BYTES. Returns opencode rc.
run_once() {
  local model="$1" body_start rc
  body_start=$(( $(wc -l < "$LOG") + 1 ))
  if [ -n "$TASK_FILE" ]; then
    # Message BEFORE -f: the flag is an array and eats trailing positionals.
    opencode run --dir "$WORKDIR" --agent "$AGENT" --thinking -m "$model" \
      "Execute the task in the attached file. Follow it exactly." \
      -f "$TASK_FILE" >>"$LOG" 2>&1
  else
    opencode run --dir "$WORKDIR" --agent "$AGENT" --thinking -m "$model" \
      "$TASK" >>"$LOG" 2>&1
  fi
  rc=$?
  REPLY_BYTES=$(tail -n +"$body_start" "$LOG" | tr -d '[:space:]' | wc -c | tr -d ' ')
  return $rc
}

{
  echo "---"
  echo "task: ${TASK_FILE:-$TASK}"
  echo "model: $MODEL"
  echo "agent: $AGENT"
  echo "workdir: $WORKDIR"
  echo "started: $STAMP"
  echo "---"
  echo
} > "$LOG"

START=$(date +%s)
run_once "$MODEL"; RC=$?
USED="$MODEL"; ATTEMPTS=1

if [ "${REPLY_BYTES:-0}" -lt 20 ]; then
  { echo; echo "<!-- empty reply from $MODEL; retrying -->"; echo; } >> "$LOG"
  run_once "$MODEL"; RC=$?; ATTEMPTS=2
fi

if [ "${REPLY_BYTES:-0}" -lt 20 ] && [ "$MODEL" != "$FALLBACK_MODEL" ]; then
  { echo; echo "<!-- still empty; failing over to $FALLBACK_MODEL -->"; echo; } >> "$LOG"
  run_once "$FALLBACK_MODEL"; RC=$?; USED="$FALLBACK_MODEL"; ATTEMPTS=3
fi

ELAPSED=$(( $(date +%s) - START ))

{
  echo
  echo "---"
  echo "finished_model: $USED"
  echo "attempts: $ATTEMPTS"
  echo "exit: $RC"
  echo "seconds: $ELAPSED"
  echo "---"
} >> "$LOG"

# --- report ----------------------------------------------------------------
if [ "$QUIET" -eq 1 ]; then
  echo "$LOG"
  [ "${REPLY_BYTES:-0}" -lt 20 ] && exit 1
  exit $RC
fi

echo "log:      $LOG"
echo "model:    $USED (attempt $ATTEMPTS of max 3)"
echo "exit:     $RC   elapsed: ${ELAPSED}s"

if [ "${REPLY_BYTES:-0}" -lt 20 ]; then
  echo
  echo "WARNING: empty reply after $ATTEMPTS attempts — exit status is NOT a"
  echo "reliable signal here. Check 'git status' before assuming nothing ran."
  exit 1
fi

echo
echo "--- reply (tail) ---"
tail -n 25 "$LOG"
exit $RC
