# Buildings 13.0.0 ElectricEIR 对齐说明

## 当前交付范围

`chiller_app` 的网页默认引擎为 ElectricEIR 水冷制冷模式的 Python 移植版。
分析依据是本机 `Buildings 13.0.0` 可读源码，使用普通源码工具检查，无需二进制反编译。
此次没有修改安装库或 OpenModelica 配置；机组参数随应用打包，正常使用不依赖本机库路径。

| 原模型来源 | 应用实现 |
|---|---|
| `Fluid/Chillers/ElectricEIR.mo` | `model/electric_eir.py`：capFunT、EIRFunT 双二次曲线，EIRFunPLR 二次曲线；曲线使用摄氏温度 |
| `BaseClasses/PartialElectric.mo` | 理想出水设定值控制、PLR1、PLR2、CR、功率、冷量、冷凝热、COP 和停机分支 |
| `Utilities/Math/Functions/{regStep,smoothMin,smoothMax,biquadratic}.mo` | 相同平滑多项式和过渡宽度，不用普通 min/max 替代 |
| `Fluid/Interfaces/FourPortHeatMassExchanger.mo` | 恒物性且给定正向流量时的水侧能量方程；C = 额定质量流量 × tau × cp |
| `Fluid/Chillers/Data/ElectricEIR.mo` | 提取 159 个具体参数记录，网页提供其中 158 个水冷记录；1 个风冷记录不可选 |
| `Buildings.Media.Water` / Modelica 4.1.0 恒物性水 | 网页/工作台默认 cp=4184 J/(kg K)，ρ=995.586 kg/m³，可显式修改 |

参数及源文件 SHA-256 在 `chiller_app/model/buildings_eir_catalogue.json`，运行 JSON 同时记录源文件摘要、实际参数、物性、初态规则与求解设置。版权和许可保存在 `model/BUILDINGS_LICENSE.txt`。

## 使用页面

在项目目录和虚拟环境中运行：

```powershell
python -m uvicorn chiller_app.api.fastapi_app:app --reload
```

打开 `http://127.0.0.1:8000`，选“机组仿真”，默认模型为 ElectricEIR。
选定机组后点击“载入示例工况”，会填入该机组的额定流量和有效参考温度；再选择稳态或动态并运行。
设定温度是目标出水温度，与实际出水测量不同。曲线与可用冷量限制会影响能否达到目标。

必要输入：两侧进水温度、两侧正向质量/体积流量、出水设定温度。启停默认开机。
实测功率与出水测量可留空；它们仅用于实测指标和对照，不驱动 ElectricEIR 状态或功率。
上传数据可映射 `TSet_K` 和 `operating_status`，分别代表逐行设定温度和 0/1 启停状态；
一旦映射，列必须完整有效，不能靠默认值掩盖缺失。未映射时用页面固定设定值和默认启停。
所有操作温度（含设定温度、初始温度）共用输入温标。

机组参数展开框可以编辑 JSON，勾选“使用自定义参数”才生效。这里固定采用 SI 单位：温度 K、
热流 W、流量 kg/s，额定蒸发热流为负。曲线系数仍按摄氏温度拟合，不随温标选择改变。
通用框架不意味着一组性能曲线适合所有机组：新机组仍需正确额定参数和校准曲线。

结果支持自选单条/多条曲线，新增模型功率、模型 COP、PLR1、PLR2、CR、性能修正系数等。
`power_kW` 与 `COP` 始终是实测输入/计算值；`simulated_power_kW` 与 `simulated_COP` 是模型输出。
没有实测功率时实测 COP 留空，不以模型功率混算。

## 数值与符号

源码热流约定：蒸发器 `QEva_flow` 为负，冷凝器 `QCon_flow` 为正；页面“模型制冷量”为 `-QEva_flow/1000`。

```text
QEva_ava = QEva_nominal * capFunT(TEvaLvg_C, TConEnt_C)
QEva_set = smoothMin(mEva * cp * (TSet - TEvaEnt), Q_small, ...)
PLR1 = smoothMin(QEva_set / (QEva_ava + Q_small), PLRMax, ...)
PLR2 = smoothMax(PLRMinUnl, PLR1, ...)
CR = smoothMin(PLR1 / PLRMin, 1, ...)
P = -QEva_ava / COP_nominal * EIRFunT * EIRFunPLR(PLR2) * CR
QEva = smoothMax(QEva_set, QEva_ava, ...)
QCon = -QEva + etaMotor * P
COP = -QEva / (P - Q_small)
```

本版本逐项保留源码：包括 PLRMax 用于 PLR1 限制，而实际 QEva 仍由源码中的 QEva_ava 分支限制，
没有自行把可用冷量再乘 PLRMax。最低负荷用平均循环比表达，最低卸载负荷下的功率用 PLR2 计算。
`etaMotor` 是电机热进入制冷剂的比例，不是再除一次功率的电机效率。

动态模式：两水温状态，热容取 m_nominal × tau × cp；默认 tau=30 s。固定初态默认冷冻侧 5°C、冷却侧 25°C，
与父类默认开始温度一致，但应用选择固定初态，不声称等同于所有 Modelica 初始化模式。
输入在 t_i 到 t_(i+1) 保持，t0 输出初态，每个 run_id 重置，不排序、不插值、不外推末点。
使用 SciPy BDF，rtol=1e-9，atol=1e-9 K；当前状态水温参与性能曲线，不用测量温度或目标温度替代。
稳态模式使用 Brent 求解蒸发器水侧能量方程，再计算冷凝出水；逐行独立，忽略热容和初态。

曲线有效温区、负能耗系数、0°C/60°C 参考温度与额定工况冷量修正超出 0.9–1.1 会提示。
提示不等于故障诊断，也不自动截断曲线、限温或停机。

## API

- `GET /workbench/eir/catalogue`：水冷参数记录和来源摘要。
- `POST /workbench/run`：物理计算或 ElectricEIR 仿真。
- `POST /model/electric-eir/simulate`：ElectricEIR 专用仿真接口，与工作台使用同一请求结构。
- `POST /model/electric-eir/calibrate`：健康稳态数据上的单参数功率校准。
- `GET /model/definition` 和 `GET /models`：当前仅提供 ElectricEIR 仿真模型。
- 研究用训练、预测、诊断及优化服务独立保留；不属于 Buildings 故障或控制模块移植。

请求示例（单位 °C、kg/s，未提供实测功率）：

```json
{
  "operation": "simulate",
  "records": [{"tei":13.89,"tci":26.67,"me":10.35,"mc":19.24}],
  "schema": {
    "column_map":{"TEI_K":"tei","TCI_K":"tci","evap_flow_kg_s":"me","cond_flow_kg_s":"mc"},
    "temperature_unit":"C","flow_unit":"kg/s"
  },
  "simulation": {
    "engine":"electric_eir","mode":"dynamic","setpoint":8.89,
    "duration_s":600,"interval_s":60,"tau_evap_s":30,"tau_cond_s":30
  }
}
```

## 验证结果与边界

已通过 Python 单元与 API 检查：理想常数曲线可解析解、能量守恒、额定/部分/过载、最低负荷循环、停机、
动态收敛、控制列缺失、独立序列初始化、实测值不驱动状态、自定义参数及曲线温区提示。
Python/API 回归检查、图表逻辑检查和 JavaScript 语法检查通过。当前没有新增浏览器视觉验证。

`tests/reference/ElectricEIRAlignment.mo` 和 `validate_eir.mos` 已生成独立的 OpenModelica 稳态/动态参考结果。对照覆盖部分负荷、停机/重启、低负荷、超容量需求及冷凝进水温度阶跃；比较 0–600 秒的 11 个时刻，并按容差取事件后记录。

现有报告 `artifacts/eir_validation/alignment_report.json` 的动态功率最大误差约 0.003055 W，温度最大误差小于 3e-6 K；稳态结果接近双精度舍入误差。细节见 [实施与对照记录](implementation_progress_2026-10-26.md)。这些结论限于该记录和参考工况，不能替代目标机组适配验证。

在已配置 OpenModelica 的环境，可进入 `tests/reference` 重跑：

```powershell
& F:/modelica/bin/omc.exe -n=1 validate_eir.mos
```

返回项目根目录后执行：

```powershell
python tests/reference/compare_eir.py
python -B -m pytest -q -p no:cacheprovider tests/test_reference_alignment.py
```

更换对照机组时须匹配曲线、物性、流量、初态、tau、设定温度和启停。

未移植范围：完整 Buildings 库、ElectricReformulatedEIR、Carnot、吸收式、模块化可逆机组、
热回收切换、风冷、流向反转、零流量运行、压力网络、非恒物性介质、实际 PID/防冻控制、制冷剂状态和故障模型。
它们需要独立建模与验证，不能从 ElectricEIR 的同名输出推断已经实现。
