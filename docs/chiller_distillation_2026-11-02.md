# 冷水机组学生模型：从数据到项目接入

日期：2026-11-02。本文基于当前项目源码、用户提供的服务器信息及下方官方资料制定。所有样本数、超参数和验收门槛均是起步方案，不是已经取得的实验结果。

当前完成的是方案、配置模板和开发题库；尚未连接服务器、付费调用教师、训练学生或改动应用的模型路由。

## 1. 适合本项目的结论

推荐第一版采用：**DeepSeek API 教师 + Qwen3-8B 学生 + BF16 LoRA SFT + 现有 Python 分析工具 + 后续文档检索**。

先让学生承担冷水机组知识问答。涉及当前数据集的分析，第一版继续由 DeepSeek 组织工具调用；学生通过工具评测后，再逐步承担这部分。冷量、COP、误差、ElectricEIR 仿真继续由项目工具计算。

Qwen3-8B 是结合现有驱动和成熟工具协议选择的工程起点，不是断言它是当前最强小模型。Qwen3.5-9B 可作为下一组候选，但需要另外验证训练框架、混合架构、推理环境和工具解析，不能只替换这里的模型名。

用户写的“stf”通常指 **SFT（监督微调）**。本项目的“从零开始”是从零建立数据、训练、评测和部署流程，在已有开源模型上适配，不是从随机权重预训练语言模型。

| 方法 | 在这里解决什么问题 | 当前优先级 |
|---|---|---|
| 文档检索 / RAG | 让回答有说明书、版本和页码依据；更新知识无需重新训练 | 补充资料后尽早加入 |
| 教师输出蒸馏 + SFT | 学习领域表达、证据边界、追问、工具选择和报告格式 | 第一轮训练主体 |
| LoRA / QLoRA | 减少训练显存与可训练参数；它们不是另一种知识来源 | H100 上先 LoRA，显存不足再考虑 QLoRA |
| DPO | 用审核过的好/坏回答对修正偏好 | SFT 后按失败案例决定 |
| GRPO 等在线 RL | 通过可执行验证器改进工具行为等能力 | 暂不作为第一版前置条件 |

通过 API 取得教师回答、筛选后训练学生，属于输出级 / 序列级蒸馏。学生和教师不必同一模型家族，也不要求教师一起装在训练服务器上。不应把它称为已完成 token logits 的 KL 蒸馏：普通聊天 API 并不提供完整教师分布，教师与学生 tokenizer 也可能不同。

## 2. 先理解项目已经具备什么

已核查的源码：

- `energy_agent/providers/compatible.py`：OpenAI 兼容的 `/chat/completions` 客户端。
- `energy_agent/agents/chat.py`：聊天工具循环；最多四次模型请求和四次工具调用。
- `energy_agent/prompts/system.md`：问答、缺测、仿真前提与事实引用规则。
- `energy_agent/agents/reporting.py`：`{{fact:F编号}}` 校验、数值替换和报告回退。
- `energy_agent/config/llm.py`、`energy_agent/api/chat.py`：目前是一套模型配置和一个 Provider，没有双模型自动分流。
- `chiller_app/api/workbench.py`、`chiller_app/model/electric_eir.py`：水侧计算和 ElectricEIR。
- `energy_agent/README.md`、`docs/agent_stage2.md`：当前真实接入能力及边界。

当前聊天模型能调用的工具只有：

```json
{"name":"inspect_dataset","arguments":{}}
{"name":"chiller_analyze","arguments":{"task":"physics"}}
{"name":"chiller_analyze","arguments":{"task":"simulate"}}
{"name":"chiller_analyze","arguments":{"task":"compare"}}
```

注意：这段是便于阅读的调用内容。线上仍使用标准 `tool_calls` 协议；数据集、设备、机组参数和设定值由服务器绑定，不能让模型添加 `dataset_id`、猜机组或随意修改参数。

`/model/train` 等研究入口训练的是现有性能研究模型，不是本方案中的大语言模型。自动校准、优化、任意 pandas 分析和设备控制目前都没有注册为聊天工具。即使换成更大的语言模型，也不会自动得到这些能力。

## 3. 数据分析究竟由谁做

| 用户任务 | 语言模型的职责 | 计算或知识依据 | 第一版选择 |
|---|---|---|---|
| “COP 是什么？” | 解释概念、边界和计量范围 | 审核过的知识资料 | 学生 |
| “某型号报警代码是什么意思？” | 根据具体型号、控制器和手册版本回答 | 对应手册检索；无资料先追问 | 学生 + 文档检索 |
| “计算上传数据的冷量和 COP” | 选择任务、解释缺测与结果 | `chiller_analyze(physics)` | DeepSeek 编排工具，后续评测学生 |
| “模拟这个机组” | 检查显式配置、组织仿真 | `chiller_analyze(simulate)` | 同上 |
| “比较实测功率和仿真功率” | 解释配对数、误差和模型有效域 | `chiller_analyze(compare)` | 同上 |
| “按月份积分能耗并找峰值” | 理解分析目的 | 需要新增时间聚合工具 | 先补工具，再比较模型 |
| “判断是否结垢/缺冷媒” | 给出候选原因、证据不足和补测建议 | 经过验证的诊断证据 | 不能仅靠语言模型确诊 |
| “做实时节能控制” | 本方案不提供控制策略上线 | 需要独立控制建模、验证与边界 | 不与本轮 LLM 微调混在一起 |

运行架构建议：

```text
用户问题 + 会话绑定 + 最近任务
              |
          服务端任务分流
          /            \
知识问答                 数据分析 / 仿真 / 比较
学生 + 检索              DeepSeek（后续可换合格学生）
          \            /
         现有工具、事实校验和报告
```

分流不能只看有没有“冷水机组”关键词：几乎所有分析也包含这个词。判断应结合问题意图、绑定数据、历史任务和工具需求；有歧义时走具备工具能力的分析路线或追问。是否已绑定数据不是唯一判断条件，但它影响事实引用规则。

若将来通过评测发现同一个学生可以稳定编排这些简单工具，可以让学生同时处理问答和常规分析，保留复杂问题的教师回退，减少两套模型的运维成本。

## 4. 服务器判断和目录

已确认：Ubuntu 22.04、H100 PCIe 81559 MiB、MIG 关闭、GPU 当前空闲、驱动 550.90.12。CPU 约 26 线程、内存约 224 GiB；`/` 总量 50GB 且已用约 27GB。

H100 80GB 适合先做 8B 的 BF16 LoRA。8B 的 BF16 权重约 16GB（十进制），训练还需要激活、梯度和适配器优化器状态；实际峰值取决于长度、批量和实现，必须实测。不要把权重大小当作总训练显存。

完整 DeepSeek-R1 有 671B 总参数；即使每次只激活部分专家，也需要存储大量总权重。单卡 H100 不适合直接承担其完整本地教师服务。采用 DeepSeek API 可以把本地 GPU 留给学生。[DeepSeek-R1 模型说明](https://huggingface.co/deepseek-ai/DeepSeek-R1)

持久化目录建议：

```text
/root/epfs/chiller-distill/
  envs/                 训练和推理分开
  cache/                HF、pip 和临时缓存
  models/               原始学生模型
  sources/              原始资料、版本、哈希和授权记录
  data/raw/             教师原始响应
  data/processed/       train.jsonl、val.jsonl、dataset_info.json
  eval/dev/             可反复调试的开发题
  eval/locked/          封存的最终测试题；训练进程不读取
  runs/                 每次训练单独目录、checkpoint 和日志
  releases/             已验收模型和 tokenizer
  manifests/            环境、模型、数据和评测版本
```

运行前检查 `/root/epfs` 的容量、配额和 I/O；不要假定它无限。单一 8B 方案可先以约 100–200GB 作为规划空间，再按实际权重、依赖和 checkpoint 大小调整。只读 `/root/public` 中若已有正确模型，可以直接读取，避免重复下载。环境存在 epfs 也不意味着容器释放后无需重建系统配置，因此仍需保存安装记录。

```bash
nvidia-smi
df -h / /root/epfs
python --version
mkdir -p /root/epfs/chiller-distill/{envs,cache,configs,models,sources,data/raw,data/processed,eval/dev,eval/locked,runs,releases,manifests}
export HF_HOME=/root/epfs/chiller-distill/cache/huggingface
export PIP_CACHE_DIR=/root/epfs/chiller-distill/cache/pip
export TMPDIR=/root/epfs/chiller-distill/cache/tmp
mkdir -p "$TMPDIR"
```

`nvidia-smi` 的 CUDA 12.4 是驱动报告的支持信息，登录页的 cuda-12.3 可能是 Toolkit 版本；它们不能直接等同于 Python 包使用的 CUDA runtime。当前先采用 CUDA 12.4 对应的 PyTorch 与旧版兼容推理栈，别直接安装最新版 vLLM 到训练环境里。

## 5. 教师与学生模型

教师优先使用用户选定的 DeepSeek API。2026-11-02 核对的官方文档列出了 `deepseek-flash` 和 `deepseek-v4-pro`；Flash 已映射到更新版本。**不要假定 `deepseek-reasoner` 仍表示历史 R1，也不要用别名代替可复现的模型版本记录。**实际调用前以账户 `/models` 和文档为准。[官方模型说明](https://api-docs.deepseek.com/quick_start/pricing/)

建议先用 Flash 处理有明确参考材料的普通样本，对困难案例再与 Pro 比较；用同一批人工审核题决定是否值得增加教师成本。若研究目标必须是历史 R1 蒸馏，应另找明确提供 R1 版本的服务并记录提供方，不把当前 API 模型称为 R1。

学生的备选关系：

| 模型 | 在本轮中的定位 | 选择依据 |
|---|---|---|
| `Qwen/Qwen3-8B` | 第一套工程基线和训练配置 | 8B、支持开关思考、可用工具调用，适合当前兼容栈 |
| `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B` | 对比候选 | 已有推理蒸馏，仍须验证短回答、工具协议、输出预算与延迟 |
| `Qwen/Qwen3.5-9B` | 后续升级候选 | 官方提供 9B 模型，含视觉和混合架构；需单独适配较新软件栈 |

这些模型存在不意味着其中任意一个已经具备冷水机组专业能力。先拿开发题对比，再决定要训练谁。面向短问答和工具编排，已有长推理蒸馏模型未必天然优于通用指令模型；这是本项目需要验证的假设。[Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B)、[R1-0528-Qwen3-8B](https://huggingface.co/deepseek-ai/DeepSeek-R1-0528-Qwen3-8B)、[Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)

## 6. 只有 RP-1043 Excel，应该补什么资料

当前可以先把目标定为“RP-1043 与本项目工具助手”。要称为覆盖型号报警、维护和故障排查的冷水机组专家，必须补充相应资料。教师凭记忆编出的维修知识不能直接作为真值。

| 资料 | 去哪里取得 | 如何使用 |
|---|---|---|
| 当前项目说明、方程、工具契约和单元测试 | 本项目 README、docs、energy_agent、chiller_app、tests | 训练项目边界、工具选择、缺测处理和证据格式 |
| ElectricEIR 的原理与适用域 | LBNL 的 Buildings 13.0.0 官方文档 | 与当前代码版本对照；不要混入其他版本的新增能力 |
| EIR 曲线、能耗和机组模型说明 | EnergyPlus 官方 Engineering Reference | 学习模型假设、变量与功率范围，保留版本 |
| 冷站设计、能效影响因素 | Trane 官方技术资料 / Engineers Newsletter | 构建有出处的概念与系统问答 |
| 型号安装、运行和维护手册 | Carrier、Trane、Daikin、YORK 等厂商官网；优先你实际使用的机型 | 记录具体型号、控制器、版本；不能泛化报警代码 |
| RP-1043 字段、试验定义、故障严重度 | 你持有数据随附的 readme 和原报告；通过学校或 ASHRAE 正规渠道获取缺失部分 | 确定实验真值与分组，不能只凭文件名猜定义 |
| 真实运维知识 | 后续取得的脱敏工单、检修结论、专家问答 | 补充目标设备与现场分布；当前并不存在此类验证 |

可以从这些已核实的入口开始：

- [Buildings 13.0.0 Chillers](https://simulationresearch.lbl.gov/modelica/releases/v13.0.0/help/Buildings_Fluid_Chillers.html)
- [EnergyPlus 24.1 Engineering Reference](https://energyplus.net/assets/nrel_custom/pdfs/pdfs_v24.1.0/EngineeringReference.pdf)
- [Trane：What drives Chiller Efficiency](https://commercial.trane.com/content/dam/Trane/Commercial/global/products-systems/education-training/engineers-newsletters/waterside-design/ADM-APN069-EN.pdf)
- [Carrier：19XR / 19XRV 安装运行手册](https://brandportal.carrier.com/m/4501b362486920a6/original/11989_IOM_03_2017_19XR_19XRV.pdf)

后两项只是可取得的真实资料示例，不说明它们就是 RP-1043 或你未来现场机组的手册。下载前核对使用许可；公开可读不自动代表允许再分发全文、训练或上传外部 API。先从允许使用的项目资料与开源模型文档做试点，厂商资料可先作为人工阅读及经许可的检索来源。

起步可以先准备少量完整、覆盖核心问题的资料，例如十余份允许使用的文档；数量不是验收条件。优先可追溯、与实际任务相关的资料，少收重复营销材料。

每个知识片段保存：`source_id / title / URL或本地来源 / version / equipment_model / section / page / text / sha256 / usage_permission`。扫描件 OCR 后检查表格、上下标、负号、温度和单位。教师输出的来源必须真实存在且支持该结论。

文档检索建议：按语义段落切分，保留标题与表格上下文；先以约 400–800 中文字、少量重叠作为试点参数，再用检索命中率调整。型号、控制器、年份先过滤，再混合检索和重排。训练“根据证据回答、证据不足追问”的行为，不把所有手册细节强行记进权重。

## 7. 把 RP-1043 变成训练样本

不要把 Excel 的每行直接当一条问答。应先建立规范数据层和可重复的场景，再执行现有工具取得答案依据。

处理顺序：

1. 建立原始文件清单、sheet 名、文件哈希和原始行号；保留未改动源文件。
2. 核实每列含义、单位、状态码、故障实验定义及数据权限。
3. 按原始试验文件 / 完整 run 分配 train、val 和 locked test，然后才抽窗口和扩写问题。Complete、Reduced、Steady 中重复观测及由同一试验生成的改写必须同组。
4. 训练和最终测试之间不得共享同一批相邻工况、同一窗口的改写，或同一源段落衍生的题。
5. 统一映射 °F、US gpm、功率单位；不要把不明压力口径当绝对压力使用。
6. 按稳态、动态、启停、缺测、曲线越界等定义场景。先审核健康稳态样例，再扩展。
7. 通过真实项目工具运行 `physics / simulate / compare`，保存输入、有效 schema、参数、工具版本、warnings 和输出。
8. 教师读取问题、允许使用的说明及工具结果，生成解释；数值来自工具，不能由教师重新猜。

RP-1043 的故障标签可用于有原始说明依据的实验评测，但不能让回答读取隐藏标签。文件名、目录名和 `Active Fault` 等潜在标签泄漏也要清理。不能把实验注入标签等同于语言模型从稀疏水侧数据完成了现场确诊。

本项目尤其要覆盖：

- 缺流量不能计算实测冷量；缺正实测功率不能得到实测 COP。
- 只有两侧水温和功率，不能仅凭能量守恒唯一确定两侧未知流量。
- 工作台默认 cp=4184、密度=995.586；研究 DataSchema 默认 cp=4180、密度=1000。以实际生效 schema 为准，不能混用。
- 均值 COP 不等于时段积分冷量除以积分电量；现有工具指标是有效输出点均值。
- 动态储热、模型越界或残差不能单独等同于故障确诊。
- 默认机组性能记录不是 RP-1043 实验机组的已知真值。
- ElectricEIR 的功率不包含全冷站水泵、冷却塔风机等全部用电。

## 8. 教师造数与审核

先做约 200 条候选样本，逐条审核，跑通数据格式和训练闭环；不要第一步生成几万条。第二轮可扩至约 2,000 条合格训练对话，再按失败类型扩充到约 5,000–10,000 条。若来源和场景不足，减少数量，不靠同义改写凑规模。

首轮配比可暂用：知识与资料问答约 30%，缺测/不确定性/追问约 20%，真实工具轨迹和事实报告约 40%，纠错、多轮与指令干扰约 10%。如果第一版只上线知识路线，也要保留一定工具行为，避免后续合并时完全重学。

教师提示词模板：

```text
你负责为冷水机组助手生成可审核的训练样本。
只使用下方提供的参考资料及真实工具结果。
不补造型号、报警定义、测量值、故障概率或结论。
资料不足时应指出不足并提出必要问题。
涉及当前数据集的数字只使用给定事实表中的 {{fact:F编号}}。
当前工具仅有 inspect_dataset 和 chiller_analyze；后者 task 仅可为 physics/simulate/compare。
输出：用户问题、应采取的动作、简明答案、支持答案的 source_id/页码或事实ID、审核要点。
给出可核验的简短理由；不要要求冗长的内部思考过程。

任务：{任务}
会话绑定：{绑定}
参考资料：{片段}
真实工具定义和结果：{工具及结果}
```

复杂样本可以生成两个候选，但是否保留必须由检查器和人工确认，不能因为教师自评高分就直接通过。

审核至少检查：来源能否定位并支持结论；工具名和参数是否合规；缺测是否被承认；实测/模型归属是否正确；占位符是否存在；是否错误确诊；有没有把标签、答案或隐藏传感器放进输入；轨迹是否完整且未截断。

**工具结果应由程序真实执行产生。**教师可以提出动作，但不能把自己编的 tool observation 当作真实结果。采集工具轨迹时保留 `assistant tool_calls → tool response → assistant answer`，并包含失败、needs_input 和修复样本。训练损失主要覆盖 assistant 和 function_call，不学习让模型冒充工具生成观测。

默认保存教师最终短答案和可核验的推导摘要，不将全部长篇 `reasoning_content` 拼进目标。若以后研究推理蒸馏，再单独控制推理预算、质量及与上线模板的一致性。

费用先采样估计：

```text
教师费用 ≈ 输入tokens / 1e6 × 输入单价
         + 输出tokens / 1e6 × 输出单价
         + 多候选、审核调用与失败重试
```

若服务计费含 reasoning tokens，也要纳入输出。记录每条请求的模型版本、提示词版本、usage 和费用；设置任务总预算、并发上限和重试上限。实际价格查执行当天官方文档，本文不承诺固定费用。

## 9. 数据格式和提供的模板

`examples/distillation/format_examples.json` 只用于说明 ShareGPT 格式，不能当成完成的数据集；其中物理工具样例的观测由当前项目真实计算生成，知识回答和解释由本次编写，未调用教师。

LLaMA-Factory 注册配置见同目录 `dataset_info.json`。它预期你实际准备好 `train.jsonl` 与 `val.jsonl`，这两个文件尚未生成；验证集必须预先按来源分组划出，不能用随机行切分代替。[LLaMA-Factory 数据协议](https://github.com/hiyouga/LlamaFactory/blob/main/data/README.md)

一个工具样本的逻辑结构为：

```text
system：项目规则 + 当前绑定 + 事实表
human：计算当前数据的实测制冷量和 COP
function_call：{"name":"chiller_analyze","arguments":{"task":"physics"}}
observation：真实工具返回的状态、缺测、警告及 facts
gpt：计算结果：{{fact:F编号}}。按事实解释，说明边界。
```

完整训练轨迹应复用真实线上工具 schema 和系统提示。不要只训练普通 QA，然后期待模型自动满足函数调用和事实引用格式。将来源、分组、生成器版本等审核信息保存在旁侧 manifest，不需要全部塞入模型输入。

## 10. 当前驱动下的训练环境

为了兼容驱动 550.90.12，先给出一条保守、固定旧版本的 Qwen3-8B 试点路径。它不是面向公网的生产基础镜像推荐；后续升级驱动与软件栈后，应重新做协议与模型回归。本文没有在你的服务器执行安装，实际依赖解析和 GPU 冒烟检查必须通过后才训练。

使用服务器已有的 Python 3.11；如没有，先通过平台支持的镜像或环境管理方式提供，不要修改系统 Python。训练环境与项目 Web 环境分开。

```bash
python3.11 -m venv /root/epfs/chiller-distill/envs/train
source /root/epfs/chiller-distill/envs/train/bin/activate
python -m pip install --upgrade pip
python -m pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
python -m pip install 'transformers==4.51.3' 'datasets==3.6.0' 'accelerate==1.7.0' 'peft==0.15.2' 'trl==0.9.6' 'numpy==1.26.4'
python -m pip install 'git+https://github.com/hiyouga/LLaMA-Factory.git@v0.9.3'
python -m pip check
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available()); print(torch.cuda.get_device_name(0)); print(torch.cuda.is_bf16_supported())"
python -m pip freeze > /root/epfs/chiller-distill/manifests/train-environment.txt
```

此处 v0.9.3 源码支持 `template: qwen3` 和 `enable_thinking: false`；不要把较新版本示例中的 `qwen3_nothink` 直接移植进这个旧版环境。若换成当前新版框架，应连同模板、依赖和服务端一起重新验证。[v0.9.3 模板源码](https://github.com/hiyouga/LLaMA-Factory/blob/v0.9.3/src/llamafactory/data/template.py)、[v0.9.3 依赖约束](https://github.com/hiyouga/LLaMA-Factory/blob/v0.9.3/requirements.txt)

PyTorch 官方提供 2.6.0 的 cu124 安装方式。[PyTorch 版本安装说明](https://docs.pytorch.org/get-started/previous-versions/)

模型下载可使用官方 Hugging Face 或 ModelScope 客户端，也可读取 `/root/public` 的已备模型。无论来源如何，都记录准确模型 revision，且只保留一份原始权重。这里配置预期本地路径为 `/root/epfs/chiller-distill/models/Qwen3-8B`，需要先放好对应权重、配置和 tokenizer。

数据准备好后，把本项目模板复制到服务器的对应目录，执行：

```bash
llamafactory-cli train /root/epfs/chiller-distill/configs/qwen3_8b_lora_sft.yaml
```

需要自行把 `examples/distillation/` 中配置放入服务器的 `configs/`，并把 `dataset_info.json` 放入 `data/processed/`。不要在配置文件中写 API Key。

训练起步参数见模板：BF16 LoRA、rank 16 / alpha 32、长度 4096、单卡 batch 1、梯度累计 8、学习率 1e-4、两轮、梯度检查点、SDPA。目标是先简化安装与排错；FlashAttention、长上下文、QLoRA 和其他优化在基线成功后再加。

上线默认关闭思考，因此训练与推理都保持 `enable_thinking=false`。这是一版产品策略；如果后续要开放推理，另做模板和评测。

训练顺序：

1. 检查渲染后的输入、工具 JSON、EOS、角色边界和 loss mask。只让 assistant/function_call 目标参与监督，用户、系统和 observation 作为上下文。
2. 用少量训练样本验证能过拟合，并确认工具消息、事实占位符和完整答案均未被截断。
3. 用约 200 条审核样本跑试点；为了看更新后的行为，先跑少量步数并抽题生成，不以 loss 下降代表成功。
4. 以约 2,000 条合格样本做正式第一轮；每轮保留独立 checkpoint，以开发题和 val 判断，最终测试不用于选 checkpoint。
5. 学生若更会背术语却更会编数值，优先修正数据与监督，再考虑更大模型。

4096 是训练上限，不代表任意工具轨迹都能直接放入。先统计 token 分布；长轨迹应在完整回合边界缩短历史或拆分，不能截掉 tool observation 或最终答案。若准备在 8192 上下文上线，需要专门测长历史，必要时增加对应训练样本。

不要预先承诺几小时完成。以真实试跑的 tokens/s、峰值显存和样本长度估算总时长；保存 GPU 峰值、有效 tokens、batch 和训练步数。H100 的主要价值是支持快速迭代，资料审核往往比一次 LoRA 训练更耗时。

## 11. 如何评测学生

同目录 `eval_dev_seed.jsonl` 提供 30 道公开的开发种子题，带 setup、期望行为、关键错误及部分数值答案。它不是封存测试集，也不是已经实现的自动评测器；可以用于调试，但不能拿反复看过的题证明最终泛化。

建议随后由独立于训练数据生成过程的人工审核建立 300 道最终题，训练开始前冻结来源与分组：

| 类别 | 建议题数 | 主要检查 |
|---|---:|---|
| 概念、机组与项目边界 | 60 | 知识正确、来源和型号适用性 |
| 故障候选与证据不足 | 60 | 不乱确诊、必要补测、假设清晰 |
| 计算与单位 | 50 | 单位、有效物性、缺测和数值一致性 |
| 工具调用与多轮任务 | 80 | 正确工具、参数、会话绑定、占位符、端到端结果 |
| 错误恢复与干扰 | 30 | needs_input、failed、提示注入、模型超时 |
| 新工况 / 新文件 / 长历史 | 20 | 来源隔离、上下文和分布变化 |

至少比较：原始学生；原始学生+检索；SFT学生+同样检索；DeepSeek+同样检索和工具。检索前后对比用于区分知识检索与训练各自带来的增益。计算题和工具题给予相同工具、事实和调用预算，不能让教师看到隐藏标签或更多资料后宣称公平比较。

分两层报告：

- 模型层：原始回答是否选对工具、能否正确引用、是否自发编数值，发生了多少次格式修复。
- 系统层：最终显示给用户的答案是否正确、是否降级为事实报告、是否超时、耗时与成本。

如果服务器回退机制救回了错误答案，应记录为系统保护生效，不能统计为学生已学会。必须记录 `report_mode`、`model_calls`、`tool_calls`、`notices`、原始协议响应和最终状态；采集时隐藏密钥并脱敏。

推荐的起步上线门槛（需要结合基线再讨论，不是行业统一标准）：

- 可自动评分的工具选择与参数合规率至少 95%，同时分报 physics/simulate/compare/追问子类。
- 固定计算集的工具数值在规定容差内全部一致；单独记录模型是否正确引用这些数值。
- 封存关键题中，不出现伪造实测值、伪造事实ID、实测/模拟混淆和无证据的确定故障结论。
- 领域问答按正确性、依据、边界、可操作性由人工评分；学生不能只赢在篇幅。
- 简单问答和常规分析分别统计端到端 P50/P95、超时率、单请求 token 和单位成本；先测当前 DeepSeek 的基线，再定服务目标。
- 报告分组通过率和样本数；关键题“零观察错误”不代表真实错误概率为零。

可复算示例：cp=4180 J/(kg·K)、rho=1000 kg/m³，冷冻水 10→5°C、72 m³/h，冷却水 30→35°C、90 m³/h，功率 100kW。预期 Qe=418kW，Qc=522.5kW，COP=4.18，Qc−Qe−P=4.5kW。若使用工作台默认物性，答案不同且应该不同。

在 standalone 计算测试中可以要求模型写数字；在实际绑定数据的 Agent 测试中，数字必须来自事实占位符，不能用同一种输出规范给两类题评分。

## 12. SFT 后是否上 RL

第一版先不做 GRPO/PPO。专业资料不足、工具协议没学会和评测题泄漏，都不能通过 RL 自动解决。

如果 SFT 后存在稳定的回答偏好问题，可以建立数百到上千条人工审核的 preference pairs，例如：

- 好：说明缺流量，追问测量；坏：默认一个流量算出 COP。
- 好：准确引用实际 fact；坏：把模型功率解释为实测功率。
- 好：给候选原因并标注证据不足；坏：仅凭 COP 下降确诊结垢。

DPO 是离线偏好优化，不需要在线环境交互，不要把“跑了 DPO”描述成已完成线上 RL。

只有在 SFT 稳定、独立验证器可执行后，才考虑小规模 LoRA GRPO 工具实验。奖励应检查任务是否完成、工具 schema、事实存在性、引用归属和证据边界，并对这些正确性条件设前置门槛。避免仅奖励格式、答案长或教师给高分，否则模型可能总是拒答、循环工具，或者输出合规占位符却给出错误解释。

单卡 80GB 可以探索受限的小模型 RL，但 rollout、actor、reference 和长轨迹都会占资源，需要重新核算；不要承诺本轮 SFT 参数原样就能跑 RL。这里的语言模型 RL 与实际冷站节能控制 RL 是两个独立任务，后者需要单独的环境、目标、约束与验证。

## 13. 导出、服务与当前项目接入

先挑选通过开发验证的 checkpoint，将 `qwen3_8b_export.yaml` 中 `adapter_name_or_path` 指向它。不要盲用最后一步，更不要先量化再判断训练效果。

```bash
llamafactory-cli export /root/epfs/chiller-distill/configs/qwen3_8b_export.yaml
```

导出合并需使用原始未量化基座，保留 tokenizer、special tokens、chat template 和 generation config。部署前比较 adapter 形式与合并权重在固定题上的输出和工具协议，再决定是否量化。量化后要重新验收，不能沿用 BF16 的结果。

推理单独建环境。当前驱动可先验证 vLLM 0.8.5 的 CUDA 12.4 路线；它只用于这里的 Qwen3-8B 基线，不适用于本文另列的新架构候选。该版本官方文档说明了 cu124 二进制和独立环境的要求。[vLLM 0.8.5 安装说明](https://docs.vllm.ai/en/v0.8.5/getting_started/installation/gpu.html)

```bash
python3.11 -m venv /root/epfs/chiller-distill/envs/serve
source /root/epfs/chiller-distill/envs/serve/bin/activate
python -m pip install --upgrade pip
python -m pip install 'vllm==0.8.5'
python -m pip check
python -m pip freeze > /root/epfs/chiller-distill/manifests/serve-environment.txt
```

先用**原始学生**验证一轮普通回答和完整工具来回，再用相同命令部署合并学生。如果解析器、模板或驱动检查失败，在排清环境问题前不要开始大规模训练。

```bash
vllm serve /root/epfs/chiller-distill/releases/chiller-qwen3-8b-sft-v1 \
  --served-model-name chiller-student-v1 \
  --host 127.0.0.1 --port 8008 \
  --dtype bfloat16 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.80 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --api-key "$CHILLER_SERVE_API_KEY"
```

启动前通过你的环境管理方式设置 `CHILLER_SERVE_API_KEY`，不要把真实密钥提交到项目。初期把 vLLM 绑定到 loopback，通过平台端口转发或 SSH 隧道访问；训练期间先停止同卡推理，避免显存互相占用。

项目网页目前可能仍运行在 Windows。本项目的 Base URL 校验只允许本地 HTTP、远程 HTTPS，所以不能直接把 `http://10.233.90.62:8008/v1` 填进去；该地址还是容器内网地址，也不代表 Windows 可达。

两种接入方式：

- 项目与 vLLM 同服务器：Base URL 填 `http://127.0.0.1:8008/v1`。
- 项目在本机：使用平台提供的转发，或通过实际可登录的 SSH 入口建立 `ssh -N -L 8008:127.0.0.1:8008 <用户>@<实际SSH入口>`；再在本机填相同 loopback URL。需要公网服务时用有鉴权的 HTTPS 网关。

页面配置为：模型名 `chiller-student-v1`；API Key 为实际服务密钥；高级 JSON 起步为：

```json
{"chat_template_kwargs":{"enable_thinking":false}}
```

额外采样参数应按实际模型与验证结果设置。当前客户端默认非流式、max_tokens=2048、timeout=45秒；这些都要在真实工具题上验证。连接测试仅请求一句简短回答，**不等于 function calling 验收**。

先在测试环境完成：模型列表/普通问答 → 真实 `tool_calls` → 工具执行 → 回传 `role=tool` → fact 引用 → 最终报告。若服务只把函数 JSON 当普通文本输出，现有客户端不会把它当工具调用。

vLLM 的自动工具选择需要正确的 parser 和模板，相关开关不能遗漏。[vLLM 工具协议说明](https://docs.vllm.ai/en/v0.8.5/features/tool_calling.html)

## 14. 如何实现“问答学生、分析 DeepSeek”

这是后续应用改造项，当前只保存了一套 `LLMSettings`。仅把页面换成学生地址，会让所有聊天请求都使用学生，不会自动保留分析走 DeepSeek。

可选实现：

1. 在应用内部增加 knowledge / analysis 两套模型配置和任务路由；沿用现有 CompatibleProvider、ChatService 和事实校验。这是本项目推荐方式，路由选择和报告记录较清晰。
2. 用统一兼容网关暴露一个地址，在网关内部路由；网关同样必须拿到足够会话上下文、处理密钥和记录模型来源。

改动位置与职责：

| 文件位置 | 后续要做的事 |
|---|---|
| `energy_agent/config/llm.py` 与配置契约 | 保存两套 profile；环境变量覆盖规则明确 |
| `energy_agent/api/chat.py` | 根据当前请求、历史和绑定选择 Provider，再进入现有 ChatService |
| `energy_agent/agents/chat.py` | 同一轮工具循环保持模型一致；显式记录选择原因和回退 |
| 会话与报告存储 | 记录实际模型、版本、路线、耗时、回退原因和学生原始失败 |
| 聊天配置 UI 与回归测试 | 区分两条路线，分别验收普通问题与工具闭环 |

若跨轮换模型，需转换厂商私有 reasoning 字段，保留标准工具配对，不能简单把某厂商全部 wire history 原封不动发给另一个。模型返回格式错误、超时或事实校验失败时可以回退教师，但不能无限重试，也不能把教师成功记为学生成功。

初期上线顺序：知识路线先影子评测 → 小范围启用学生 → 常规 physics 工具灰度 → simulate/compare 通过后再启用。每次发布保留上一版地址、模型 revision、数据哈希、适配器、模板及评测结果，支持一键切回已验收版本。

## 15. 实际执行顺序和停止条件

| 阶段 | 具体产物 | 通过后再进入下一步 |
|---|---|---|
| M0 环境 | 持久目录、GPU检查、固定依赖、原始学生推理服务 | 普通回答与真实工具来回可用 |
| M1 资料 | 允许使用的来源清单、RP-1043 字段和试验分组 | 每个关键知识/标签有依据 |
| M2 评测 | 开发题、人工评分规则、封存测试与原始学生/教师基线 | 不依赖训练题自评 |
| M3 数据试点 | 约200条审核样本、真实工具轨迹和格式检查 | 无编造观测、无错误标签泄漏 |
| M4 第一轮SFT | 约2000条合格训练对话、分组val、LoRA、训练日志 | 开发题能力改善且关键错误不回退 |
| M5 正式评测 | 固定输入下的模型与系统两层结果、延迟成本 | 达到预设门槛；不足则修数据/范围 |
| M6 部署 | 合并模型、兼容服务、双路由、回滚记录 | 端到端真实工具验收和灰度通过 |
| M7 可选优化 | 失败样本回收、DPO或受限RL对照 | 增益超过额外复杂度，最终测试重新封存 |

当前最值得先做的三件事：**整理 RP-1043 的字段和分组；补充允许使用的领域资料；让未微调的 Qwen3-8B 在当前服务器跑通本项目工具协议。**随后才为教师造数和训练付出规模化成本。

## 配套文件

- `examples/distillation/qwen3_8b_lora_sft.yaml`：当前驱动兼容方案的起始训练模板。
- `examples/distillation/qwen3_8b_export.yaml`：未量化基座合并模板。
- `examples/distillation/dataset_info.json`：训练/验证数据注册。
- `examples/distillation/format_examples.json`：三个格式样例，其中工具观测由项目真实生成。
- `examples/distillation/eval_dev_seed.jsonl`：30道可见开发题、期望行为与关键失败项。
- `examples/distillation/README.md`：模板使用边界与准备事项。

本机已完成的准备检查：30道开发题的 JSONL 结构和唯一ID、两份 YAML 解析、数据注册 JSON、三个样例的工具格式与现有报告校验。真实数值检查覆盖完整工况、默认物性变化、零功率及两类 COP 汇总口径。工具样例的本机复算记录另存于 `outputs/distillation_format_evidence_20261102/`，不使用正常聊天数据库。没有进行学生模型推理、训练框架加载、服务器训练或最终评测，配置有效性仍需服务器冒烟检查。
