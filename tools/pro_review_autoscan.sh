#!/bin/bash
# pro_review_autoscan.sh — run a Gemini Flash review (kept name for cron compat).
# Probes quota first (cheap 1-token call), retries until it clears, then reviews
# the dream video master with gemini-3.5-flash and prints a summary.
set -u
cd /home/ubuntu/video_engine || exit 1
set -a; . ./.env; set +a

VIDEO="results/why_we_dream__the_brain_s_nightly_cinema/why_we_dream__the_brain_s_nightly_cinema_mixed.mp4"
OUT="results/why_we_dream__the_brain_s_nightly_cinema/review_pro_autoscan.json"
MODEL="gemini-3.5-flash"

# Phase 1: wait for flash quota (max ~6h, check every 5 min)
echo "[$(date -u +%H:%M:%S)] probing ${MODEL} quota..."
attempt=0
while [ $attempt -lt 72 ]; do
  if python3 -c "
from google import genai
import os
c = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
try:
    c.models.generate_content(model='${MODEL}', contents='Reply OK')
    print('PRO_QUOTA_OK')
except Exception as e:
    print('PRO_QUOTA_BLOCKED:', str(e)[:60])
" 2>/dev/null | grep -q PRO_QUOTA_OK; then
    echo "[$(date -u +%H:%M:%S)] flash quota available — launching review"
    break
  fi
  attempt=$((attempt+1))
  echo "[$(date -u +%H:%M:%S)] quota still blocked (attempt $attempt/72) — sleeping 5 min"
  sleep 300
done

# Phase 2: run the flash review
python3 review_video.py "$VIDEO" --model "$MODEL" --out "$OUT" 2>&1 | tail -25

echo "=== FLASH REVIEW SUMMARY ==="
python3 -c "
import json
r = json.load(open('$OUT'))
print('Score:', r.get('quality_score'), '/100 (conf', r.get('confidence'), ')')
print('Model used:', r.get('_meta', {}).get('model_used'))
print('Strengths:', r.get('strengths', []))
print('Weaknesses:', r.get('weaknesses', []))
for rec in r.get('prioritized_recommendations', []):
    print('-', rec)
"
