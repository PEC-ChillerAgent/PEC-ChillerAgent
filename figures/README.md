# 系统架构与学生训练图

保留5份系统架构与训练流程图。原始Visio与PDF由作者提供并原样保存，PNG从对应PDF渲染以供GitHub预览。文件对应关系及SHA-256见[清单](paper/figure_manifest.json)。模型比较结果图由作者在本地另行保存，不在当前代码仓库发布。

## 当前代码架构图

这三幅图对应当前源码：

- [默认学生分析架构](system-architecture.md)：[PNG](system-architecture.png) / [Mermaid](system-architecture.mmd)。
- [单次请求时序](analysis-sequence.md)：[PNG](analysis-sequence.png) / [Mermaid](analysis-sequence.mmd)。
- [学生训练流程](student-training.md)：[PNG](student-training.png) / [Mermaid](student-training.mmd)。

图源与Markdown中的代码相同，使用Mermaid CLI 12.2.0渲染核验。需要调整时编辑`.mmd`并同步`.md`，再生成PNG：

```bash
npx --yes @mermaid-js/mermaid-cli@12.2.0 -i figures/system-architecture.mmd -o figures/system-architecture.png -b white
```

## 作者原始论文图

### tu0.1：通用工具调用Agent

[Visio源文件](paper/tu0.1.vsdx) · [PDF（Figure_1.pdf）](paper/Figure_1.pdf) · [PNG](paper/tu0.1.png)

![通用工具调用Agent](paper/tu0.1.png)

通用工具调用路径。当前默认学生入口采用后台固定物理计算，具体区分见[架构说明](../docs/architecture.md)。

### tu0.2：双路径系统与学生适配

[Visio源文件](paper/tu0.2.vsdx) · [PDF（Figure_2.pdf）](paper/Figure_2.pdf) · [PNG](paper/tu0.2.png)

![双路径系统与学生适配](paper/tu0.2.png)

通用分析路径、学生路径与LoRA适配关系。当前应用默认使用focused1186解释接口。

### tu1：水侧物理计算与证据

[Visio源文件](paper/tu1.vsdx) · [PDF（Figure_3.pdf）](paper/Figure_3.pdf) · [PNG](paper/tu1.png)

![水侧物理计算与证据](paper/tu1.png)

水侧热量、COP、代数能量平衡偏差与证据结构；图中单位应与实际源单位转换共同阅读。

### tu2：离线教师辅助训练与在线分析

[Visio源文件](paper/tu2.vsdx) · [PDF（Figure_4.pdf）](paper/Figure_4.pdf) · [PNG](paper/tu2.png)

![离线教师辅助训练与在线分析](paper/tu2.png)

离线教师辅助训练和在线解释。教师提供离散参考，推理时Python提供本次事实。

### tu3：答案级监督与LoRA

[Visio源文件](paper/tu3.vsdx) · [PDF（Figure_5.pdf）](paper/Figure_5.pdf) · [PNG](paper/tu3.png)

![答案级监督与LoRA](paper/tu3.png)

提示位置屏蔽、答案级监督与LoRA更新。历史1186次更新属于最后一轮，不是全部训练成本。
