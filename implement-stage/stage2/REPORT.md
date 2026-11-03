# 第二阶段实施与验收

复核限定：最终轮记录仍为gaps（1项未声明语义限制及3项具体问题）；对应选择已补入台账并修复，最终143项Python及5项聊天交互检查通过。两轮预算已用完，末轮后的修复仅经执行者验证，不能表述为独立复核通过。

## 已可运行的内容

现有 FastAPI 应用新增 `/chat`。用户填写兼容模型服务配置后，模型可选择数据检查、实测物理分析、模型仿真或实测/模型比较。所有数值工具复用第一阶段与原工作台的 `run_workbench` 计算边界。

完整持久路径为：消息 → 真实兼容聊天客户端 → 有调用上限的工具循环 → 原数值计算 → 保存运行 → 服务器事实片段 → 历史会话及 Markdown 报告。模型回复中的数字可点开对应运行结果与 JSON Pointer。工作台可将当前数据、单位、物性与仿真配置转入聊天。

正常数据目录为 `outputs/energy_agent`。配置保存在本机 SQLite 或服务进程环境，接口不回显密钥。原工作台保持独立入口。

## 验收命令与实际结果

使用 `F:/Anaconda/envs/modelica/python.exe` 虚拟环境：

| 命令 | exit | 实际结果 |
|---|---|---|
| `python -B -m pytest -q -p no:cacheprovider tests energy_agent/tests` | 0 | 143 passed；一个上游 TestClient 弃用提示 |
| `node --check chiller_app/web/chat.js` | 0 | 语法通过 |
| `node --check chiller_app/web/app.js` | 0 | 语法通过 |
| `node tests/test_chat_ui.cjs` | 0 | 5 passed；初始化、历史切换、失败恢复、刷新锁定及后续消息绑定 |
| `node tests/test_chart_utils.cjs` | 0 | 5 passed |

`node --test`初次因本机沙箱拒绝子进程（spawn EPERM）无法启动，随后直接执行相同 node:test 文件通过。没有为此扩大权限。工程不是 Git 仓库，未创建仓库或提交。

实际本地 HTTP：正式应用的 `/`、`/chat`、`/docs`、`/agent/v1/health` 均返回200；正式配置为 `configured=false, has_api_key=false`。启动命令及页面操作见 [运行说明](../../docs/agent_stage2.md)。

## 浏览器证据与真实性

隔离协议 fixture 使用 `8769/8770`，数据目录为 `outputs/stage2_ui_fixture`，所有来源均标识 `protocol_fixture=true, live_vendor_test=false`。浏览器实际验证配置保存、连接测试、选择数据集、工具执行、证据链接、报告下载、原工作台转入及历史恢复。最终复核显示服务器可见的“实测COP（有效输出点均值） · 实测派生：4.1655318”片段，来自真实水侧计算。该值沿用原网页的cp和密度。显式4180/1000物性示例的COP为4.18，亦有测试与运行证据。

- `outputs/stage2_provider_protocol_smoke_test.json`：早期最小 HTTP 路径的协议 fixture 记录。
- `outputs/stage2_chat_ui.jpg`：隔离 fixture 的实际浏览器计算和证据页面。
- `outputs/stage2_chat_start.jpg`：正式8000端口的模型配置位置。
- `outputs/stage2_ui_fixture/PROVENANCE.json`：测试来源限定。

初次验收后已关闭隔离协议服务，正式8000服务已启动且保留在浏览器。当时未填入真实厂商配置，初次验收产物均不能作为真实厂商连接证据。

2026-10-29后续连接排查：用户保存了DeepSeek配置并报告HTTP400。查询真实`/models`返回200，可用ID为`deepseek-flash`、`deepseek-v4-pro`。已将无效模型名`deepseek`改为`deepseek-flash`，保留现有密钥和地址。原启动进程继承受限执行环境的不可用代理，随后从允许联网的环境重新启动仅监听127.0.0.1:8000的服务。实际`POST /agent/v1/llm/test`返回HTTP200、connected=true、model=deepseek-flash、message=连接成功。这仅验收了真实厂商连接，尚未把真实模型的工具循环或数值分析记作已验收。未打印、导出或写入报告任何密钥。

## 阶梯状态及范围

F0连接主路径、F1会话/绑定/工具循环、F2事实报告/错误/记忆/调用上限、F3网页/工作台接入均已通过本地验收。生产没有模拟模型桩；测试 fixture 仅用于验收。

后续扩展位置为水泵、冷却塔与空调系统工具，目前这些目录不含可调用数值能力。流式输出、多用户鉴权、自动训练/优化和现场控制不在本阶段范围。

## 复核

第一轮原始意见见 `SILENT_ASSUMPTION_SWEEP.round1.json`：3项未声明选择（其中semantic=2）、2项陈旧记录、6项可复现问题。已补入B-019至B-023，更新记录并加入回归检查。

第二轮原始意见见 `SILENT_ASSUMPTION_SWEEP.json`：verdict=gaps，1项未声明semantic位置限制、1项陈旧记录，3项可复现问题。执行者已更新B-021，补入B-024/B-025，修复数据集刷新期间发送、后置事实归属、重复tool_call_id三条路径，并加入回归检查。最终检查见上表。两轮复核预算用完，第二轮后的修复只经执行者验证，未取得重新复核的clean结论。

请求复核模型为gpt-6-astra/xhigh；工具没有返回可验证的实际模型身份，`review_independence=unverified-family`、`acceptance_status=provisional`。不把同系列或身份未证实的复核当作独立真实性证明。

## 接口与语义选择全文

ASK mode为never；用户确定兼容接口类别，其余实现选择在编码前记录，复核新发现的选择以sweep来源补充。下表保留所有semantic行全文及interface名称/来源。


# 第二阶段接口与语义选择

ASK mode: never。用户已选择OpenAI兼容接口；服务地址、模型名和密钥由本地配置。以下在实现前记录。

| ID | 未确定的内容 | 选择 | Class | Source |
|---|---|---|---|---|
| B-001 | 模型协议 | 标准/chat/completions，真实httpx客户端，无需新增SDK；保留assistant reasoning_content和tool_calls用于后续调用 | interface | user |
| B-002 | 凭据与配置 | 服务端环境或现有SQLite的私有local_settings表；公开接口只返回has_api_key，空密钥仅在地址未变时保留；不从模型参数接收URL或密钥。JSON替换写入在本机发生WinError5后，改为SQLite事务保存 | interface | default |
| B-003 | 配置优先级 | 显式ENERGY_AGENT_LLM环境变量覆盖本地SQLite对应字段；配置页面说明来源；保存配置不会修改进程环境 | interface | default |
| B-004 | 缺配置 | 聊天明确返回503，页面提示配置；不自动切到规则模型或伪造已连接状态；真实厂商验收取决于用户本地凭据 | semantic | default |
| B-005 | 会话绑定 | 每个会话固定可选dataset_id/asset_id和显式simulation设置，换数据集新建会话；模型只能调用本会话已绑定的数据 | interface | default |
| B-006 | 可调用能力 | inspect_dataset与chiller_analyze；分析任务由模型选择，设备和数据引用由服务端注入。仿真性能记录必须由会话显式选择，不能让模型猜测目标机组 | semantic | default |
| B-007 | 数值报告 | 模型用{{fact:F编号}}引用服务端事实；服务端代入数值、单位和证据。未引用的分析数字或未知引用触发一次受限修正，仍不合规则回到明确标识的工具事实报告 | semantic | default |
| B-008 | 汇总含义 | 沿用第一阶段sample_mean、缺测、越界和比较样本选择；不把模型预测写成实测，不由聊天生成故障概率或确诊 | semantic | default |
| B-009 | 对话记忆 | SQLite保存公开对话、运行引用和私有协议消息；公开API不返回reasoning_content。模型保留最近10个完整轮次，不截断工具调用对 | interface | default |
| B-010 | 调用上限 | 每轮最多4次模型请求、4次分析工具调用；超限或厂商失败保留已完成工具事实，明确状态；同一会话并发发送返回409 | interface | default |
| B-011 | 网络及异常 | 超时可配置且≤60秒，无自动付费重试；HTTP鉴权/限流/超时以脱敏错误显示，不把上游原始错误正文或密钥写入聊天 | interface | default |
| B-012 | 网页接入 | 在原网页新增智能分析页面入口，可将当前表单数据登记后转入聊天；独立/chat页面支持已有数据集、历史会话、配置、证据和报告下载 | interface | default |
| B-013 | 测试真实性 | 测试可注入明确标识的兼容协议fixture；生产无假模型。协议fixture的回复不能作为真实厂商连接证据 | semantic | default |
| B-014 | 接口范围 | 本地单用户，保留现有工具API；不新增训练、校准、优化或控制工具。固定会话绑定用于避免跨设备混用 | semantic | default |
| B-015 | 中断与并发会话 | SQLite原子租约拒绝同会话并发；租期10分钟，每次模型/工具边界刷新；租约到期可将中断轮次标为失败后继续，不承诺硬中止正在计算的数值求解 | interface | default |
| B-016 | 事实引用与记忆范围 | 事实ID在会话内递增；数据集行数可引用元信息，其余数字指向已保存运行中的JSON Pointer；模型只见最近10个完整轮次及相关事实 | semantic | default |
| B-017 | 聊天状态 | status表示本轮会话完成情况；工具partial仍可完成回答，工具needs_input或执行条件不足使聊天needs_input，工具/厂商失败使聊天failed；分别保留每次工具的原始状态 | semantic | default |
| B-018 | 网页仿真默认 | 独立聊天页默认稳态、series；用户可显式选择动态/恒定工况和时间规则。原工作台转入时沿用当前表单设置，不替换底层默认 | semantic | default |
| B-019 | 通用OpenAI环境密钥 | OPENAI_API_KEY仅在目标主机恰为api.openai.com且没有服务专属或本地密钥时回退；绝不自动发给第三方兼容服务 | interface | sweep |
| B-020 | 通用知识数值 | 未绑定数据且本轮未请求工具的一般知识回答可包含数字，明确标为非设备计算；绑定数据或已请求工具时，阿拉伯/中文整数、百分比和小数结论均须引用事实 | semantic | sweep |
| B-021 | 数值归属 | 数值片段显示服务器生成的指标名和来源；检查占位符前后相邻分句中明确相反的实测/模型或指标类别归属并触发修正。该启发式校验不宣称证明任意自然语言解释的完整语义 | semantic | sweep |
| B-022 | 会话切换 | 初始化或读取历史会话期间禁止发送与切换；读取失败保留先前会话并恢复其选择，避免消息绑定到旧设备 | interface | sweep |
| B-023 | 工具异常历史 | 工具边界意外异常也生成对应tool_call_id的脱敏失败回复；保存到历史前补齐所有未配对工具回复 | interface | sweep |
| B-024 | 刷新与绑定 | 手动刷新数据集或历史列表时也冻结发送、上下文选择和会话切换，异步刷新不得覆盖已提交会话的绑定显示 | interface | sweep |
| B-025 | 工具调用身份 | 同一上游assistant消息内的tool_call_id必须唯一；重复ID作为无效协议响应拒绝，避免历史配对合并不同工具结果 | interface | sweep |

官方协议依据：OpenAI function-calling说明、DeepSeek Tool Calls/Thinking Mode、阿里云OpenAI兼容接口说明。确切链接见BUILD_NOTE.md。
