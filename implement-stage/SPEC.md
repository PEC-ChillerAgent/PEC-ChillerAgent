# 第一阶段实现规格

目标：实现可独立调用的冷水机组工具、持久数据集引用和统一输入输出，与现有工作台数值结果一致。

输入：带设备 ID、显式列映射和单位的 JSON/CSV/Excel 数据；分析请求引用 dataset_id，选择 physics、simulate 或 compare。

输出：类型化工具结果、指标及单位、缺测项、数据/模型警告、证据引用和可查询完整记录；SQLite 存储数据集与运行记录，CLI 可导出 JSON。

成功命令：`F:/Anaconda/envs/modelica/python.exe -B -m pytest -q -p no:cacheprovider tests energy_agent/tests`；`python -m energy_agent demo --output outputs/agent_stage1_demo.json`。

Base commit：none (not a git repo)，已执行 git rev-parse HEAD 确认。

范围：本地单用户同步工具服务；复用现有数值模型。对话、语言模型连接、训练/校准/优化工具、异步任务及其他设备模型留待后续阶段。

模式：effort=balanced，ask=never，assurance=draft。复用现有 FastAPI、Pydantic、SQLite 和模型服务，不新增依赖。
