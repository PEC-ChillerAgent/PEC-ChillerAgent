# 第一阶段交付报告

第一阶段已实现：持久数据集引用、chiller_analyze工具、统一输入输出和证据，以及Python/CLI/HTTP调用。现有数值模型及网页继续复用。F0–F3全部验收通过，无第一阶段占位实现。

## 会影响结果含义的选择

以下为当前全部semantic记录，逐项保留：

| ID | 请求未确定的内容 | 选择 | Class | Source |
|---|---|---|---|---|
| A-003 | 源单位 | JSON 接入必须显式给 temperature_unit、flow_unit、power_unit；物性沿用工作台默认并固化。保留工作台 ASHRAE 表头推断行为，暴露原始和生效 schema 及推断警告 | semantic | default |
| A-006 | 模型默认行为 | 时间、初态、启停、物性及求解规则复用工作台；全部有效设置进入结果。沿用默认初态不代表已现场校准 | semantic | default |
| A-007 | 结果状态 | success=所选任务目标完整；partial=部分目标缺测、有效性警告或越界；needs_input=必要输入缺失/无效或无可用目标；failed=求解失败；不编造缺失值 | semantic | default |
| A-008 | 曲线外推 | 保留原模型外推数值；明确 partial、越界数量/行号/范围，比较统计排除越界点，不作为故障确诊 | semantic | default |
| A-009 | 统计定义 | 普通汇总采用有效输出点算术均值并明确 sample_mean、单位、来源与有效数；不称为时段 COP/能耗 | semantic | default |
| A-010 | 比较任务 | compare 只接受 series，一条源记录对应一条预测，按来源行配对；至少有功率/出水温度之一的实测值；统计 MAE/RMSE/bias/n，不诊断故障，不自动删除暖机段 | semantic | default |
| A-015 | 研究与生产边界 | 只封装现有物理/EIR分析，不调用训练、校准、优化或现场控制；数值验收不代表目标现场准确率 | semantic | default |
| A-016 | 不可信模型数值 | 保留底层负功率/负能耗系数记录用于复核，但不纳入模型汇总和比较统计；部分有效时partial，全部无有效模型目标时needs_input，并披露invalid_model_rows | semantic | default |
| A-017 | 已映射比较目标的完整性 | 各比较目标独立选择有效域内配对并分别报告n；已映射目标缺测须披露并标为partial，未映射的可选目标不强制要求 | semantic | sweep |
| A-018 | 布尔启停状态 | 沿用工作台对true/false作为1/0的接受规则，不把有效布尔启停误判为缺测 | semantic | sweep |

## 可执行验收

- `python -B -m pytest -q -p no:cacheprovider tests energy_agent/tests`：94 passed，原有53项与新增41项均通过。
- `python -B -m energy_agent demo --output outputs/agent_stage1_demo.json`：exit=0；418 kW、COP4.18，完整统一结果已导出。
- `python -B -m energy_agent tools --output outputs/agent_stage1_tool_contracts.json`：exit=0；输入/输出JSON Schema可读取。
- 独立Uvicorn服务实际完成loopback HTTP登记数据集→调用工具→下载完整JSON；outputs/agent_stage1_http_demo.json保存结果。
- 测试覆盖数据持久化和重启、显式源单位、不可变引用、设备匹配、缺测、源顺序、稳态/动态数值一致、控制列、模型越界、比较完整性、数值失败、证据复算、文件工作表、分页、CLI和已有运行读取。

## 审查

原生审查请求为gpt-6-astra/xhigh，实际身份未由运行时返回。首轮发现3项未声明选择（其中2项semantic），相关代码和台账已更新；第二轮未声明0、stale0、concrete_failures0、verdict=clean。状态为unverified-family/provisional，只作为补充审查证据，不能独立证明正确性。原文和路由记录保存在同目录。

## 接口选择

ASK=never，语义与接口选择均在实现前或审查发现后明确记录。接口项目如下：

| ID | 请求未确定的内容 | 选择 | Class | Source |
|---|---|---|---|---|
| A-001 | 持久化与部署范围 | 本地单用户 SQLite；默认 outputs/energy_agent/agent.sqlite3，可通过 ENERGY_AGENT_DATA_DIR 或应用工厂配置 | interface | default |
| A-002 | 数据集修改方式 | 每次登记创建不可变 dataset_id/version=1；保留原记录、设备 ID、源信息、请求及实际生效 schema；不提供更新/删除 | interface | default |
| A-004 | 设备身份 | 登记与调用都指定 asset_id，执行时必须匹配；阶段一不实现独立设备资产管理系统 | interface | default |
| A-005 | 首版任务与模型选择 | physics/simulate/compare；仿真必须显式提供 simulation.record_id 或 custom 参数配合 record_id=custom，不自动选择示例机组 | interface | default |
| A-011 | 大结果与证据 | 默认返回最多5条预览、结构化指标和完整记录引用；SQLite 保存完整输出与来源行；HTTP 支持分页和完整 JSON 导出 | interface | default |
| A-012 | 接口入口 | Python Runtime/注册表、CLI、/agent/v1 路由；路由接入现有应用，也提供独立应用工厂；本阶段无聊天端点 | interface | default |
| A-013 | 处理和限额 | 复用工作台，不排序/去重/插值；单数据集1–20000行，文件10MB；记录值是JSON标量，拒绝非有限数和未知映射列 | interface | default |
| A-014 | 错误协议 | 结构/类型错误HTTP422，未知引用404，设备不匹配409；可执行性不足返回HTTP200的needs_input结果；CLI needs_input退出2、failed退出1、success/partial退出0 | interface | default |
| A-019 | 来源行示例上限 | 所有摘要行号字段命名为source_row_examples（域外字段亦明确examples）；最多10个唯一一基行号。完整选择由artifact与selection复算 | interface | sweep |
| A-020 | 本轮开发已保存运行的读取 | 当前SQLite内实际存在旧source_rows字段的运行；读取接受其作为别名并统一输出新examples字段，不修改保存的原始记录或模型输出 | interface | sweep |

## 范围

本地单用户、SQLite、同步分析。对话与大模型连接、训练/校准/优化工具、异步任务、独立资产管理、多用户鉴权及其他设备模型留待后续阶段。目标机组现场适配标记为not_assessed，原模型结果一致不等于现场诊断准确率。

使用说明见 ../energy_agent/README.md。没有第一阶段live stub。根目录不是Git仓库，因此未初始化Git或创建提交。
