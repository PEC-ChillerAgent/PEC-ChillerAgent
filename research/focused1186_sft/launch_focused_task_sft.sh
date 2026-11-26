#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [ "${CONDA_DEFAULT_ENV:-}" != chiller-sft-v1 ]; then
  echo "Activate existing chiller-sft-v1. Do not install or upgrade."
  exit 2
fi
mkdir -p results
RUN="results/focused_task_$(date +%Y%m%d_%H%M%S)_$$"
nohup bash run_focused_task_sft.sh "$RUN" > "${RUN}.launch.log" 2>&1 < /dev/null &
PID=$!
echo "Detached launcher PID: $PID"
echo "Run: $RUN"
echo "Watch: tail -n 50 -f ${RUN}.launch.log"
echo "Return: ${RUN}_review.zip"
echo "SSH may close; this detached job continues. Do not launch a second copy."
