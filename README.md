# PEC-ChillerAgent

**面向冷水机组运行分析的物理证据约束智能体**

*Physical-evidence-constrained analysis for water-cooled chillers.*

PEC-ChillerAgent 将 **Python物理计算、可追溯运行证据与领域学生模型** 连接起来。用户输入工况并提问，系统执行计算，再由 `focused1186` 根据本次结果解释制冷量、功率、COP、缺测和判断边界。页面名称保留为 **Chiller Lab**。

默认学生路径已接入项目：**Python负责计算，Qwen3-8B＋单个LoRA负责解释，程序负责校验与事实引用呈现**。服务异常或回答检查失败时显示当前工具事实报告，默认路径不调用DeepSeek。项目同时保留可显式选择的外部模型工具调用路径。

[快速启动](#快速启动) · [项目架构](#项目架构) · [目录树](#目录树) · [学生部署](#学生模型部署) · [学生训练](#学生训练) · [API说明](#api与代码调用) · [常见问题](#常见问题)

## 已实现的功能

| 模块 | 实现内容 | 主要入口 |
|---|---|---|
| 数据接入 | 单条输入、CSV/XLSX/XLS上传、列映射、源单位声明、质量检查 | `/`、`/workbench/upload`、`/agent/v1/datasets` |
| 水侧物理计算 | 制冷量、冷凝热、输入功率、COP、代数能量平衡偏差 | `physics`工具、`/physics/calculate` |
| ElectricEIR仿真 | 性能曲线、稳态及动态计算、实测比较、适用范围提示 | 工作台、`simulate` / `compare`工具 |
| 学生智能分析 | 当前单条工况＋完整问题＋Python证据→自然语言解释 | `/chat`、`/agent/v1/analysis` |
| 证据呈现 | 事实编号、指标值、单位、有效点数、运行ID及JSON Pointer | 点击回答引用、下载计算产物和报告 |
| 会话与审计 | 数据集绑定、历史会话、原始模型输出与执行记录 | SQLite、`/agent/v1/chat/sessions` |
| 外部模型兼容 | 用户主动选择后进行受限工具调用；数据检查、物理计算、仿真及比较 | `/agent/v1/chat/external` |
| 回退 | 身份、网络、输出协议或已知断言检查失败时返回本次工具事实 | `report_mode=tool_facts` |

**当前默认学生的使用范围：单行物理工况解释。** 工作台能够处理多行数据和动态仿真；这些能力不等同于学生已支持动态仿真解释、知识检索、跨轮指代或故障确诊。学生每次使用完整问题与当前绑定数据重新计算，不沿用上一条回答的数值。

## 项目架构

**分析流程：** 用户问题与工况 → Python物理计算 → 证据与待答清单 → 学生模型解释 → 校验与报告。

1. **绑定输入**：保存原始数据、映射、源单位和生效参数，生成不可变 `dataset_id`。
2. **执行Python**：`AgentRuntime` 调用冷水机组工具，生成本次 `run_id` 和完整计算产物。
3. **组织证据**：将指标值、单位、有效点数、缺项和运行来源组织为类型化事实；从问题编译待答清单。
4. **学生解释**：通过受认证HTTP服务调用冻结的 `focused1186`；返回包含 `{{fact:F3}}` 等引用的解释文本。
5. **校验呈现**：核对模型身份、请求绑定、格式、引用、数值和部分已知矛盾；通过后填入本次事实值，失败则显示工具事实。
6. **持久保存**：保存会话、工具运行、模型原始返回、检查结果和报告，以便复查。

程序检查是有限检查，不是对所有自然语言推理的完备证明。学生正文与程序事实报告在接口中有不同标识，工具回退不计学生回答成功。

## 目录树

```text
PEC-ChillerAgent/
├── README.md                              # 项目入口与使用说明
├── requirements.txt                       # 本机应用、计算及测试依赖
├── requirements-student.txt               # 冻结GPU推理环境版本
├── .env.example                           # 配置示例，不会自动加载
├── .github/workflows/tests.yml            # 软件回归CI
├── chiller_app/                           # 物理计算、仿真和Web工作台
│   ├── api/                               # FastAPI、工作台、底层计算接口
│   ├── data/                              # 源数据映射、单位和清洗
│   ├── model/
│   │   ├── physics_model.py               # 水侧公式
│   │   ├── electric_eir.py                # ElectricEIR稳态与动态模型
│   │   ├── buildings_eir_catalogue.json    # Buildings性能参数目录
│   │   ├── eir_calibration.py             # 功率尺度校准
│   │   ├── performance_model.py           # 数据驱动性能模型
│   │   └── BUILDINGS_LICENSE.txt          # 第三方许可
│   ├── diagnosis/                         # 规则诊断辅助模块
│   └── web/                               # 原生HTML/CSS/JavaScript页面
├── energy_agent/                          # 工具、会话、证据与模型接入
│   ├── runtime.py                         # Python公共入口
│   ├── __main__.py                        # 命令行入口
│   ├── api/                               # 数据集、运行、聊天及学生API
│   ├── agents/
│   │   ├── student_explanation.py         # 默认学生：先计算后解释
│   │   ├── student_physics.py             # 共用执行边界及旧选择器兼容
│   │   ├── chat.py                        # 可选外部模型工具循环
│   │   └── reporting.py                   # 事实引用渲染与报告
│   ├── config/                            # 数据路径、学生及外部模型配置
│   ├── contracts/                         # Pydantic请求、事实和结果契约
│   ├── providers/                         # HTTP传输、身份检查和审计
│   ├── registry/                          # 工具注册与发现
│   ├── storage/                           # SQLite数据集、运行和会话
│   ├── tools/chiller/                     # 冷水机组确定性工具实现
│   ├── distillation/export.py             # 教师采集记录导出为待审核样本
│   ├── prompts/system.md                  # 外部Agent工具与证据提示词
│   └── tests/                             # 工具、API、引用和回退测试
├── chiller_student/                       # 当前应用的学生推理及证据协议
│   ├── configure.py                       # 绑定已有模型与私有凭据
│   ├── service.py                         # focused1186 HTTP服务
│   ├── check_connection.py                # 只读健康与身份检查
│   ├── focused_contract.py                # 冻结身份与请求协议
│   ├── planned_task_contract_v2.py         # 问题待答清单
│   ├── selection_inference.py             # 冻结基座＋单LoRA推理引擎
│   ├── greedy_generation.py               # 显式greedy生成控制
│   ├── adapter_precision.py               # FP32适配器张量核验
│   ├── focused_output.py                  # 应用输出数值检查
│   └── ...                                # 类型化事实和历史兼容检查模块
├── deployment/focused1186.json            # 模型、tokenizer及适配器SHA-256
├── scripts/                               # 应用、GPU服务与SSH隧道启动
├── research/                              # 与应用隔离的训练源码快照
│   └── focused1186_sft/                   # 最终SFT代码与配置，不含训练样本
├── docs/                                  # 仅保留部署与训练准备说明
│   ├── student_deployment.md              # GPU服务、本机连接与故障排查
│   └── research_reproduction.md           # SFT材料准备与教师记录导出
└── tests/                                 # 物理、工作台和前端回归
    └── reference/                         # Modelica参考模型与仿真输出
```

运行时生成的 `outputs/`、`.student.local.json` 和 `.student_credentials/` 不入库。`research/`保留历史源码命名空间 `student_tools`，应用实际使用 `chiller_student`；两者不是两套同时运行的学生模型。

**仓库只发布训练代码、Agent系统及配套文档。** 训练集、测试题目、参考答案、评测结果和模型权重由本地单独保存。`tests/`是软件回归检查，`buildings_eir_catalogue.json`是仿真所需性能参数；它们不属于学生模型的训练集或测试题库。

## 快速启动

### 1. 只运行计算工作台

建议Python 3.11。Windows PowerShell：

```powershell
git clone https://github.com/PEC-ChillerAgent/PEC-ChillerAgent.git
cd PEC-ChillerAgent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn chiller_app.api.fastapi_app:app --host 127.0.0.1 --port 8001
```

Linux/macOS将环境激活命令替换为 `source .venv/bin/activate`。应用端不需要Torch或GPU；首次安装会下载Python依赖。

| 页面 | 地址 | 用途 |
|---|---|---|
| 计算与仿真 | `http://127.0.0.1:8001/` | 输入、上传、计算、仿真与导出 |
| 智能分析 | `http://127.0.0.1:8001/chat` | 绑定数据后提问，需要模型服务 |
| API文档 | `http://127.0.0.1:8001/docs` | 交互式OpenAPI |
| 健康检查 | `http://127.0.0.1:8001/health` | 应用进程状态 |

启动后可在计算工作台手动录入工况或上传自己的数据。下载仓库代码不等于已获得学生权重；智能分析的模型部署见下一节。

### 2. 查看工具与输入要求

```powershell
python -m energy_agent tools --output outputs/tool_contracts.json
```

该命令导出工具定义与输入契约。实际工况通过工作台录入或上传，并声明温度、流量和功率单位；HTTP请求结构可在应用的`/docs`页面查看。

## 学生模型部署

### 1. 模型文件与身份

学生由 **Qwen3-8B基座＋focused1186单LoRA** 组成。基础权重约16 GB，适配器约175 MB；后者不能脱离基座独立运行。仓库保存代码及预期哈希，权重需另行准备。

```text
<模型备份根目录>/
├── Qwen3-8B/                              # 5个safetensors分片、索引与tokenizer
└── chiller_focused_task_sft_kit_v1/results/
    └── focused_task_.../adapter_focused_epoch1/
        ├── adapter_model.safetensors
        ├── adapter_config.json
        └── README.md
```

```powershell
python -m chiller_student.configure --model-root "<模型备份根目录>"
python -m chiller_student.service --validate-only
```

第一条生成本机路径配置和私有token，已有配置不会被覆盖；第二条全量校验文件，不加载GPU。模型路径也可以在GPU端直接用命令参数传入。

### 2. GPU服务器启动

复用已验证的Python3.11 / CUDA12.4环境；固定依赖见 `requirements-student.txt`。当前严格数学执行配置要求单张支持BF16的GPU，启动时至少60GiB空闲显存。这是已验证运行配置的预检门槛，不代表8B模型在其他精度下的理论最低需求。

将代码、已有模型路径和与本机相同的私有token准备好后运行：

```bash
cd <服务器上的PEC-ChillerAgent目录>
chmod 600 .student_credentials/student-service.token
bash scripts/run_student_service.sh \
  --model-dir <Qwen3-8B绝对路径> \
  --adapter-dir <adapter_focused_epoch1绝对路径> \
  --token-file .student_credentials/student-service.token \
  --port 18081
```

出现 `ADAPTER_EXACT: focused1186 504/504 FP32 identical` 和 `FOCUSED1186_READY` 后，服务在GPU服务器回环地址运行。启动脚本不停止其他进程、不下载模型，也不启动训练。

### 3. 本机连接与页面启动

在本机新开PowerShell，进入项目目录：

```powershell
.\scripts\start_student_tunnel.ps1 -Server <SSH主机> -SshPort <SSH端口>
```

默认将本机 `127.0.0.1:28081` 转发到服务器 `127.0.0.1:18081`。保留隧道窗口，在另一个终端检查并启动页面：

```powershell
python -m chiller_student.check_connection
.\scripts\start_student_app.ps1 -Python python -Port 8001
```

连接检查应显示 `connected: true`、`identity_verified: true` 和 `model: chiller-focused1186`。随后在工作台运行单条工况，转入智能分析，选择学生模式并提问，例如：

> 请给出本次工况的制冷量、输入功率和COP，并解释COP表示什么，以及这些结果有哪些判断边界。

GPU服务、SSH隧道和本机应用是三个进程。模型在同一台具备足够资源的机器运行时可省略SSH，启动应用时设 `-StudentUrl http://127.0.0.1:18081`，连接检查也使用 `--url http://127.0.0.1:18081`。

更多配置、故障处理和回滚步骤见[学生部署说明](docs/student_deployment.md)。

### 4. 配置变量

| 变量 | 默认/含义 |
|---|---|
| `ENERGY_AGENT_DATA_DIR` | 默认 `outputs/energy_agent`，保存SQLite与运行记录 |
| `ENERGY_AGENT_STUDENT_FOCUSED_ENABLED` | `1`，启用默认学生 |
| `ENERGY_AGENT_STUDENT_FOCUSED_URL` | `http://127.0.0.1:28081` |
| `ENERGY_AGENT_STUDENT_FOCUSED_TOKEN_FILE` | 本机私有token路径，内容不进入日志 |
| `ENERGY_AGENT_STUDENT_FOCUSED_TIMEOUT_S` | `60`，允许1–60秒 |
| `CHILLER_BASE_MODEL_DIR` / `CHILLER_ADAPTER_DIR` | 服务端模型路径，可被CLI参数覆盖 |
| `ENERGY_AGENT_LLM_BASE_URL` / `MODEL` / `API_KEY` | 可选外部Provider；完整变量名均以 `ENERGY_AGENT_LLM_` 开头 |

`.env.example`用于说明，不会自动加载。学生连接的环境变量优先于`.student.local.json`；连接状态用`python -m chiller_student.check_connection`核对。外部模型的密钥只用于用户显式选择的外部路径。

外部Agent提示词位于`energy_agent/prompts/system.md`。默认学生输入由`chiller_student/focused_contract.py`及`planned_task_contract_v2.py`构建，包含当前问题、本次Python事实和待答清单，使用Qwen非思考模板；更改这些协议后需要重新验证模型回答。

## 物理计算与数据约定

输入温度转换为K、质量流量为kg/s、功率为W；输出热功率为kW。对于有效输入：

$$Q_e=\dot m_e c_p(T_{e,in}-T_{e,out})/1000$$

$$Q_c=\dot m_c c_p(T_{c,out}-T_{c,in})/1000$$

$$COP=Q_e/P,\qquad R=Q_c-Q_e-P$$

上式的 $P$ 为kW，$c_p$ 为J/(kg·K)，COP无量纲。密度只用于体积流量转质量流量，比热用于热量计算；二者均记录生效值。

- 缺测、无效值和实测零值分开处理；有效正功率才可计算COP，实测零功率仍可用于残差。
- 每个指标独立判断可计算性，缺失冷却侧测量不自动作废冷冻侧制冷量。
- 出水温度设定值属于控制目标，不能替代实测出水温度。
- `R`为代数能量平衡偏差，单凭它不能确诊故障或量化能效损失。
- 指标值和有效点数是不同事实；多行指标均值不自动代表时段能耗或时段COP。
- 默认学生接受单行物理分析；ElectricEIR使用工作台或显式外部Agent路径。

源单位支持温度K/°C/°F、流量kg/s、m³/s、m³/h或US gpm、功率W/kW。同一请求内同类物理量共用单位。工作台默认比热4184 J/(kg·K)、密度995.586 kg/m³；研究用DataSchema默认4180、1000。比较计算结果时应核对实际生效物性。

ElectricEIR仿真需要两侧进水温度、正向流量、出水设定温度及匹配的性能参数，提供158组水冷记录，也支持自定义曲线。实测功率和出水温度用于比较，不驱动仿真状态；模拟COP与实测COP分开输出。自定义性能参数使用SI单位，曲线按摄氏温度拟合。

动态仿真按独立运行段初始化，默认两侧初温为5°C、25°C，时间常数各30秒；组内时间须严格递增。输入按零阶保持，首点输出初态，求解使用SciPy BDF。稳态仿真逐行求解，不使用热容和初态。性能曲线须适配目标机组；理想设定值控制、恒物性水和动态储热均应纳入结果解释。功率不含水泵与风机，模型不包含完整制冷剂循环或水力网络。

`/model/electric-eir/calibrate`只在有依据的健康稳态数据上拟合单个功率尺度。数值对齐使用`tests/reference/`内的Modelica参考模型和输出，可用`python tests/reference/compare_eir.py`复核；目标机组适用性仍需另行验证。

## API与代码调用

### 常用接口

| 方法与路径 | 用途 |
|---|---|
| `POST /workbench/run` | 工作台计算或仿真 |
| `POST /agent/v1/datasets` | 登记数据及源单位 |
| `POST /agent/v1/datasets/upload` | 上传CSV/Excel |
| `GET /agent/v1/datasets/{dataset_id}/records` | 分页查询原始记录 |
| `POST /agent/v1/tools/chiller_analyze/execute` | 按数据集执行physics/simulate/compare |
| `GET /agent/v1/runs/{run_id}/artifact` | 完整计算产物 |
| `GET /agent/v1/analysis/config` | 默认学生配置与预期身份 |
| `POST /agent/v1/analysis` | Python计算后调用学生解释 |
| `POST /agent/v1/chat` | 与默认学生分析相同的入口 |
| `POST /agent/v1/chat/external` | 用户显式选择的外部模型工具循环 |
| `GET /agent/v1/chat/sessions` | 会话历史 |
| `GET /agent/v1/chat/sessions/{session_id}/turns/{turn_id}/report` | 分析报告 |

GPU服务另提供受token认证的 `/health`、`/v1/models` 和 `/v1/chat/completions`。它只接受本项目冻结协议的Chat Completions子集，不能当成任意通用聊天API。

### Python工具调用

先通过工作台或数据集API登记自己的数据，再将下方占位符替换为对应的设备ID和数据集ID。

```python
from energy_agent.runtime import AgentRuntime

runtime = AgentRuntime()
result = runtime.analyze({
    'asset_id': '<asset_id>',
    'dataset_id': '<dataset_id>',
    'task': 'physics',
})
print(result.metrics['COP'].value)
print(runtime.repository.get_run(result.run_id))
```

### HTTP学生分析

应用与学生服务启动后，可以用 `httpx` 分析已登记的数据。将占位符替换为实际ID；可通过`GET /agent/v1/datasets`查询。

```python
import httpx

with httpx.Client(base_url='http://127.0.0.1:8001', timeout=70, trust_env=False) as client:
    response = client.post('/agent/v1/analysis', json={
        'message': '请分析本次制冷量、输入功率和COP，并说明判断边界。',
        'context': {'asset_id': '<asset_id>', 'dataset_id': '<dataset_id>'},
    })
    response.raise_for_status()
    reply = response.json()
    print(reply['report_mode'], reply['answer'])
```

`student_explanation`表示学生正文经有限检查后展示；`tool_facts`表示程序事实回退。HTTP成功不能单独证明模型回答成功。完整工具API见[energy_agent说明](energy_agent/README.md)。

## 学生训练

训练采用教师辅助参考答案、编辑审核和答案级监督微调。system/user上下文保持可见，提示位置标签为 `-100`，仅答案及原生结束标记参与监督。基座冻结，更新LoRA；不需要教师logits或KL损失，物理公式仍由Python执行。

| 项目 | focused1186配置 |
|---|---|
| 基座 | Qwen3-8B，revision `b968826d9c46dd6066d109eabc6255188de91218` |
| 适配器 | 单LoRA，r16、alpha32、dropout0.05 |
| 最终训练池 | 815条：748条自然语言解释＋67条结构化选择 |
| 最后一轮 | 从保留的targeted1058继续，1186次加权访问/更新，新优化器 |
| 优化 | AdamW，学习率5e-6，batch1、梯度累积1，seed42 |
| 精度 | BF16基座＋FP32 LoRA |
| 推理 | 非思考模板、显式greedy、最多2048新token |
| 适配器SHA-256 | `136eeeb15c1751b8a32628fc525ba680e783e3bf1cbbc546e54a64ab00eca8ab` |

`1186`指最终一轮更新数，不是全部历史训练成本。保留谱系还包含之前阶段，最终推理加载一个继承训练的适配器，不叠加多个历史LoRA。最终训练源码和固定计划见 [research/focused1186_sft](research/focused1186_sft/PUBLICATION.md)。

训练样本和参考答案不随代码发布。训练入口保留原有完整性检查，使用时需要在私有目录补齐对应材料，详见[训练源码与数据准备](docs/research_reproduction.md)。日常使用已训练模型无需重新训练。

## 验证与开发

```powershell
python -B -m pytest energy_agent/tests tests -q -p no:cacheprovider
node tests/test_chat_ui.cjs
node tests/test_chart_utils.cjs
```

目前软件测试覆盖真实Python计算、持久化、源单位、引用绑定、身份不匹配、超时回退、页面会话及图表。测试使用合成模型传输夹具，不调用付费API；GPU真实运行另由权重核验、服务日志和页面产物验证。已完成focused1186的一次真实页面链路核查，不将单次演示等同于完整系统准确率。

CI只运行软件测试；研究目录不自动触发训练或外部API采集。

## 常见问题

**只克隆代码能否运行？** 可以运行计算工作台和软件测试。学生分析还需要基础权重、focused1186适配器、GPU服务及本机凭据。

**原来的DeepSeek还会被调用吗？** 默认学生路径不调用。只有显式选择外部模式、配置模型并发送请求时才使用外部Provider；`/llm/test`也会产生一次实际请求。

**为什么出现工具事实报告？** 这表示模型连接、身份、格式或检查未通过，页面展示Python事实。查看该轮 `error_code` 和审计记录，不把此结果记成学生成功。

**修改工况后为什么要新建对话？** 会话绑定数据集和模式。新工况应登记新数据集、新建对话；每次回答产生新的计算运行，便于核查引用来源。

**为什么仓库中有多个协议版本？** 当前focused入口依赖其中部分版本，另有历史会话兼容逻辑；这些文件不是多个同时部署的学生模型，不能只按版本号删除。

**能直接在4GB显存电脑上运行模型吗？** 当前冻结BF16/FP32配置不能直接这样运行。本机可承担页面和Python计算，GPU服务器承担推理；量化部署属于另一个需单独验证的配置。

## 发布内容与许可

本仓库发布应用代码、推理代码、最终SFT源码快照、软件回归检查和配套文档。图稿、独立示例数据、模型权重、真实测量原表、训练集、测试题库、参考答案、模型比较结果、API密钥、SQLite数据库及私人论文工作目录不包含在当前发布中。

Buildings相关来源和许可保留在[BUILDINGS_LICENSE.txt](chiller_app/model/BUILDINGS_LICENSE.txt)。基础模型、第三方数据与其他依赖遵循各自许可；仓库目前未添加项目整体LICENSE，公开可读不自动代表对所有材料授予再分发许可。完整数据和权重的公开地址另行确定。
