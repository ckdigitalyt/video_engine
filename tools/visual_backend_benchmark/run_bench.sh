#!/usr/bin/env bash
# V14 Stage 2 — Remotion benchmark runner (bounded: 2 workers, 4 OCPU box)
set -u
cd "$(dirname "$0")/remotion_bench"
mkdir -p out ../results

# fonts for typography fidelity
fc-list 2>/dev/null | grep -qi dejavu || sudo -n apt-get install -y -qq fonts-dejavu-core >> ../results/apt_chrome_deps.log 2>&1

echo "=== V14 REMOTION BENCHMARK $(date -u +%FT%TZ) ===" | tee ../results/bench_remotion.txt
node -e "console.log('remotion:', require('remotion/package.json').version)" 2>/dev/null | tee -a ../results/bench_remotion.txt

# startup/bundle cost
/usr/bin/time -v npx remotion bundle --out-dir out/bundle 2> ../results/bundle.time.log >/dev/null || true
grep -E "Elapsed \(wall|Maximum resident" ../results/bundle.time.log | sed 's/^\s*//' | sed 's/^/bundle /' | tee -a ../results/bench_remotion.txt

# per-scene renders (independent — demonstrates per-scene rerender)
for C in BenchA BenchB BenchC BenchD; do
  /usr/bin/time -v npx remotion render "$C" "out/$C.mp4" --codec h264 --concurrency 2 --log error \
    2> "../results/$C.time.log" > "../results/$C.render.log"
  RC=$?
  WALL=$(grep -m1 "Elapsed (wall" "../results/$C.time.log" | sed 's/^\s*//')
  RSS=$(grep -m1 "Maximum resident" "../results/$C.time.log" | sed 's/^\s*//')
  echo "--- $C exit=$RC | $WALL | $RSS" | tee -a ../results/bench_remotion.txt
  ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_type,duration \
    -of csv "out/$C.mp4" 2>/dev/null | sed "s/^/$C /" | tee -a ../results/bench_remotion.txt
done

# determinism: identical second render of BenchA
/usr/bin/time -v npx remotion render BenchA out/BenchA_rerender.mp4 --codec h264 --concurrency 2 --log error \
  2> ../results/BenchA_rerender.time.log > /dev/null
md5sum out/BenchA.mp4 out/BenchA_rerender.mp4 | sed 's/^/determinism /' | tee -a ../results/bench_remotion.txt

echo BENCH_DONE | tee -a ../results/bench_remotion.txt
