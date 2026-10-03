#!/usr/bin/env bash
# tools/daily_shorts.sh — decision #13 item 5: shorts-v3 daily-mode cron.
#
# Runs N videos sequentially through the real illustrated_engine pipeline
# (topic engine -> engine.v16_autostory research+script -> v15_pipeline
# render -> v16_gate -> packaging, all via `engine.v16_batch --n N`), then
# delivers each result to the requesting Discord channel: a PASS posts the
# packaged MP4 + title + description + tags + a one-line verdict; a
# HOLD/FAIL/ERROR posts the hold reason only, NEVER the video.
#
# Fixed cron timing only (no LLM-based scheduling). No social upload here —
# delivery is this Discord post only; configs/publish.yaml upload.enabled
# stays whatever it already is, untouched by this script.
#
# Usage: tools/daily_shorts.sh [N]      (default N=3; dry run uses N=1)
#
# Retry policy: v16_batch pauses (exit 75) ONLY on a genuine LLM usage/
# quota outage; that is the ONE allowed retry here (resume once after a
# short wait). Any other non-zero exit is reported as-is, no retry loop.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

N="${1:-3}"
CHANNEL="discord"
TARGET="${DAILY_SHORTS_DISCORD_TARGET:-channel:1544333808604807220}"
DATE_TAG="$(date -u +%Y-%m-%d_%H%M%S)"
WORK="illustrated_engine/build/v16/batches/daily_${DATE_TAG}"
LOG="logs/daily_shorts_${DATE_TAG}.log"
mkdir -p "$WORK" logs

echo "=== daily_shorts.sh N=${N} work=${WORK} $(date -u '+%Y-%m-%d %H:%M UTC') ===" | tee -a "$LOG"

run_once() {
  (cd illustrated_engine && ../venv/bin/python3 -m engine.v16_batch \
    --n "$N" --work "../$WORK") >> "$LOG" 2>&1
}

resume_once() {
  (cd illustrated_engine && ../venv/bin/python3 -m engine.v16_batch \
    --resume --work "../$WORK") >> "$LOG" 2>&1
}

run_once
RC=$?

if [ "$RC" -eq 75 ]; then
  echo "quota/usage-limit pause (exit 75): sleeping 5 minutes, one resume attempt" | tee -a "$LOG"
  sleep 300
  resume_once
  RC=$?
fi

echo "pipeline exit: $RC" | tee -a "$LOG"

venv/bin/python3 tools/daily_shorts_deliver.py --work "$WORK" --channel "$CHANNEL" \
  --target "$TARGET" >> "$LOG" 2>&1
DELIVER_RC=$?
echo "delivery exit: $DELIVER_RC (log: $LOG)" | tee -a "$LOG"

exit "$RC"
