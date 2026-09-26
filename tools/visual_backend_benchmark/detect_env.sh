#!/usr/bin/env bash
# V14 Stage 2 — visual backend benchmark: environment detection (read-only + version logging)
# Directive: docs/directives/JADE_V14_SCENE_GRAPH_AUTONOMOUS_PRODUCTION.md §2-§3
set -u
cd "$(dirname "$0")"
mkdir -p results
OUT="results/env_report.txt"
{
echo "=== V14 VISUAL BACKEND BENCHMARK — ENV DETECTION $(date -u +%FT%TZ) ==="
echo "--- system"
uname -a
echo "arch: $(uname -m)  cpus: $(nproc)"
grep -m1 "model name" /proc/cpuinfo || grep -m1 "Model" /proc/cpuinfo || true
free -h | head -2 | tail -1
df -h / | tail -1
echo "--- gpu (expect none)"
ls /dev/nvidia* 2>/dev/null || echo "no GPU devices (CPU-only confirmed)"
echo "--- runtimes"
node --version 2>/dev/null || echo "node: MISSING"
npm --version 2>/dev/null || echo "npm: MISSING"
python3 --version
ffmpeg -version 2>/dev/null | head -1 || echo "ffmpeg: MISSING"
echo "--- candidate renderers (already installed?)"
(npx --no-install remotion --version 2>/dev/null && echo "remotion: installed") || echo "remotion: not installed"
resvg --version 2>/dev/null || echo "resvg: not installed"
inkscape --version 2>/dev/null | head -1 || echo "inkscape: not installed"
(python3 -c "import vtracer; print('vtracer python pkg:', getattr(vtracer,'__version__','present'))" 2>/dev/null) || echo "vtracer: not installed"
synfig --version 2>/dev/null | head -1 || echo "synfig: not installed"
echo "--- package availability probe (apt-cache, no installs)"
for p in resvg synfig synfigstudio; do
  apt-cache policy "$p" 2>/dev/null | grep -m1 Candidate || echo "$p: no apt candidate"
done
echo "--- sudo"
sudo -n true 2>/dev/null && echo "passwordless sudo: yes" || echo "passwordless sudo: no"
} | tee "$OUT"
echo "env report -> $OUT"
