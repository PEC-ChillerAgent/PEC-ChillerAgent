# 第一阶段验收

`test_storage.py` 验证持久化、不可变快照、显式单位、输入范围和引用查询；`test_chiller_tool.py` 验证与原工作台逐项一致、缺测、控制列、越界、来源行和比较；`test_api.py` 验证HTTP接入、文件/工作表、分页、重启、CLI和完整导出。

在项目根目录执行 `python -B -m pytest -q -p no:cacheprovider tests energy_agent/tests`。测试数据目录按UUID隔离在outputs/agent_test_runs，并只清理各自工作区目录。
