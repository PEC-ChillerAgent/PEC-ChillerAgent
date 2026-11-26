# 训练源码与私有数据准备

当前应用入口使用 `chiller_student`。`research/focused1186_sft/`保留实际SFT训练代码、配置和校验逻辑；它不会被应用导入，也不随CI启动GPU作业。仓库不提供训练集、测试题库、参考答案或模型比较结果。

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

## 数据与代码的边界

- `training_plan.json`保存训练配置和样本访问次序；编号不包含问题或答案正文。
- `bundle_manifest.json`和`PUBLICATION_MANIFEST.json`保存版本、文件名与哈希，用于检查私有材料是否对应原训练。
- `student_tools/`中的质量检查、编码检查和验证函数是训练代码依赖，因此保留；这些函数不是测试题库。
- 私有训练数据、参考答案和运行产物应放在被忽略的`data/`、`checks/`或`results/`目录，不提交到GitHub。

如果希望训练新的数据集，应另建实验目录和清单，保留原始快照；不要复用原实验哈希或覆盖历史模型。

## 从应用导出待审核教师记录

外部模型对话的请求、可见回复、工具运行和校验结果保存在SQLite的`chat_audit_events`中；单独运行物理工作台不会生成教师回复。使用实际轮次编号和原始数据来源组导出：

```bash
python -m energy_agent.distillation.export \
  --db outputs/energy_agent/agent.sqlite3 \
  --turn <turn_id> \
  --source-group <原始数据来源组> \
  --output outputs/student_candidates/sample_review.json
```

该命令只读数据库，不调用模型，不覆盖已有输出。导出省略具名凭据和供应商私有思考字段，但不会对任意用户文本进行全面脱敏；公开前仍需审核。历史缺失的请求、版本或用量不会自动补出。

同一原始试验的切片、缺测变体和改写问题应放在同一来源组，再按来源组划分训练与验证材料。导出默认`training_approved=false`、`split=unassigned`，需经过内容审核、去重、来源划分和原生token/loss mask检查；失败回答与工具回退报告不能直接当作正确教师答案。此导出器提供候选材料，不能直接生成可用SFT训练集。

## 软件与部署验证

| 层次 | 当前提供 | 不能替代 |
|---|---|---|
| 软件行为 | Python/前端回归，合成传输夹具 | 语言模型真实正确率 |
| 冻结身份 | 基座、tokenizer、适配器SHA及504张量检查 | 跨硬件完全相同的所有生成结果 |
| 页面接入 | 真实Python→focused1186→引用报告链路 | 完整系统长期稳定性和成本测量 |

`tests/`与`energy_agent/tests/`保留必要的软件回归检查；`tests/reference/`保存物理模型对齐用的Modelica参考输出。它们验证代码行为，不属于学生模型训练集或语言模型测试题库。
