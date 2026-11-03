# 第一阶段假设与接口选择

ASK mode: never。以下选择在对应实现前登记。

| ID | 请求未确定的内容 | 选择 | Class | Source |
|---|---|---|---|---|
| A-001 | 持久化与部署范围 | 本地单用户 SQLite；默认 outputs/energy_agent/agent.sqlite3，可通过 ENERGY_AGENT_DATA_DIR 或应用工厂配置 | interface | default |
| A-002 | 数据集修改方式 | 每次登记创建不可变 dataset_id/version=1；保留原记录、设备 ID、源信息、请求及实际生效 schema；不提供更新/删除 | interface | default |
| A-003 | 源单位 | JSON 接入必须显式给 temperature_unit、flow_unit、power_unit；物性沿用工作台默认并固化。保留工作台 ASHRAE 表头推断行为，暴露原始和生效 schema 及推断警告 | semantic | default |
| A-004 | 设备身份 | 登记与调用都指定 asset_id，执行时必须匹配；阶段一不实现独立设备资产管理系统 | interface | default |
| A-005 | 首版任务与模型选择 | physics/simulate/compare；仿真必须显式提供 simulation.record_id 或 custom 参数配合 record_id=custom，不自动选择示例机组 | interface | default |
| A-006 | 模型默认行为 | 时间、初态、启停、物性及求解规则复用工作台；全部有效设置进入结果。沿用默认初态不代表已现场校准 | semantic | default |
| A-007 | 结果状态 | success=所选任务目标完整；partial=部分目标缺测、有效性警告或越界；needs_input=必要输入缺失/无效或无可用目标；failed=求解失败；不编造缺失值 | semantic | default |
| A-008 | 曲线外推 | 保留原模型外推数值；明确 partial、越界数量/行号/范围，比较统计排除越界点，不作为故障确诊 | semantic | default |
| A-009 | 统计定义 | 普通汇总采用有效输出点算术均值并明确 sample_mean、单位、来源与有效数；不称为时段 COP/能耗 | semantic | default |
| A-010 | 比较任务 | compare 只接受 series，一条源记录对应一条预测，按来源行配对；至少有功率/出水温度之一的实测值；统计 MAE/RMSE/bias/n，不诊断故障，不自动删除暖机段 | semantic | default |
| A-011 | 大结果与证据 | 默认返回最多5条预览、结构化指标和完整记录引用；SQLite 保存完整输出与来源行；HTTP 支持分页和完整 JSON 导出 | interface | default |
| A-012 | 接口入口 | Python Runtime/注册表、CLI、/agent/v1 路由；路由接入现有应用，也提供独立应用工厂；本阶段无聊天端点 | interface | default |
| A-013 | 处理和限额 | 复用工作台，不排序/去重/插值；单数据集1–20000行，文件10MB；记录值是JSON标量，拒绝非有限数和未知映射列 | interface | default |
| A-014 | 错误协议 | 结构/类型错误HTTP422，未知引用404，设备不匹配409；可执行性不足返回HTTP200的needs_input结果；CLI needs_input退出2、failed退出1、success/partial退出0 | interface | default |
| A-015 | 研究与生产边界 | 只封装现有物理/EIR分析，不调用训练、校准、优化或现场控制；数值验收不代表目标现场准确率 | semantic | default |
| A-016 | 不可信模型数值 | 保留底层负功率/负能耗系数记录用于复核，但不纳入模型汇总和比较统计；部分有效时partial，全部无有效模型目标时needs_input，并披露invalid_model_rows | semantic | default |
| A-017 | 已映射比较目标的完整性 | 各比较目标独立选择有效域内配对并分别报告n；已映射目标缺测须披露并标为partial，未映射的可选目标不强制要求 | semantic | sweep |
| A-018 | 布尔启停状态 | 沿用工作台对true/false作为1/0的接受规则，不把有效布尔启停误判为缺测 | semantic | sweep |
| A-019 | 来源行示例上限 | 所有摘要行号字段命名为source_row_examples（域外字段亦明确examples）；最多10个唯一一基行号。完整选择由artifact与selection复算 | interface | sweep |
| A-020 | 本轮开发已保存运行的读取 | 当前SQLite内实际存在旧source_rows字段的运行；读取接受其作为别名并统一输出新examples字段，不修改保存的原始记录或模型输出 | interface | sweep |

## Notes

基础文件不是 Git 仓库，因此实现记录使用具体文件列表，不初始化仓库。
