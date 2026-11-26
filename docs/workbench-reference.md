# 冷水机组分析与暖通 Agent 工程

当前仿真模型为 Buildings 13.0.0 ElectricEIR 的 Python 方程实现，支持 158 组水冷机组参数、自定义性能曲线、稳态/动态仿真、设定温度和启停时序。

现有应用负责数据接入、水侧计算、机组仿真、参数校准和结果展示；`energy_agent/` 已实现冷水机组工具、持久数据集引用、统一结果，以及第二阶段的兼容模型连接、对话入口、工具调用和证据报告。

## 运行现有应用

建议使用 Python 3.11 或 3.12。在项目目录和已准备的虚拟环境中执行：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn chiller_app.api.fastapi_app:app --reload --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000/>；API 文档为 <http://127.0.0.1:8000/docs>。本机已有环境可使用 `F:/Anaconda/envs/modelica/python.exe`。

智能分析入口为 <http://127.0.0.1:8000/chat>，默认使用focused1186学生服务。原工作台录入或上传单条工况后，点击“转入智能分析”即可绑定数据与源单位。学生部署见[部署说明](student_deployment.md)；需要外部模型时，在新对话中显式选择外部模式，再填写服务配置。

页面可直接使用，不要求训练，也不依赖 ASHRAE 数据文件：

- 单条工况：手动输入或载入示例，选择源单位后计算。
- 文件导入：CSV、XLSX、XLS；支持选择 Excel 工作表，最多 10 MB / 20,000 行；在内存中解析。
- 物理计算：实测制冷量、冷凝热、COP、稳态能量平衡偏差；缺少必要测量的输出为 null，页面显示“—”。
- ElectricEIR：选择性能记录或自定义曲线，执行稳态逐行求解或动态时间序列仿真。
- 结果：指标、警告、按单位分组的自选曲线、来源行号、CSV/JSON 导出及模型参数记录。

## 数据和模型约定

| 任务 | 必要信息 |
|---|---|
| 实测制冷量 | 冷冻水进出温度、冷冻侧流量 |
| 实测冷凝热 | 冷却水进出温度、冷却侧流量 |
| 实测 COP | 实测制冷量及正实测功率 |
| 稳态能量平衡 | 两侧进出温度、流量及同一计量范围的功率 |
| ElectricEIR 稳态仿真 | 两侧进水温度、两侧正流量、出水设定温度、启停和机组性能参数 |
| ElectricEIR 动态仿真 | 仿真输入，另加时间设置、连续试验标识、初始状态和时间常数 |
| ElectricEIR 功率校准 | 有依据的健康稳态数据、实测功率及匹配的性能记录；独立验证数据可选 |

输入需显式映射源列和单位。支持温度 K/°C/°F、流量 kg/s/m³/s/m³/h/US gpm、功率 W/kW。相同请求内同类物理量共用源单位；混用单位的文件需先统一。

工作台默认使用 Buildings 水介质常数 cp=4184 J/(kg·K)、密度=995.586 kg/m³；研究服务的 DataSchema 默认 cp=4180、密度=1000。比较结果时需匹配实际生效物性。显式指定 cp=4180、密度=1000 时，10/5°C、30/35°C、72/90 m³/h、100 kW 工况的冷量为 418 kW、冷凝热 522.5 kW、COP 4.18、能量偏差 4.5 kW。

实测功率和出水温度不驱动 ElectricEIR 状态，仅用于比较。实测 COP 与模拟 COP 分开输出；缺少实测功率时不能混用模型功率生成实测 COP。

动态使用 SciPy BDF，热容为额定质量流量 × 时间常数 × 比热。各 run_id 独立初始化；未提供初温时冷冻出水为 5°C、冷却出水为 25°C。输入在 t_i 至下一点保持，首点输出初态，末点不外推。组内时间必须严格递增，不自动排序、去重或插值。稳态模式逐行独立求解，忽略初态和热容。

动态储热、性能曲线越界或基础规则提示不等同于真实故障确诊。ElectricEIR 包含理想设定值控制，功率不含水泵和风机；目标机组需要匹配或校准参数。它不包含完整制冷剂循环、水力网络和中央空调系统模型。

## 当前 API

```text
GET  /health
GET  /models                         仅列出 ElectricEIR 仿真模型
GET  /model/definition               当前模型、状态、参数和方程
GET  /workbench/eir/catalogue         水冷性能记录
POST /workbench/upload               内存解析文件及选择工作表
POST /workbench/run                  物理计算或 ElectricEIR 仿真
POST /model/electric-eir/simulate     ElectricEIR 仿真
POST /model/electric-eir/calibrate    健康稳态单参数功率校准
POST /data/validate                  数据字段检查
POST /data/clean                     研究数据规范化和清洗
POST /physics/calculate              水侧物理计算及规则提示
POST /model/train                    稳态性能研究模型训练
POST /model/predict                  稳态性能预测
POST /model/validate                 独立数据集验证
POST /model/optimize                 受约束离线建议原型
```

物理计算请求示例见[合成请求](../examples/generic_schema_request.json)。ElectricEIR请求和对齐范围见[Buildings说明](buildings_alignment.md)。

## 工程结构

```text
chiller_model/
├─ energy_agent/          设备工具、模型连接、对话、数据集和证据报告
├─ chiller_app/
│  ├─ api/                FastAPI、工作台和应用服务
│  ├─ data/               单位、字段映射与清洗
│  ├─ model/              水侧计算、ElectricEIR、校准与性能研究
│  ├─ diagnosis/          规则检查
│  └─ web/                当前网页
├─ tests/                 Python/API、图表及 Modelica 参考对照
├─ chiller_student/       focused1186推理、协议及输出检查
├─ research/              最终SFT训练源码快照，不含数据集或题库
├─ examples/              输入协议示例
├─ docs/                  模型、研究与 Agent 设计说明
└─ outputs/               运行数据及报告，不进入Git仓库
```

Agent的实际目录树见[工具说明](../energy_agent/README.md)，模块关系见[当前架构](architecture.md)。

## 验证

```powershell
python -B -m pytest -q -p no:cacheprovider tests energy_agent/tests
node --check chiller_app/web/app.js
node --check chiller_app/web/chat.js
node tests/test_chart_utils.cjs
node tests/test_chat_ui.cjs
```

指定参数和工况下的OpenModelica动态/稳态参考文件位于[tests/reference](../tests/reference/)，事件对齐与数值对照纳入测试。该结果不替代目标现场机组验证。

## 第一阶段工具调用

```powershell
python -B -m energy_agent demo --output outputs/agent_stage1_demo.json
```

已接入现有应用的 `/agent/v1`，支持登记数据集、执行 `chiller_analyze`、查询证据和下载完整结果。详细接口、Python示例和状态含义见[工具使用说明](../energy_agent/README.md)。

## 保留的研究入口

稳态性能研究仍可通过 `/model/train`、`/model/predict`、`/model/validate` 和 `/model/optimize` 调用。LLM学生训练及比较源码位于[research](../research/README.md)，与上述数值性能模型训练不同；所需材料和复现范围见[复现说明](research_reproduction.md)。
