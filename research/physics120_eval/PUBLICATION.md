# 120题开放权重基线评测源码

入口为 `student_tools/physics120_comparison.py`，支持base8b与qwen14b。历史包复用学生原回答；保留的116标签校验是当时快照，最终审核结果117/120见结果目录。

这是**缺少数据与权重的历史源码快照**。原 `.py` / `.sh` 文件保持字节；新增本说明及 `PUBLICATION_MANIFEST.json`，不会改变原实验结果。

先阅读[复现条件](../../docs/research_reproduction.md)。`PUBLICATION_MANIFEST.json.required_external_files`列出缺失原包文件和哈希；未补齐前运行会拒绝执行。不要为通过检查而删除校验、伪造样本或覆盖历史输出。

没有在本次发布中启动训练、GPU推理或API请求。应用部署使用根目录 `scripts/`，不运行这里的训练启动脚本。

本目录README.md是原始包的历史记录；当前发布范围以本说明和项目复现文档为准。
