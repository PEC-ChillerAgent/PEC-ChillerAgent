# 软件回归

在仓库根目录运行：

```bash
python -B -m pytest energy_agent/tests tests -q -p no:cacheprovider
node tests/test_chat_ui.cjs
node tests/test_chart_utils.cjs
```

`test_focused_application.py`覆盖真实Python先算后解释、当前运行引用、模型身份不匹配、请求重放、超时、坏格式、断言错误和回退。模型传输是明确的合成夹具，不计作真实GPU正确率。

其余文件覆盖不可变数据集、源单位、缺测、ElectricEIR一致性、外部Provider、教师采集导出、报告渲染、持久会话、HTTP和CLI。测试临时数据位于 `outputs/agent_test_runs` 的独立UUID目录。软件测试不调用付费API、不启动训练。
