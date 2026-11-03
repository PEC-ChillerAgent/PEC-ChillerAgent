# 第二阶段构建记录

| Rung | Feature | Acceptance command | Tier | Status |
|---|---|---|---|---|
| F0 | HTTP聊天入口→兼容模型客户端→回复 | `python -B -m pytest -q -p no:cacheprovider energy_agent/tests/test_provider.py` | MUST | passed |
| F1 | SQLite会话、绑定和工具循环 | `python -B -m pytest -q -p no:cacheprovider energy_agent/tests/test_chat.py` | MUST | passed |
| F2 | 数值证据报告、错误/记忆/上限 | `python -B -m pytest -q -p no:cacheprovider energy_agent/tests/test_chat.py energy_agent/tests/test_provider.py` | MUST | passed |
| F3 | 网页配置、聊天与原表单接入 | `python -B -m pytest -q -p no:cacheprovider tests energy_agent/tests`；`node tests/test_chat_ui.cjs` | MUST | passed |

## Run record

基础不是Git仓库。已有第一阶段工具、SQLite、FastAPI、Pydantic和httpx可复用。环境仅检查配置是否存在，未打印密钥；当前没有厂商地址、模型名或密钥。

## Official protocol references

- https://developers.openai.com/api/docs/guides/function-calling
- https://api-docs.deepseek.com/guides/tool_calls/
- https://api-docs.deepseek.com/guides/thinking_mode/
- https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions

## Deferred

流式token显示、多用户鉴权、其他设备模型和现场控制。

## Blockers

初次验收时真实厂商连接需要用户在本地填写base_url/model/API Key。后续用户已填写，并在2026-10-29完成DeepSeek模型列表查询和deepseek-flash连接测试（HTTP200）。真实模型的设备工具循环尚未验收，详见REPORT.md追加记录。

F0：8项提供商检查通过，HTTP聊天→真实客户端→明确标记的协议fixture→JSON回复。保留产物outputs/stage2_provider_protocol_smoke_test.json（protocol_fixture=true，live_vendor_test=false），未声称真实厂商连接。

F1/F2：累积24项连接和对话检查通过；完整回归118项通过。新增网页/chat以及原工作台转入入口。浏览器已验证隔离协议服务配置、连接、数据选择、真实工具计算、可点击4.18证据和Markdown报告下载。截图outputs/stage2_chat_ui.jpg明确来自协议fixture，非真实厂商。

第一轮复核的原始意见保存在SILENT_ASSUMPTION_SWEEP.round1.json。新增B-019至B-023并修复配置密钥归属、中文整数、数值可见来源/类别、通用知识数字范围、历史切换锁定、工具异常协议配对及地址端口验证。

F3最终自动检查：Python完整回归142项通过（exit 0），其中连接和聊天48项；`node tests/test_chat_ui.cjs`4项异步历史/绑定检查通过（exit 0）。`node --test`在本机沙箱因子进程spawn EPERM失败，改用直接执行同一个node:test文件通过，不需要额外权限。浏览器过程及最终截图另见REPORT.md。

第二轮原始意见保存在SILENT_ASSUMPTION_SWEEP.json（verdict=gaps，semantic_undeclared=1）。执行者随后更新B-021并补充B-024/B-025：锁定列表刷新、同时检查事实前后归属、在执行前拒绝重复调用ID。新增回归后完整Python143项、聊天UI5项、图表5项通过。第二轮后的修复只经执行者验证；balanced两轮预算已用完，不声称复核已clean。模型实际身份未获返回，接受等级为provisional。
