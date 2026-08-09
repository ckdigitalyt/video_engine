#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════ #
# daily_video.sh — cron-driven daily documentary production (v13).
#
# Production flow (expert review rec #10): the pipeline may run every day,
# but a video is UPLOADED (unlisted, enforced by youtube_upload.py) ONLY
# when the run resolves to PUBLISH_READY.  REVISION_REQUIRED runs leave
# their artifacts + STATUS.json as revision evidence and are NOT uploaded.
#
# Usage:
#   tools/daily_video.sh "Topic: subtitle"            # one-off
#   tools/daily_video.sh --topic "Topic" --runner stills --upload
#
# Flags:
#   --topic   "..."   topic (default: rotates through DAILY_TOPICS)
#   --runner  run|stills   which runner (default: run)
#   --upload  actually upload when PUBLISH_READY (default: dry-run report)
#   --keep    keep REVISION_REQUIRED artifacts (default: keep, they are
#             the revision evidence; only interim files are cleaned)
#
# Exit codes: 0 = PUBLISH_READY (uploaded or ready), 3 = REVISION_REQUIRED,
#             2 = BLOCKED/fatal, 1 = usage/config error.
# ═══════════════════════════════════════════════════════════════════════ #
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUNNER="run"
UPLOAD="no"
TOPIC=""

DAILY_TOPICS=(
  "The Bloop: the sound that shook the ocean"
  "52-Hertz Whale: the loneliest voice in the sea"
  "Julia: the mystery sound of the Pacific"
  "Upsweep: the signal that never stops"
  "Slow Down: the ice that screams"
)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --topic) TOPIC="$2"; shift 2 ;;
    --runner) RUNNER="$2"; shift 2 ;;
    --upload) UPLOAD="yes"; shift ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$TOPIC" ]]; then
  # Rotate through the topic list by day-of-year (deterministic cron).
  IDX=$(( $(date +%j) % ${#DAILY_TOPICS[@]} ))
  TOPIC="${DAILY_TOPICS[$IDX]}"
fi

echo "═══════════════════════════════════════════════════════════════════"
echo "DAILY VIDEO — $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "  topic:  $TOPIC"
echo "  runner: $RUNNER"
echo "  upload: $UPLOAD"
echo "═══════════════════════════════════════════════════════════════════"

SLUG="$(echo "$TOPIC" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]\+/_/g' | sed 's/^_\|_$//g' | cut -c1-44)"
OUT_DIR="results/$SLUG"
mkdir -p "$OUT_DIR"
LOG="logs/${SLUG}_daily.log"
mkdir -p logs

# ── Run the pipeline ─────────────────────────────────────────────────────
if [[ "$RUNNER" == "stills" ]]; then
  CMD=(./venv/bin/python mission_stills.py --topic "$TOPIC")
else
  CMD=(./venv/bin/python mission_run.py --topic "$TOPIC")
fi

set +e
"${CMD[@]}" > "$LOG" 2>&1
RC=$?
set -e

echo "pipeline exit: $RC (log: $LOG)"

# ── Resolve run status (STATUS.json written by the pipeline) ─────────────
STATUS="BLOCKED"
if [[ -f "$OUT_DIR/STATUS.json" ]]; then
  STATUS="$(python3 -c "import json;print(json.load(open('$OUT_DIR/STATUS.json'))['status'])" 2>/dev/null || echo BLOCKED)"
fi
echo "run status: $STATUS"

# ── Find the final mixed video ───────────────────────────────────────────
VIDEO="$(ls "$OUT_DIR"/*mixed*.mp4 2>/dev/null | head -1 || true)"
if [[ -z "$VIDEO" ]]; then
  VIDEO="$(ls "$OUT_DIR"/*_v1.mp4 2>/dev/null | head -1 || true)"
fi

case "$STATUS" in
  PUBLISH_READY)
    echo "✅ PUBLISH_READY"
    if [[ "$UPLOAD" == "yes" && -n "$VIDEO" ]]; then
      echo "  uploading (unlisted): $VIDEO"
      ./venv/bin/python tools/youtube_upload.py "$VIDEO" --title "$TOPIC" || {
        echo "  !! upload failed (non-fatal for pipeline)" >&2; }
    else
      echo "  dry-run: not uploading (pass --upload to publish)"
    fi
    exit 0
    ;;
  REVISION_REQUIRED)
    echo "⛔ REVISION_REQUIRED — NOT uploaded. Artifacts at $OUT_DIR/"
    echo "   review STATUS.json + claim_report.json + publish_gate.json"
    exit 3
    ;;
  *)
    echo "⛔ BLOCKED — no publishable artifact. Log: $LOG"
    exit 2
    ;;
esac
