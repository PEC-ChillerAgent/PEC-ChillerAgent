# focused1186 接入与部署

默认页面使用focused1186解释单条工况。Python工具先运行，学生只接收当前问题、当前计算证据和程序待答清单；身份或回答检查失败时显示工具事实，不自动调用DeepSeek。外部模型保留为手动选择的兼容模式。

## 1 模型备份与硬件

项目只保存冻结文件哈希，模型权重存放在你已有的备份或GPU服务器。`python -m chiller_student.configure --model-root "<模型备份根目录>"`创建本机路径配置；`python -m chiller_student.service --validate-only`全量验证，不加载GPU。

推理保留实验环境：Python3.11、Torch2.6.0+cu124、Transformers4.51.3、PEFT0.15.2，完整版本在`requirements-student.txt`及`deployment/focused1186.json`。服务不自动升级环境，不自动下载模型、量化、合并LoRA或启动训练。

GPU启动沿用验证过的严格数学模式及资源预检：单进程、单张支持BF16的CUDA12.4 GPU，启动时至少60GiB空闲显存。这个门槛沿用原实验运行配置，并不是8B模型的理论最低显存；不能据此声称其他部署精度已经测试。推荐复用原H100/H800训练环境。4GB显存、16GB内存的本机用作网页及物理计算端。

## 2 GPU服务器准备

将本项目源码放入GPU服务器目录，或者上传交付的精简代码包。复用原`chiller-sft-v1`环境及现有基座、focused适配器路径；不要重复上传16GB基座，不加载80步选择器代替focused。

服务需要本机与服务器持有相同的私有token文件。请通过SSH/SCP复制文件，不要把token内容粘贴到聊天、网页配置或GitHub。服务器令该文件权限为600；文件路径由参数指定。服务只监听127.0.0.1，远程访问走SSH隧道。

```bash
conda activate chiller-sft-v1
cd <GPU服务器上的项目源码目录>
chmod 600 .student_credentials/student-service.token
bash scripts/run_student_service.sh \
  --model-dir <已有Qwen3-8B目录> \
  --adapter-dir <已有adapter_focused_epoch1目录> \
  --token-file .student_credentials/student-service.token \
  --port 18081
```

等待`FOCUSED1186_READY http://127.0.0.1:18081`。哈希、适配器FP32张量或环境不一致时服务会停止，不修复或降级模型。保留该终端；Ctrl+C仅停止本次服务。程序不会结束其他GPU进程。如果显存不足或端口已用，请先核实你自己的旧服务，再决定是否关闭。

只在原环境不存在时，另建Python3.11环境并安装`requirements-student.txt`；不要为解决警告直接升级原实验环境。

## 3 本机SSH隧道

在本机PowerShell新终端运行，使用实例实际SSH主机和端口：

```powershell
.\scripts\start_student_tunnel.ps1 -Server <SSH主机> -SshPort <SSH端口>
```

默认映射本机28081到服务器18081。密码只在SSH提示中输入，不保存到项目。终端没有新输出通常表示隧道保持连接；保留窗口。

在另一个本机终端运行`python -m chiller_student.check_connection`，只核对服务健康与冻结身份，不生成回答、不调用外部API。显示`connected: true`与`identity_verified: true`后继续。

## 4 本机Chiller Lab

另开本机PowerShell，进入项目，在已安装`requirements.txt`的环境中运行：

```powershell
.\scripts\start_student_app.ps1 -Python python -Port 8001
```

打开`http://127.0.0.1:8001/`输入一条完整工况或使用合成示例，转入智能分析。页面默认选择“学生模型 focused1186”。环境变量和路径可通过启动参数调整；`.env.example`不会自动加载。

为避免环境混淆，可以将`-Python`设置为你应用环境的python.exe绝对路径。应用端不需要安装Torch。

## 5 核验真实接入

先询问“请给出本次制冷量、输入功率和COP，并解释COP表示什么。”然后核对：

1. 下载的计算产物确实由Python生成，有本次run_id与正确源单位。
2. 回答的model为`chiller-focused1186`，身份中的适配器SHA为冻结的`136eee…`，不是`e786…`的旧选择器。
3. 点击引用可到本次计算；补录数据后新建对话、重新计算，运行标识应变化。
4. `report_mode=student_explanation`表示学生正文经有限检查后呈现；`tool_facts`表示回退，不能算学生成功。
5. 默认学生路径的teacher_calls恒为0；不支持的仿真/知识/故障请求不会自动切换外部API。

服务启动记录在`outputs/student_service/<时间戳>/service_ready.json`，请求与原始返回分别保存，token不会写入日志。页面审核接口保留当前工具产物与原模型回复。

## 6 回滚与范围

停止本机应用即可回滚当前运行；需要外部模型时，在新对话中明确选择“外部模型（可选）”并填写自己的服务配置。学生和外部模型会话不混用，历史数据与模型备份保留。

本次软件接入不重新定义120题成绩。现有比较是回顾性、非专家初审；页面端真实GPU回答与故障处理仍应按第5节保存证据，不能用软件夹具测试代替。

默认`POST /agent/v1/chat`和`POST /agent/v1/analysis`均使用focused1186。外部模型仅由显式`POST /agent/v1/chat/external`调用；旧外部API客户端应迁移到该路径，不会在学生失败后自动触发。
