# 120题六系统比较：当前可运行两个开源基线

这120题是知道学生128题结果后选出的8工况×15题型子集；不是新的独立测试。
focused1186的120份回答与原审核标签原样复用；116/120不表示训练改善。
原完整128题仍为116/128；8道基础指标题保留为额外业务回归。
同一设备实验系列、2文件、8共享基础工况，不是120台独立设备。
比较目标：同信息任务能力；不预设学生优胜，不更改提示、不挑选多次生成。
协议/引用通过不等于事实正确及完整任务成功。工具回退不算学生成功。

## GPU服务器（用户执行）

沿用chiller-sft-v1@5befcb78，不升级环境、不停止其他进程、不新建训练。
H100/H80080GB，要求至少60GiB空闲显存及4GiB结果磁盘。
首先解压到新的chiller_physics120_comparison_kit_v1目录，再执行：

```bash
cd ~/epfs/chiller_physics120_comparison_kit_v1
conda activate chiller-sft-v1
bash launch_physics120_comparison.sh base8b
```

只启动一次。4道不计分预热+120道原始Qwen3-8B回答；不加载学生LoRA。
预热不是历史输出完全一致性见证。逐token核验真实贪心、不变RNG、冻结权重。
启动器返回Watch命令；复制该命令看日志。Ctrl+C只结束tail，不停止后台任务。
返回results/physics120_base8b_*_review.zip，失败包也保留返回。

base8b完成后，再依次执行14B；新权重约29.5GB十进制，至少留40GiB下载磁盘：

```bash
python -B -m student_tools.physics120_download --download
bash launch_physics120_comparison.sh qwen14b
```

下载固定提交40c069824f4251a91eefaf281ebe4c544efd3e18，并核验全部8分片及配置。
下载如失败，保留目录返回错误，不重新执行以覆盖既有文件。
14B默认目录/root/epfs/chiller_comparison_models/Qwen3-14B-40c0698。
base8B默认目录/root/epfs/chiller_student_baseline_kit_v1/models/Qwen3-8B。
一个GPU顺序执行，不同时启动两份。返回physics120_qwen14b_*_review.zip。

## API比较

DeepSeek/Kimi请求草稿不含答案、密钥或开发数据；没有执行API的启动脚本。
当前Kimi新版本始终思考；GPT候选与中转平台身份/计费需先核实。
不能宣称三种API与本地模型等推理预算；统一问题证据，分开记录资源。
GPT中转如无法核验上游，不标成已认证官方GPT基线。
取得有效配置/范围后另冻结API包；不会读取或上传密钥。

## 本机文档复核（无GPU、无下载、无API）

在本包根目录用PowerShell原样执行以下两条命令，若目录已存在则返回信息：

```powershell
& 'F:/Anaconda/envs/modelica/python.exe' -X utf8 -B -m student_tools.physics120_comparison --validate-package-only --output results/doc_validation
& 'F:/Anaconda/envs/modelica/python.exe' -X utf8 -B -m student_tools.export_smoke_review --run-dir results/doc_validation
```

文档复核仅证明封包与命令可用。GPU/14B下载/Linux启动器必须由真实服务器验证。
无API调用，无训练、无优化器、无页面切换，不改变原128题或原一次性记录。
统计及论文图只在人工逐题审核后填入新模型数据，失败/截断保留在分母中。
