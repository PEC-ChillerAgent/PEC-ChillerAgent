# 第一阶段构建记录

| Rung | Feature | Acceptance check | Tier | Status |
|---|---|---|---|---|
| F0 | CLI → 现有计算 → JSON 实物 | `python -B -m energy_agent demo --output outputs/agent_stage1_demo.json` | MUST | passed |
| F1 | 类型化数据集与 SQLite 引用 | `python -B -m pytest -q -p no:cacheprovider energy_agent/tests/test_storage.py` | MUST | passed |
| F2 | 统一工具、仿真、缺测/越界及证据 | `python -B -m pytest -q -p no:cacheprovider energy_agent/tests/test_storage.py energy_agent/tests/test_chiller_tool.py` | MUST | passed |
| F3 | HTTP/文件/CLI 集成及全量回归 | `python -B -m pytest -q -p no:cacheprovider tests energy_agent/tests` | MUST | passed |

## Run record

Base commit：none (not a git repo)。本机 Python：F:/Anaconda/envs/modelica/python.exe。本地复用调查：已有 WorkbenchRequest/run_workbench、文件解析、EIRPerformance、Pydantic2、FastAPI 与 SQLite 标准库可覆盖第一阶段。

F0：CLI 导出实际数值 JSON，冷量418 kW、COP4.18，exit=0；F1：11项存储检查通过；F2：累积28项检查通过；F3：现有模型与新工具累计86项通过，exit=0。未初始化Git，未创建提交。后续原生审查使用文件列表。

当前新增/修改源码：energy_agent/contracts/datasets.py、tools.py；storage/repository.py；config/settings.py；tools/chiller/backend.py、tool.py；registry/tools.py；runtime.py；api/routes.py、app.py；__main__.py；tests/conftest.py、test_storage.py、test_chiller_tool.py、test_api.py；chiller_app/api/fastapi_app.py；examples/agent_physics_request.json。

## Deferred

第二阶段的对话、大模型提供商连接和自然语言报告；训练/校准/优化工具、异步任务、其他设备模型及多用户鉴权。

## Blockers

None.

首轮审查：3项未声明选择（2项semantic、1项interface）及A-016措辞不符；已记录A-017至A-019并修正。另修复已复现的大数RMSE溢出。新增回归后92项通过；来源行示例去重检查随后加入，待最终检查。审查模型身份未由运行时返回，记录为unverified-family/provisional。
实际Uvicorn服务经loopback HTTP完成登记→调用→完整导出，产物outputs/agent_stage1_http_demo.json。

## 最终验收

全量命令：`F:/Anaconda/envs/modelica/python.exe -B -m pytest -q -p no:cacheprovider tests energy_agent/tests`，94 passed（原53、新增41）。新增来源行去重与旧运行字段读取回归通过；测试内SQLite连接均显式关闭。

CLI真实示例和工具JSON契约导出均退出0。产物：outputs/agent_stage1_demo.json、outputs/agent_stage1_http_demo.json、outputs/agent_stage1_tool_contracts.json。默认SQLite数据持久保存。

两轮审查已完成，首轮3项未声明选择、2项semantic；第二轮未声明0、stale0、concrete_failures0。原始回复分别保存在SILENT_ASSUMPTION_SWEEP.round1.json和SILENT_ASSUMPTION_SWEEP.json。实际模型身份未由运行时返回，review_independence=unverified-family，acceptance_status=provisional，不作为独立正确性证明。

Stage-one live stubs：none。agents/providers/prompts及pump/cooling_tower/hvac_plant仅为明确保留的后续扩展位置，不参与第一阶段验收。最后审查后仅更新文档与验收产物。
