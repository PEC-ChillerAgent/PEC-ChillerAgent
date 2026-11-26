# 研究源码快照

这里保留与最终focused1186及120题比较直接相关的两套历史源码；日常应用从仓库根目录启动，不需要运行本目录。

| 目录 | 内容 | 数据是否随附 |
|---|---|---|
| [focused1186_sft](focused1186_sft/PUBLICATION.md) | 最终SFT、固定训练计划、精度和编码核验 | 否 |
| [physics120_eval](physics120_eval/PUBLICATION.md) | 原120题开放权重基线评测及原包核验 | 否 |

各快照保持原 `.py` / `.sh` 文件字节，保留历史命名与默认服务器路径；实际使用可通过已有CLI参数指定路径。两个快照中的 `student_tools` 依赖版本应分别使用，不加入全局PYTHONPATH，不与应用 `chiller_student` 混装。

`PUBLICATION_MANIFEST.json`列出发布文件哈希及尚需获取的原包材料。未包含教师密钥、真实数据、样本答案、历史权重或GPU运行产物。完整条件、历史分数变化和评测范围见[复现说明](../docs/research_reproduction.md)。
