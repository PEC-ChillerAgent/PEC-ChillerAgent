# 蒸馏方案配套模板

完整操作和来源见 [项目指导](../../docs/chiller_distillation_2026-11-02.md)。

本目录是准备材料，没有训练产物，没有自动造数、自动评分或生产路由实现；未向 DeepSeek 发送请求。

- `qwen3_8b_lora_sft.yaml`：针对 H100 80GB / 550.90.12 驱动的保守兼容栈起始参数；服务器上未执行。使用 LLaMA-Factory v0.9.3 的 `qwen3` 模板和 `enable_thinking: false`。
- `qwen3_8b_export.yaml`：导出模板；部署前修改为实际选中的适配器/checkpoint。
- `dataset_info.json`：应放入服务器配置的 `data/processed/`。`train.jsonl` 和 `val.jsonl` 尚不存在，必须先准备并审核。
- `format_examples.json`：三个格式示例，不能当作正式数据集或训练规模。工具观测在本机用当前项目真实执行，回答由本次编写；无教师调用。
- `eval_dev_seed.jsonl`：30道开发种子题。`setup` 是待评测程序或人工准备的场景说明，不会自动注册数据集；`gold_numeric` 是离线评分参考。题库不含自动评分实现。

先将数据按原始文件/试验/资料来源分组，分出 train、val 和最终封存测试，再生成窗口和问题改写。最终封存题不能从此可见开发题简单改写后冒充独立测试。

`standalone_qa` 用于离线答题，可输出解释性数字；`agent` 须通过真实项目执行，遵守绑定、工具和 fact 引用。只有数值或措辞相似，不代表端到端成功；同时统计原始模型行为、修复和事实报告回退。

模板检查不等于服务器环境、训练质量和模型接入验收。下一步先准备资料和小批样本，跑通原始学生的工具协议，再启动 SFT。
