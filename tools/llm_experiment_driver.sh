#!/usr/bin/env bash
# llm_experiment_driver.sh — controlled Groq vs Nemotron vs ZAI GLM A/B.
# Runs 3 complete stills-first video generations on the SAME topic:
#   1. control  (production chain, no env override)
#   2. groq     (LLM_ROUTING_EXPERIMENT=groq → [Groq, ZAI GLM])
#   3. nemotron (LLM_ROUTING_EXPERIMENT=nemotron → [Nemotron, ZAI GLM])
# Results dir is moved aside after each run so evidence is preserved.
set -euo pipefail
cd "$(dirname "$0")/.."
TOPIC="The Bloop: the sound that shook the ocean"
TS=$(date +%Y%m%d_%H%M%S)
SLUG=$(./venv/bin/python -c "
import sys
t='${TOPIC}'
print(''.join(c if c.isalnum() else '_' for c in t.lower())[:40].strip('_'))")
LOG="logs/llm_exp_${TS}.log"
echo "SLUG=$SLUG TS=$TS" | tee "$LOG"

run_one() {
  local tag="$1"; shift
  local t0=$(date +%s)
  echo "=== [$tag] start $(date -u +%H:%M:%S) ===" | tee -a "$LOG"
  "$@" ./venv/bin/python mission_stills.py --topic "$TOPIC" --target-seconds 60 >> "$LOG" 2>&1
  local rc=$?
  local t1=$(date +%s)
  echo "=== [$tag] end rc=$rc dur=$(( (t1-t0)/60 ))m $(date -u +%H:%M:%S) ===" | tee -a "$LOG"
  if [ -d "results/$SLUG" ]; then
    mv "results/$SLUG" "results/${SLUG}__${tag}"
    echo "  archived -> results/${SLUG}__${tag}" | tee -a "$LOG"
  fi
  return $rc
}

run_one control
run_one groq env LLM_ROUTING_EXPERIMENT=groq
run_one nemotron env LLM_ROUTING_EXPERIMENT=nemotron
echo "ALL DONE $TS" | tee -a "$LOG"
