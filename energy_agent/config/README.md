# 运行配置

`settings.py`管理数据目录，默认 `outputs/energy_agent`，可由 `ENERGY_AGENT_DATA_DIR`覆盖。

默认学生配置在 `student_focused.py`：环境变量优先于 `.student.local.json`，未指定时使用本机28081端口。token只从本地文件读取。`public()`返回的是配置状态与预期模型身份，不代表网络已连通；实际检查用 `python -m chiller_student.check_connection`。

`llm.py`管理用户显式选择的外部模型配置，支持 `ENERGY_AGENT_LLM_BASE_URL`、`ENERGY_AGENT_LLM_MODEL`、`ENERGY_AGENT_LLM_API_KEY`。密钥不回显；切换服务主机时不会沿用旧主机密钥。默认学生路径不加载外部模型配置。

`student_analysis.py`、`student_explanation.py`、`student_shadow.py`保留旧接口/历史会话兼容；当前默认模型以 `student_focused.py`及 `deployment/focused1186.json`为准。`.env.example`不会自动加载，变量应设置在启动应用的终端。

详细命令见[部署说明](../../docs/student_deployment.md)。
