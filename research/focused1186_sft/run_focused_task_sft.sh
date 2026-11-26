#!/usr/bin/env bash
set -uo pipefail
cd -- "$(dirname -- "$0")"
if [ "${CONDA_DEFAULT_ENV:-}" != chiller-sft-v1 ]; then
  echo "Activate existing chiller-sft-v1. No installation."
  exit 2
fi
mkdir -p results
RUN="${1:-results/focused_task_$(date +%Y%m%d_%H%M%S)_$$}"
if [ -e "$RUN" ] || [ -e "${RUN}.console.log" ]; then
  echo "Output exists. Preserve it; do not relaunch."
  exit 2
fi
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export CUDA_VISIBLE_DEVICES="${CHILLER_GPU_INDEX:-0}"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
python -B -u -m student_tools.focused_task_sft --output "$RUN" --run 2>&1 | tee "${RUN}.console.log"
STATUS=${PIPESTATUS[0]}
if [ -d "$RUN" ]; then
  mv -- "${RUN}.console.log" "$RUN/console.log"
  python -B -m student_tools.export_smoke_review --run-dir "$RUN"
  EXPORT_STATUS=$?
  if [ "$STATUS" -eq 0 ] && [ "$EXPORT_STATUS" -ne 0 ]; then STATUS=$EXPORT_STATUS; fi
fi
echo "Focused full-answer SFT exit code: $STATUS"
echo "Return ${RUN}_review.zip, including failures. Keep weights on server. No page switch."
exit "$STATUS"
