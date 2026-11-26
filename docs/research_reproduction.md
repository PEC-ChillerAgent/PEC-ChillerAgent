# 训练、评测与发布范围

当前应用入口使用 `chiller_student`。`research/` 是选定历史研究代码的独立快照，方便查看实际训练和评测实现；它不会被应用导入，也不随CI启动GPU作业。

## 最终SFT

源码位于 `research/focused1186_sft/student_tools/focused_task_sft.py`，固定访问次序及完整性检查在 `focused_task_support.py`，计划在 `training_plan.json`。代码保持原训练包字节，来源和SHA-256保存在 `PUBLICATION_MANIFEST.json`。

训练条件：从targeted1058适配器继续训练，815个唯一样本、1186次加权访问；AdamW新优化器，常量学习率5e-6、seed42、batch1、累积1。基座BF16冻结，504个FP32 LoRA张量更新，答案及结束标记参与监督。不是从原始Qwen仅训练1186步，也不是把多个LoRA相加。

公开快照不包含原数据、参考答案、token编码核对文件或起始权重。`PUBLICATION_MANIFEST.json.required_external_files`列出原包必须具备、当前未发布的文件及预期哈希。不能凭这个代码目录声称训练已可从零完整复现。

有权访问原包材料的研究者可在隔离副本中按原相对路径补齐缺项，并使用原 `bundle_manifest.json` 校验；不得改写哈希让其他数据冒充原实验。先执行仅校验命令：

```bash
cd research/focused1186_sft
python -m student_tools.focused_task_sft \
  --bundle bundle_manifest.json \
  --model-dir <原Qwen3-8B路径> \
  --adapter-dir <原targeted1058路径> \
  --output results/package_check_new \
  --validate-package-only
```

缺少原包文件时停止是预期行为。只有补齐材料、环境及算力且明确要重跑时才用 `--run`；不能用最终focused1186权重替代训练起点，也不需要为日常使用重训模型。

## 120题评测源码

`research/physics120_eval`保留当时开放权重基线（8B、14B）的推理脚本与依赖。该历史包复用既有学生回答，不重新采样学生；输入为已计算证据＋问题，评测不执行完整Agent工具循环。它不是新的四模型一键采集器，API采集和后续人工/助手审核不由该脚本完成。

历史校验器锁定当时116/120的继承标签，用于验证原始包未变动；最终全文复核将其中一处歧义扣分撤销为117/120。这是审核标签变化，没有改变权重或原回答。当前发布结果以 `results/physics120` 为准；不能修改历史代码中的116来伪装当时已得到最终标签。

获取原始评测文件后，可先做原包完整性验证：

```bash
cd research/physics120_eval
python -m student_tools.physics120_comparison \
  --bundle bundle_manifest.json --arm base8b \
  --model-dir <原Qwen3-8B路径> \
  --output results/package_check_new --validate-package-only
```

## 各层验证

| 层次 | 当前提供 | 不能替代 |
|---|---|---|
| 软件行为 | Python/前端回归，合成传输夹具 | 语言模型真实正确率 |
| 冻结身份 | 基座、tokenizer、适配器SHA及504张量检查 | 跨硬件完全相同的所有生成结果 |
| 离线解释 | 120题四模型汇总、题型图、指标定义 | 新来源确认性测试、专家盲审 |
| 页面接入 | 真实Python→focused1186→引用报告链路 | 完整系统长期稳定性和成本测量 |

本批120题是在原128题结果已知后形成的后验子集，8个基础工况共享来源。将其称为“120题比较集”比“120个独立测试工况”准确。后续若继续据这些题调整模型，应使用新的未参与开发的来源评估泛化。
