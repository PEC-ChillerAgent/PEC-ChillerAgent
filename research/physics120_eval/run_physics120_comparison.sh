#!/usr/bin/env bash
set -uo pipefail
cd -- "$(dirname -- "$0")"
ARM="${1:-base8b}"
case "$ARM" in base8b|qwen14b) ;; *) echo "Use base8b or qwen14b";exit 2;; esac
if [ "${CONDA_DEFAULT_ENV:-}" != chiller-sft-v1 ];then echo "Activate existing chiller-sft-v1; no install or upgrade.";exit 2;fi
mkdir -p results
RUN="${2:-results/physics120_${ARM}_$(date +%Y%m%d_%H%M%S)_$$}"
if [ -e "$RUN" ] || [ -e "${RUN}.console.log" ];then echo "Preserve existing run";exit 2;fi
export CUBLAS_WORKSPACE_CONFIG=:4096:8 CUDA_VISIBLE_DEVICES="${CHILLER_GPU_INDEX:-0}"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
python -B -u -m student_tools.physics120_comparison --arm "$ARM" --output "$RUN" --run 2>&1 | tee "${RUN}.console.log"
STATUS=${PIPESTATUS[0]}
if [ -d "$RUN" ];then
 mv -- "${RUN}.console.log" "$RUN/console.log"
 python -B -m student_tools.export_smoke_review --run-dir "$RUN"
 EXPORT_STATUS=$?
 if [ "$STATUS" -eq 0 ] && [ "$EXPORT_STATUS" -ne 0 ];then STATUS=$EXPORT_STATUS;fi
fi
echo "Evaluation exit code: $STATUS"
echo "Return ${RUN}_review.zip, including failures. Do not rerun completed quality cases."
exit "$STATUS"
