# Focused teacher32 continuation:815 TRAIN rows,1186 updates

ONE bounded SFT candidate continues retained1058 SHA79b247, not rejected DPO
SHA1849d4. Reuse chiller-sft-v1@5befcb78 unchanged. Keep every previous adapter
and base on the server. No install, upgrade, online download or teacher call.
One trainable LoRA, fresh AdamW, LR5e-6/constant,seed42,dropout0.05,BF16 frozen
base,504 FP32 adapter tensors. This is not a stack of previous adapters.

815 unique TRAIN rows =783 exact old rows +32 newly reviewed teacher-assisted
questions. The original783 file is retained as an exact byte prefix. New32
come from32 already-used TRAIN parents, not new independent measurements or
parents. All32 targets were editorially rewritten/partly templated, not raw
teacher-verbatim or independent expert truth; teacher originals and approval
lineage remain separate. Three explicit raw content errors were corrected.
All TRAIN815 use47 existing parents. No DEV/final labels enter gradients.

One predeclared weighted visit sequence has1186 updates:task08=1,
explanation_replay=1,selection_replay=2,compound09=2,selection09=2,
complete_teacher=1,targeted_teacher=6,focused_teacher=4. No automatic extra
epochs or checkpoint search. Save only adapter_focused_epoch1. New data and
continued weighted replay change together; no causal/optimal-recipe claim.

Before optimizer creation,4 known original-input controls must reproduce
retained1058 tokens exactly, including old errors. Generate32 fresh baseline
answers for the new TRAIN questions. Reuse140 same-input historical DEV
answers (104 explanation,36 selector) with new latency NULL and old errors
intact. After training generate172 answers once (newTRAIN32 plus original
unchangedDEV140).208 FRESH generations=4 controls+32 baseline+172 after;
344 comparison records also include140 historical answers, not344 new calls.
New32 citation labels come from approved targets and are TRAIN-fit checks,
not independent-test truth. Labels never enter generation message history.

Keep the original single-pass whole-answer interface and original questions,
facts, units and states. No taskwise multi-call assembly, rewriting of model
output, replacement of failed answers or source calculations. Original v7
and offline v8 scores are preserved. Neither loss, a citation match nor a
finite check proves content correctness. Tool fallback is not student success.
All172 after answers require item-level review after return. Diagnostic TRAIN
goal30/32, DEV goal99/104 including61/64 and38/40,0 critical formula/water-side/
unit/missing errors,0 loops/truncation,selector no regression below32/36.
These development gates alone do not release the model:95% complete tasks,
final-test justification and actual page Python/identity/current citations/
fallback/rollback acceptance remain necessary. Final128 stays sealed. No
automatic page or default-model switch, even if any score improves.

GPU preflight requires60GiB free GPU/4GiB output disk; no processes stopped.
It checks exact versions and base/adapter/tokenizer hashes, seeded BF16 math
witness and actual greedy behavior.815 native label checks require masked
prompt and final answer+EOS/suffix with no truncation. Each1186 update checks
all504 finite gradients and frozen-base absence of gradients. Save/reload
FP32 tensors and next-token logits must match. Base after-checks are sample
and metadata probes, not a full post-training rehash. Real H100 quality is
not checked by local CPU fixtures. Budget/cost are unmeasured for this run;
previous1058 training+evaluation was about124 minutes. Do not promise the
same duration; generation may dominate. GPU rental price is unknown.

Server commands are supplied directly in chat. launch_focused_task_sft.sh
detaches with nohup and prints the exact Watch tail command. SSH may close;
do not launch twice. Ctrl+C exits tail, not training. A per-package fcntl
lock rejects simultaneous jobs. run_focused_task_sft.sh is a foreground
ALTERNATIVE, not an additional launch. Return results/focused_task_*_review.zip
including failures. Keep adapter_focused_epoch1 and the initial weights.

## Documented local CPU validation only

In this package directory run each command verbatim once:

```powershell
& 'F:/Anaconda/envs/modelica/python.exe' -X utf8 -B -m student_tools.focused_task_sft --output ../../../../tmp/focused_task_doc_follow_v1 --validate-package-only
& 'F:/Anaconda/envs/modelica/python.exe' -X utf8 -B -m student_tools.export_smoke_review --run-dir ../../../../tmp/focused_task_doc_follow_v1
```

These do not load weights, infer, train or call an API. Preserve and report
existing output collisions; do not delete, change the command or repeat it.
