#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
ARM="${1:-base8b}"
case "$ARM" in base8b|qwen14b) ;; *) echo "Use base8b or qwen14b";exit 2;; esac
if [ "${CONDA_DEFAULT_ENV:-}" != chiller-sft-v1 ];then echo "Activate existing chiller-sft-v1";exit 2;fi
mkdir -p results
RUN="results/physics120_${ARM}_$(date +%Y%m%d_%H%M%S)_$$"
nohup bash run_physics120_comparison.sh "$ARM" "$RUN" > "${RUN}.launch.log" 2>&1 < /dev/null &
echo "Detached evaluation PID: $!"
echo "Watch: tail -n 50 -f ${RUN}.launch.log"
echo "Return: ${RUN}_review.zip"
echo "One GPU job at a time; no training/API/student rerun. SSH may close."
