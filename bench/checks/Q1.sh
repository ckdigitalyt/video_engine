#!/usr/bin/env bash
# Q1 exit criterion: round-trip voice WER <= 0.03 on 3 real scripts incl.
# Tunguska. Exits 0 iff the check script's verdict is PASS; always prints
# the numbers.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
source venv/bin/activate
python3 bench/checks/q1_wer.py
