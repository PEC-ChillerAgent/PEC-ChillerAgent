# 冷水机组工具与智能分析运行层

已实现冷水机组工具、持久数据集引用和统一输入输出。Python、CLI、HTTP 共用同一 Runtime、注册表和工具实现；实际数值计算仍由 `chiller_app` 完成。当前任务为 `physics`、`simulate`、`compare`。

当前页面默认采用focused1186学生路径：后台先运行Python物理工具，再按当前证据解释。外部模型工具循环保留为显式可选入口。启动应用后访问 `/chat`；部署见[学生说明](../docs/student_deployment.md)，整体流程见[项目README](../README.md#项目架构)。

## 直接运行

在项目根目录、已安装 requirements.txt 的环境中：

```powershell
python -B -m energy_agent tools --output outputs/tool_contracts.json
```

该命令导出工具定义与输入契约，不需要模型或示例文件。实际分析使用自己通过工作台或API登记的数据。

默认数据库为 `outputs/energy_agent/agent.sqlite3`。重启后数据集和运行 ID 保持可查。CLI 可在子命令前使用 `--data-dir <目录>`，HTTP/Python 可用 `ENERGY_AGENT_DATA_DIR` 或应用工厂参数配置。本阶段面向本地单用户使用。

## Python 调用

先通过工作台或数据集API登记自己的数据，将占位符替换为实际设备ID和数据集ID。

```python
from energy_agent.runtime import AgentRuntime

runtime = AgentRuntime()
asset_id = "<asset_id>"
dataset_id = "<dataset_id>"
result = runtime.analyze({
    "asset_id": asset_id,
    "dataset_id": dataset_id,
    "task": "physics",
})
print(result.status, result.metrics["COP"].value)
artifact = runtime.repository.get_run(result.run_id)
print(artifact["model_output"]["records"])
```

数据集保存原始记录、请求 schema、生效 schema、源文件/工作表信息和质量摘要。每次登记产生一个不可变 ID，version=1；再次登记是新数据集。源温标、流量和功率单位必须显式提供。无效单元格按原工作台规则保留为空，既不删除原行，也不填补测量。

工作台兼容模式会识别ASHRAE标准表头并推断部分映射/单位；显式源单位策略不覆盖用户声明。`source_schema` 与 `effective_schema` 分别记录声明和生效配置，结果带 `SOURCE_SCHEMA_INFERRED` 提示。

## 仿真和比较

仿真必须显式选定性能记录；使用 `GET /agent/v1/models/chiller` 查看158个水冷记录。也可提供自定义性能参数，要求 `record_id="custom"`。

```python
from chiller_app.model.electric_eir import DEFAULT_RECORD

result = runtime.analyze({
    "asset_id": asset_id,
    "dataset_id": dataset_id,
    "task": "simulate",
    "simulation": {
        "record_id": DEFAULT_RECORD,
        "mode": "steady",
        "kind": "series",
        "setpoint": 5.0,
    },
})
```

必要输入为两侧进水温度、两侧正流量和设定温度。启停未映射时采用 settings.enabled；布尔true/false与原工作台一样按1/0接受；已映射的控制列必须完整有效。设定值和初态使用数据集生效温标。全部有效设置、物性、性能参数、版本及来源信息保存在 metadata 中。

`compare` 使用同样配置，但 `kind` 必须为 `series`，每条源记录最多匹配一条预测；需要至少一种实测功率或出水温度。各目标独立选择有效配对并报告 MAE、RMSE、bias、n；已映射目标缺测时明确披露并标为partial，未映射的可选测量不强制要求。曲线越界和负功率/负能耗系数的模型点不进入比较统计。动态比较不自动排除暖机段，结果记录实际初态。它是模型/测量比较，不直接定位故障。

## 统一结果与证据

`ToolResult` 包含：schema/tool版本、run_id、dataset_id/version、asset_id、task、status、metrics、comparisons、missing_inputs、warnings/errors、model_validity、metadata、evidence、预览记录和完整结果 artifact_id。

| 状态 | 含义 |
|---|---|
| success | 所选任务的必要目标可计算，没有有效性警告 |
| partial | 部分目标缺测，或存在无效输入、模型警告、曲线越界 |
| needs_input | 缺少执行条件、全部模型目标无有效数值，或没有域内可比较的测量对 |
| failed | 数值求解失败，明确保留错误，不生成预测 |

物理任务检查冷量、冷凝热、COP与能量偏差；缺一部分时尽量给出其余结果。仿真任务不要求实测功率或实测出水，实测 COP 缺失不会被模型功率替代。

metrics 的值为有效输出点的 `sample_mean`，明确给出单位、来源和有效点数；它不是时段COP或能耗。恒定仿真展开的输出点不是新增实测样本，input_rows/output_rows分别披露。

每个指标/比较关联 evidence_id，可在 evidence 中查询完整运行 artifact_id、所用列、选择规则、有效数和source_row_examples（最多10个唯一一基行号，明确是示例而非完整选择集）。规则：`finite_values`选择该列有限值；`finite_valid_model`另排除负功率/能耗系数；`paired_in_range`再要求测量/预测均有效且曲线范围内。完整原模型记录可通过 artifact 或分页查询复算。

默认仅返回5条预览，可设置 preview_rows=0–100。完整记录和底层 notes/issues/warnings 保存在数据库，可独立查询和导出。

## HTTP 接口

现有网页应用已挂载工具路由：

```powershell
python -m uvicorn chiller_app.api.fastapi_app:app --host 127.0.0.1 --port 8000
```

也可以单独启动工具服务：

```powershell
python -m uvicorn energy_agent.api.app:app --host 127.0.0.1 --port 8001
```

API 文档为所选服务的 `/docs`。

```text
GET  /agent/v1/health
GET  /agent/v1/tools                          工具定义和输入输出JSON Schema
GET  /agent/v1/models/chiller                 性能记录
POST /agent/v1/datasets                       登记JSON数据集
POST /agent/v1/datasets/upload                CSV/XLSX/XLS文件接入
GET  /agent/v1/datasets                       分页列出数据集
GET  /agent/v1/datasets/{dataset_id}           元数据
GET  /agent/v1/datasets/{dataset_id}/records   分页源记录
POST /agent/v1/tools/chiller_analyze/execute   按dataset_id执行分析
GET  /agent/v1/runs/{run_id}                   统一结果
GET  /agent/v1/runs/{run_id}/records           分页完整输出
GET  /agent/v1/runs/{run_id}/artifact          完整JSON下载
GET/PUT /agent/v1/llm/config                  模型连接配置（密钥不回显）
POST /agent/v1/llm/test                       所配置模型的真实连接测试
POST /agent/v1/chat                          默认学生：先物理计算再解释
POST /agent/v1/analysis                      默认学生分析
GET  /agent/v1/analysis/config               学生配置与身份
POST /agent/v1/chat/external                 显式外部模型工具循环
GET  /agent/v1/chat/sessions                  历史会话
GET  /agent/v1/chat/sessions/{session_id}      会话详情
GET  /agent/v1/chat/sessions/{session_id}/turns/{turn_id}/report  Markdown报告
```

登记JSON的结构见应用`/docs`中的`POST /agent/v1/datasets`；请求包含`asset_id`、`records`和`schema`。创建后将返回的dataset_id与同一asset_id用于分析请求。文件接入使用multipart：`asset_id`、JSON文本字段`schema`、文件字段`file`，可选`sheet_name`。限额沿用工作台：10MB、20000行。schema中不存在的来源列拒绝登记。

结构/类型错误HTTP422、未知引用404、设备不匹配409；缺测和不可执行工况返回HTTP200的结构化needs_input，不伪造数值。记录分页offset≥0、limit=1–1000，数据集列表limit≤100。

## CLI

```powershell
python -m energy_agent dataset-create --request <自己的数据登记JSON文件> --output outputs/dataset_info.json
python -m energy_agent analyze --request <包含asset_id和dataset_id的JSON文件> --output outputs/analysis.json
python -m energy_agent dataset-show --id <dataset_id>
python -m energy_agent run-export --id <run_id> --output outputs/full_run.json
python -m energy_agent tools --output outputs/tool_contracts.json
```

success/partial退出0，needs_input退出2，failed退出1。JSON写入--output或标准输出。

## 实际源码目录

```text
energy_agent/
├─ runtime.py                 公共Python入口
├─ __main__.py                CLI
├─ api/
│  ├─ app.py                  独立FastAPI应用工厂
│  ├─ routes.py               工具和数据集HTTP接口
│  ├─ chat.py                 模型连接、聊天、历史和报告HTTP接口
│  └─ focused_analysis.py     默认学生分析接口
├─ config/
│  ├─ settings.py             数据目录配置
│  └─ llm.py                  本地模型配置与环境覆盖
├─ contracts/
│  ├─ datasets.py             数据集及源单位契约
│  ├─ tools.py                请求、结果、指标和证据契约
│  └─ chat.py                 会话、连接与事实片段契约
├─ registry/tools.py          工具发现和确定性路由
├─ storage/
│  ├─ repository.py           SQLite数据集及运行存储
│  └─ chat.py                 会话、协议历史和并发租约
├─ tools/
│  └─ chiller/
│     ├─ backend.py           复用原工作台数值边界
│     └─ tool.py              缺测检查、分析和结构化结果
├─ tests/                     存储、数值一致性、缺测、越界、API和CLI验收
├─ agents/
│  ├─ chat.py                 有调用上限的模型/工具循环
│  ├─ reporting.py            数值事实替换与证据报告
│  └─ student_explanation.py  Python计算先行的学生解释
├─ providers/compatible.py    OpenAI兼容Chat Completions客户端
└─ prompts/system.md          工具选择、缺测与数值证据约束
```

验证命令：

```powershell
python -B -m pytest -q -p no:cacheprovider tests energy_agent/tests
```

测试使用真实Python计算与合成模型传输，覆盖当前运行引用、身份检查、缺测、超时、格式错误和回退；不调用付费API或启动训练。它验证软件行为，不能替代真实GPU回答质量评估。

自动训练/校准/优化及设备控制未接入聊天工具。机组现场适配状态标记为not_assessed；底层数值一致性不代表现场诊断准确率。
