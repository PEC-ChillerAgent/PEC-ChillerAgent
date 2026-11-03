# 第二阶段规格

目标：按用户选择的OpenAI兼容接口实现模型连接、聊天入口、受控工具调用、持久对话和带证据的分析报告，接入现有网页。

输入：用户配置的base_url/model/API Key，聊天消息，可选已登记数据集及显式仿真设置。

输出：聊天会话、工具运行轨迹、经过服务端数值引用解析的回答、可下载报告和证据链接。原数值模型继续复用。

验收：`python -B -m pytest -q -p no:cacheprovider tests energy_agent/tests`；JavaScript语法和聊天交互检查；真实本地HTTP完整调用。没有厂商密钥时仅验证明确标注的协议测试服务，不声称连接过真实厂商。

Base commit：none (not a git repo)，已执行git rev-parse HEAD。

effort=balanced，ask=never，assurance=draft。范围为本地单用户同步聊天；流式token输出、其他设备和现场控制不在本轮范围。用户已选择OpenAI兼容接口，具体服务/模型/密钥由本地配置。
