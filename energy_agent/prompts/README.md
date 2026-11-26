# 提示词与证据协议

`system.md`用于用户显式选择的外部模型Agent，约束工具调用、缺测处理和事实引用。它不是默认学生模型的完整提示词。

默认focused1186输入由 `chiller_student/focused_contract.py`连接到 `planned_task_contract_v2.py`，从当前问题和本次Python产物构建system/user消息、类型化事实及待答清单。推理采用Qwen原生非思考模板；原历史会话不作为新一轮数值证据。

模型输出经 `focused_output.py`和已知物理断言检查后，由应用填入真实事实值。修改提示词、事实结构或生成模板会改变模型实际输入，应单独验证，而不是仅修改这个目录中的Markdown文件。
