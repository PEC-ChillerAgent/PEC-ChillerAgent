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
