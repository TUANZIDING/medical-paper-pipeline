---
name: medical-paper-pipeline
description: 医学科研论文全流程自动化：从数据到SCI投稿的端到端pipeline。面向创伤外科医生回顾性临床/流行病学研究。
---

# Medical Paper Pipeline — SKILL.md

> 本skill自动化医学科研论文从数据到SCI投稿的全流程。通过阶段化人工确认checkpoint驱动，每个阶段输出规范化文件，状态持久化于`pipeline_state.json`。
>
> **适用研究类型：** 回顾性队列研究、病例对照研究、横断面研究
> **适用数据来源：** HIS数据库、创伤登记系统、Excel、CSV、SPSS输出、混合来源

---

## 文件约定

| 文件名 | 用途 |
|--------|------|
| `pipeline_state.json` | 流水线状态持久化，各阶段读写 |
| `data_cleaning_log.md` | 所有数据清洗决策的完整记录 |
| `statistical_results.md` | Stage 1所有统计结果（APA格式） |
| `stat_methods_paragraph.md` | 自动生成的统计方法段落 |
| `figures/flow_chart.png` | 患者流程图（STROBE Item 13） |
| `figures/fig_1.png` | 图表编号从1开始顺序递增 |
| `pipeline_state.json` 中字段 `data_plan_confirmed: true` | Stage 0的gate，确认为true才进入Stage 1 |

---

## Stage 0 · 项目初始化与数据评估

**触发：** 用户提供研究方向 + 数据来源描述

### 0.1 数据来源分类与访问计划

**依据：** 本阶段对应STROBE声明Item 4（研究设计）、Item 5（机构/时间/地点）的初始评估。

**AI动作：**
1. 解析用户描述，分类数据类型：
   - **HIS/数据库**（SQL导出）：记录表结构、主要字段、日期范围
   - **Excel/CSV**：列名、数据量、字段类型
   - **SPSS输出**：分析结果表格，需额外验证原始数据可及性
   - **混合来源**：说明数据关联方式（ID匹配合并）
2. 生成1-3个具体数据访问计划，标注各方案的优缺点
3. 列出确认问题清单：
   - 结局变量的精确定义（诊断标准、时间节点）
   - 暴露/分组变量的定义依据
   - 混杂因素的初步候选列表
   - 随访方式和随访截止日期
   - 数据缺失的主要原因（回顾性研究的常见缺失来源）

### 0.2 伦理与注册状态评估

**依据：** ICMJE保护研究参与者的推荐要求所有涉及人类受试者的研究（含回顾性）均需伦理审查或明确说明豁免理由。[ICMJE](https://www.icmje.org/recommendations/browse/roles-and-responsibilities/protection-of-research-participants.html)

**AI动作：**
4. **询问IRB/伦理审查状态**（以下四选一）：
   - 已批准：需IRB编号和批准日期
   - 待审批：记录提交日期，预计获批时间
   - 需申请：建议启动审批流程，标注目标期刊对伦理的要求
   - 豁免：记录豁免理由（如仅用去标识化数据、现行诊疗数据二次分析）
5. **询问临床试验注册状态**：
   - FDAAA 801（美国）和NIH政策均不强制要求回顾性观察性研究注册。[ClinicalTrials.gov](https://clinicaltrials.gov/policy/fdaaa-801-final-rule) [NIH Grants](https://grants.nih.gov/grants/policy/nihgps/html5/section_4/4.1.3_clinical_trials_registration_and_reporting_in_clinicaltrials.gov_requirement.htm)
   - 但部分期刊（遵循ICMJE的期刊）鼓励自愿注册以提高透明度。[ICMJE FAQ](https://www.icmje.org/about-icmje/faqs/clinical-trials-registration/)
   - 若有NCT注册号则记录；若无需说明原因
6. 生成伦理声明草稿（见下方模板）

### 0.3 伦理声明模板

**版本A — 已获IRB批准：**
> 本研究已获[机构名称]机构伦理审查委员会批准（IRB编号：[XXX]，批准日期：[YYYY-MM-DD]）。鉴于研究的回顾性性质及对受试者风险极低，经委员会审核豁免知情同意要求。

**版本B — IRB豁免：**
> 本研究利用已脱敏的历史诊疗数据进行，根据[国家/地区]相关法规，该类型研究可豁免伦理审查。研究者无法识别任何个体患者身份。

**版本C — 临床试验注册（如适用）：**
> 本研究已在ClinicalTrials.gov注册（NCT[XXXXXXXX]），注册日期：[YYYY-MM-DD]。

### 0.4 初始数据评估报告

AI生成`init_data_assessment.md`，包含：
- 数据来源描述（时间范围、机构、数据库类型）
- 变量候选列表（按结局/暴露/混杂分类）
- 关键定义问题清单（需用户确认）
- 伦理/注册状态记录
- 数据访问计划选项（附优缺点）

### 0.5 Gate — 用户确认

**AI输出：** `pipeline_state.json`（初始状态）
```json
{
  "stage": 0,
  "project_name": "[用户输入的研究主题]",
  "data_sources": ["..."],
  "ethics_status": "approved|pending|exemption|none",
  "trial_registration": "NCTXXXXXXXX | null",
  "data_plan_confirmed": false,
  "variables": {
    "outcome": null,
    "exposure": null,
    "confounders": [],
    "effect_modifiers": []
  },
  "analyses_performed": [],
  "figures_generated": [],
  "paper_draft": "",
  "references": [],
  "final_output": null,
  "revision_round": 0
}
```

**Gate条件：** 用户确认数据访问计划 + 变量定义 + 伦理状态后，设置`data_plan_confirmed: true` → 进入Stage 1。

---

## Stage 1 · 数据清洗与统计分析

**触发：** `pipeline_state.json`中`data_plan_confirmed: true`

### 1.1 数据清洗

**依据：** 数据清洗是初始数据分析（Initial Data Analysis, IDA）的核心组成部分，应清晰报告所有清洗决策及其对后续分析的影响。[BMC Medical Research Methodology — Hübner et al., 2020](https://bmcmedresmethodol.biomedcentral.com/articles/10.1186/s12874-020-00942-y)

**依据：** STROBE Item 12（统计方法）要求报告所有可能影响混杂的决策；Item 12c要求专门描述缺失数据处理策略。

**AI动作：**

1. **不可能值检测**
   - 识别超出生理/逻辑范围的值（如：年龄<0或>120岁、心率>300次/分、血压舒张压>收缩压）
   - 记录异常值数量和处置方式（修正/标记为缺失/排除）

2. **单位标准化**
   - 统一所有计量单位（如血糖统一为mmol/L，肌酐统一为μmol/L或mg/dL）
   - 记录单位转换公式

3. **缺失机制评估**
   - 评估缺失类型：MCAR（完全随机缺失）/ MAR（随机缺失）/ MNAR（非随机缺失）
   - 报告各变量缺失比例（%）
   - 依据：应完整报告缺失情况，包括单位缺失（flow chart）和条目缺失（表格）。[BMC Med Res Methodol — 缺失数据报告指南](https://bmcmedresmethodol.biomedcentral.com/articles/10.1186/s12874-015-0022-1)

4. **缺失数据处理**
   - **首选策略**：完整病例分析（complete case analysis），需在文中说明并报告缺失率
   - **备选策略**：多重插补（MICE），仅在MCAR/MAR假设合理且缺失比例较高（>5-10%）时推荐
   - MICE实施规范：
     - 报告插补次数（通常5-20次）
     - 报告纳入插补模型的变量（含结局和辅助变量）
     - 按Rubin规则合并结果
     - 报告诊断结果（收敛性检验、缺失数据分布对比）
     - 参考文献：[BMC Med Res Methodol — MICE最佳实践](https://bmcmedresmethodol.biomedcentral.com/articles/10.1186/s12874-017-0442-1) + [MI报告清单](https://martin-vasilev.github.io/papers/Best_practices_multiple_imputation.pdf)

5. **离群值处理**
   - 报告识别方法（如IQR法、Z-score法）
   - 记录处置决策（缩尾/剔除/保留+敏感性分析）并附理由
   - 若保留离群值，须进行敏感性分析

6. **派生变量计算**
   - 在所有清洗完成后计算派生变量
   - 记录计算公式（如：APACHE II评分、GCS评分、ISS评分）
   - 记录任何使用派生变量截断值的决策及依据

7. **文档记录**
   - 所有清洗决策实时写入`data_cleaning_log.md`
   - 格式：`[时间戳] 变量名 | 问题描述 | 处置决策 | 依据`

### 1.2 患者流程图

**依据：** STROBE Item 13明确要求观察性研究提供参与者流程图，含纳排标准和最终分析样本量。[STROBE声明 v4](https://strobe-statement.org/fileadmin/Strobe/uploads/checklists/STROBE_checklist_v4_cohort.pdf)

**AI动作：**
- 生成标准化流程图（STROBE style），需包含：
  - 初始数据集大小
  - 每步排除标准 + 排除数量 + 排除原因
  - 失访/数据缺失情况
  - 最终分析样本量
- 输出：`figures/flow_chart.png`（双版本：彩色提交版 + 灰度打印版）

### 1.3 统计分析

#### 1.3.1 描述性统计

**依据：** STROBE Item 14要求报告各组参与者的描述性特征。

**规则：**
- 连续变量：正态分布用mean±SD，非正态用median(IQR)； Shapiro-Wilk检验评估正态性
- 分类变量：n(%)
- 基线特征表（Table 1）：总体 + 分组，**必须包含p值和标准化均数差（SMD）**
  - SMD<0.1视为组间平衡良好（倾向性评分匹配后的评估标准）
- 输出：`statistical_results.md`（APA格式）+ Table 1数据

#### 1.3.2 组间比较

**依据：** STROBE Item 14a涉及主要分析方法。

| 数据类型 | 方法 | 条件 |
|----------|------|------|
| 连续 vs 分组 | 独立样本t检验 / Mann-Whitney U检验 | t检验要求正态+方差齐性 |
| 分类 vs 分组 | χ²检验 / Fisher精确检验 | 期望频数<5时用Fisher |
| 配对数据 | 配对t检验 / Wilcoxon符号秩检验 | — |

#### 1.3.3 生存分析（如适用）

**依据：** STROBE Item 17要求生存分析报告：生存曲线构建方法、组间比较、HR+95%CI、Cox回归的 proportionality assumption验证。

**规则：**
- Kaplan-Meier生存曲线 + log-rank检验
- Cox比例风险回归：HR + 95%CI，报告所有纳入的协变量
- 验证比例风险假设（Schoenfeld残差检验）
- 若假设不成立：报告时变HR或采用分层Cox模型

#### 1.3.4 回归分析

**依据：** STROBE Item 14b要求报告多变量分析方法；Item 12要求说明变量选择策略和建模决策。

**规则：**
- **Logistic回归**（二分类结局）：OR + 95%CI
  - 单变量筛选：P<0.10的变量纳入多变量模型
  - 临床相关变量（如年龄、性别）无论P值均保留
  - 报告所有协变量，避免过度拟合（事件数/参数比≥10为参考标准）
- **Cox回归**（生存结局）：HR + 95%CI，同上策略
- 报告模型拟合优度（AUC/C-index，Hosmer-Lemeshow辅助报告）

#### 1.3.5 预测模型评估（如适用）

**依据：** ROC/AUC分析对应STROBE Item 16（判别能力）；**Hosmer-Lemeshow检验因任意分组和样本量依赖，不应作为校准度的主要指标**，而应报告校准斜率、校准-in-the-large和观测/期望比（带95%CI）。[BMJ — 预测模型验证指南2024](https://www.bmj.com/content/384/bmj-2023-074820)

**规则：**
- 判别能力：AUC + 95%CI（DeLong法）
- 校准：**校准图**（observed vs. predicted概率，按风险十分位）**优先于Hosmer-Lemeshow检验**
- 报告校准斜率、校准-in-the-large、O/E比

#### 1.3.6 内部验证

**依据：** CHEST统计报告指南强调过度拟合校正的重要性，推荐bootstrap重采样进行内部验证。[CHEST统计指南](https://www.sciencedirect.com/science/article/abs/pii/S0012369220304505)

**规则（预测模型）：**
- Bootstrap重采样：1000或10000次， optimism-corrected C-index
- 报告bootstrap校正后C-index（95%CI）
- 报告校准曲线（bootstrap平均曲线）

#### 1.3.7 敏感性分析

**依据：** STROBE Item 12d要求报告敏感性分析以评估结论稳健性。

**规则：**
- 至少一项敏感性分析（完整病例 vs. 插补数据；替代模型设定；极端情景分析）
- 记录每次敏感性分析的假设和结果

#### 1.3.8 亚组分析

**依据：** STROBE Item 12b要求：亚组分析须预先定义，明确报告交互作用检验方法（加法尺度 vs 乘法尺度）。[STROBE Item 12 Explanation](https://bookdown.org/melinkaksharp/STROBE_eduexpansion/methods-statistical-methods-12.html)

**规则：**
- 预先定义的亚组在Methods中明确说明
- 数据驱动的亚组须标注为"post-hoc"
- 报告交互作用P值
- 若效应修饰成立，同时报告各亚组分别的效应量

### 1.4 图表生成

**依据：** STROBE Item 13（流程图）、Item 14（描述性图表）、Item 16（判别/校准）、Item 17（生存曲线）。

**图表规范（通用）：**
- **配色**：Okabe-Ito色盲友好配色（Blue #0072B2、Orange #E69F00、Teal #009E73、Rose #CC79A7）
- **字体**：Arial Bold，图表标题12pt、坐标轴标签10pt、图例9pt、面板标签(A/B/C) 12pt Bold
- **分辨率**：TIFF @ 300dpi（投稿用）+ SVG（可编辑备份）
- **尺寸**：半幅8.5cm / 全幅17cm（自动适配期刊要求）
- **网格线**：统一 `axisbelow=True`，网格线0.5pt灰色
- **双版本输出**：彩色版（提交）+ 灰度版（打印审稿）

**图表类型对应：**
| 图表类型 | 适用分析 | 对应STROBE |
|----------|----------|------------|
| 患者流程图 | STROBE Item 13 | Item 13 |
| Kaplan-Meier生存曲线 | 预后分析，含risk table | Item 17 |
| Forest plot | 亚组分析、OR/HR 95%CI | Item 16 |
| ROC曲线 | 诊断/预测效能，AUC | Item 16 |
| 校准曲线 | 模型校准度 | Item 16 |
| 热力图 | 相关矩阵、危险因素分布 | Item 14 |
| 箱线图 | 组间比较 | Item 14 |

### 1.5 统计方法段落生成

**AI动作：** 根据Stage 1实际执行的各项分析，自动生成统计方法段落（见`stat_methods_paragraph.md`），匹配模板规则（详见`tools/stat_methods_templates.py`）。

**段落结构（参考STROBE Item 4、12）：**
1. 研究设计与机构（含日期范围）
2. 结局、暴露、混杂变量定义
3. 数据来源
4. 样本量论证（回顾性研究：全部可用数据，连续入组）
5. 各分析方法（描述→单变量→多变量→敏感性/亚组→验证）
6. 软件与版本

### 1.6 输出文件清单

| 文件 | 内容 |
|------|------|
| `data_cleaning_log.md` | 所有数据清洗决策，含时间戳 |
| `statistical_results.md` | 完整统计结果，APA格式 |
| `stat_methods_paragraph.md` | 自动生成的统计方法段落 |
| `figures/flow_chart.png` + `.svg` | 患者流程图 |
| `figures/fig_1.png` + `.svg` | 首个分析图表 |
| `figures/fig_2.png` + `.svg` | 第二个分析图表（如有） |
| `pipeline_state.json` | 更新`analyses_performed`、`figures_generated`、`stat_methods_paragraph` |

### 1.7 Gate — 用户确认

**AI输出：** 展示所有图表 + 统计结果摘要
**Gate条件：** 用户确认图表、统计方法、结果解读后 → 进入Stage 2

---

## Stage 0-1 错误处理

| 错误场景 | 处理策略 |
|----------|----------|
| Python脚本运行失败 | 报告错误信息 → 提供修正参数建议 → 重新运行 |
| API查询失败（PubMed等） | 降级到备用API → 若均失败则标记`[NEEDS_REVIEW]` |
| 用户中断会话 | 写入`pipeline_state.json`当前状态 → 下次启动时读取并从断点恢复 |
| 数据量异常（如<30例） | 警示用户样本量问题，建议在Discussion中增加局限性说明 |

---

## pipeline_state.json 状态转换

```
Stage 0 (未确认) → [data_plan_confirmed: true] → Stage 1
Stage 1 (未确认) → [用户确认图表和结果]       → Stage 2
Stage 2 (未确认) → [用户确认论文草稿]          → Stage 3
Stage 3 (未确认) → [用户确认参考文献]          → Stage 4
Stage 4 (未确认) → [用户确认投稿包]            → 完成 或 Stage 5
Stage 5 (审稿)   → [用户确认修回回复]          → 可再次进入Stage 5（多轮）
```

---

*文献依据：STROBE声明 v4 (strobe-statement.org) | ICMJE推荐 (icmje.org) | BMC Medical Research Methodology (bmcmedresmethodol.biomedcentral.com) | BMJ预测模型验证指南2024 (bmj.com) | CHEST统计报告指南 (sciencedirect.com) | ClinicalTrials.gov FDAAA 801 (clinicaltrials.gov) | NIH Grants Policy (grants.nih.gov)*
