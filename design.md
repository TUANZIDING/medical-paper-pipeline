---
name: medical-paper-pipeline-design
description: 医学科研论文全流程自动化skill设计文档
type: project
created: 2026-03-31
owner: dinghaixiang
---

# Medical Paper Pipeline - Skill Design

## 1. Overview

A comprehensive Claude Code skill that automates the full pipeline from medical research data analysis to SCI-ready manuscript submission. Target user: trauma surgeon performing retrospective clinical and epidemiological data analysis.

**Core principle:** A single skill orchestrating the entire pipeline through staged human-confirmation checkpoints, with automated DOI verification, SCI-grade figures, and multi-journal format adaptation.

## 2. Architecture

### Directory Structure

```
~/.claude/skills/medical-paper-pipeline/
├── SKILL.md                          # 主skill：流程编排 + 各阶段指令
├── tools/
│   ├── doi_verifier.py               # DOI校验 + PubMed查证
│   ├── figure_generator.py           # 图表生成工具链
│   ├── journal_formatter.py          # 期刊格式适配器
│   ├── paper_writer.py              # 结构化论文生成
│   ├── stat_methods_templates.py    # Statistical methods模板库
│   ├── response_letter_generator.py  # 审稿意见逐条回复生成
│   ├── revision_tracker.py           # 修回轮次追踪
│   └── tracked_change_generator.py   # 修订版稿件追踪修订
└── templates/
    ├── journal_specs.json             # 多期刊格式配置
    └── stat_template_rules.json      # stat methods段落模板规则
```

### State Management

Pipeline state stored in `pipeline_state.json` at the project directory (user's working directory). Each stage reads from and writes to this file. Stage transitions are gated by user confirmation.

## 3. Workflow Stages

### Stage 0 · Project Init & Data Assessment

**Trigger:** User provides research topic + data source description

**AI Actions:**
1. Parse user description, classify data types: SQL (HIS/database), Excel, CSV, SPSS output, or mixed
2. Generate 1-3 specific data access plans
3. List confirmation questions: variable definitions, outcome definitions, grouping criteria
4. **Ask about IRB/ethics status**: approved / pending / need to apply / exemption
5. **Ask about clinical trial registration**: NCT number if applicable
6. Write plan to `pipeline_state.json`

**Ethics/Registration Templates:**
```json
{
  "ethics_statement": "This study was approved by the Institutional Review Board of [Institution Name] (IRB No. [XXX]). The requirement for informed consent was waived due to the retrospective nature of the study and minimal risk to participants.",
  "trial_registration": "This study was registered at ClinicalTrials.gov (NCTXXXXXXX) on [date].",
  "no_registration": "This was a retrospective observational study; trial registration was not required."
}
```

**Gate:** User confirms data plan + ethics status → write `data_plan_confirmed: true` → proceed

---

### Stage 1 · Data Cleaning & Statistical Analysis

**Data Cleaning Standards (per BMC Medical Research Methodology & JMIR):**
1. **Impossible value detection**: flag values outside physiologic/logical range (e.g., negative age, pulse >300)
2. **Unit standardization**: unify all units before analysis (e.g., all glucose → mmol/L)
3. **Missingness mechanism assessment**: characterize MCAR/MAR/MNAR pattern, report missing % per variable
4. **Outlier handling**: report winsorization or exclusion decisions with rationale
5. **Derived variable computation**: compute after cleaning, re-derive whenever source fields change
6. **Documentation**: record every cleaning decision in `data_cleaning_log.md`

**Bootstrap & Internal Validation:**
- Generate calibration plot: predicted vs. observed probability across risk deciles
- Hosmer-Lemeshow test: report χ² and p-value
- Bootstrap: 1,000 or 10,000 resamples, optimism-corrected C-index

**Outputs:**
- `figures/flow_chart.png` + SVG: Patient flow diagram (STROBE Item 13, required)
- `figures/fig_1.png` + SVG: First figure (numbered sequentially)
- `statistical_results.md`: all test results in APA format
- `stat_methods_paragraph.md`: auto-generated methods text
- `data_cleaning_log.md`: all data cleaning decisions
- `pipeline_state.json` updated

**Table Structure Standard (retrospective cohort):**
| Table | Content | Format |
|-------|---------|--------|
| Table 1 | Baseline characteristics: continuous (mean±SD or median[IQR]), categorical (n[%]); overall + by group | Include p-value + standardized mean difference (SMD) |
| Table 2 | Univariate analysis results: variables vs outcome (OR/crude HR + 95%CI, p-value) | Sort by p-value or clinical importance |
| Table 3 / Figure | Multivariate results: adjusted OR/HR + 95%CI + p-value | Forest plot preferred over plain table |

**Gate:** User reviews figures + statistics → confirm → proceed

---

### Stage 2 · Structured Paper Draft

**AI Actions:**
1. Generate IMRaD structure: Background / Methods / Results / Discussion
2. Insert figure reference markers (Figure 1, Table 1...)
3. Auto-generate Figure legends for each figure
4. Inject statistical methods paragraph from Stage 1

**Gate:** User reviews structure, logic, figure placement → confirm → proceed

---

### Stage 3 · Reference Generation & DOI Verification

**AI Actions:**
1. Extract all citations from paper draft
2. For each reference:
   - Query PubMed E-utilities API with DOI
   - Verify: DOI → PMID → title/authors/year journal match
   - If mismatch: auto-search correct version + flag `[NEEDS_REVIEW]`
3. Output verification report

**Output:** `reference_verification_report.md`
- PASS: green checkmark
- FIXED: auto-corrected with explanation
- NEEDS_REVIEW: flagged for manual check

**Gate:** User confirms reference accuracy → proceed

---

### Stage 4 · Journal Adaptation & Submission Package

**Trigger:** User specifies target journal (or AI recommends based on topic/stats)

**AI Actions:**
1. Load `journal_specs.json` for target journal formatting rules
2. Apply citation style (Vancouver/AMA/ICMJE)
3. Adjust figures: resolution, dimensions per journal guidelines
4. Generate cover letter (auto-drafted from paper content)
5. Package outputs

**Outputs:**
- `manuscript_formatted.docx`: Full paper with journal formatting
- `figures/` (re-exported at journal specs)
- `references_formatted.txt`: Properly formatted reference list
- `cover_letter.docx`: Auto-generated cover letter
- `submission_checklist.md`: Journal-specific submission checklist

## 4. Figure Specifications

### Color Scheme (Okabe-Ito colorblind-friendly)

| Color | Hex | Use |
|-------|-----|-----|
| Blue | #0072B2 | Primary group |
| Orange | #E69F00 | Secondary group |
| Teal | #009E73 | Tertiary group |
| Rose | #CC79A7 | Fourth group |
| Sky Blue | #56B4E9 | Highlights |
| Coral | #D55E00 | Emphasis/warning |
| Black | #000000 | Text/borders |

All figures auto-generate two versions: **color (submission)** + **grayscale (print review)**.

### Typography

| Element | Font | Size |
|---------|------|------|
| Figure title | Arial Bold | 12pt |
| Axis labels | Arial | 10pt |
| Legend text | Arial | 9pt |
| Panel labels (A/B/C) | Arial Bold | 12pt |

### Figure Types by Analysis

| Figure Type | Analysis Context | Tool | STROBE Ref |
|------------|-----------------|------|-----------|
| Patient flow chart | STROBE Item 13: participant flow | Python matplotlib | Item 13 |
| Kaplan-Meier survival curve | Prognosis, log-rank test, risk table | Python lifelines | Item 17 |
| Forest plot | Subgroup analysis, OR/HR with 95%CI | Python matplotlib | Item 16 |
| ROC curve | Diagnostic/prediction efficacy, AUC, DeLong CI | Python sklearn | Item 16 |
| Calibration plot | Model calibration, Hosmer-Lemeshow test | Python matplotlib | Item 16 |
| Nomogram | Prognostic model visualization | Python matplotlib (manual) | Item 16 |
| Heatmap | Correlation matrix, risk factor heatmap | Python seaborn | Item 14 |
| Stacked bar chart | Epidemiological trend distribution | Python matplotlib | Item 14 |
| Box plot | Group comparisons | Python seaborn | Item 14 |
| Sankey diagram | Patient flow / treatment pathways (optional) | Python plotly | Item 13 |

### Export Specs

- Format: **TIFF @ 300dpi** (submission) + **SVG** (editable backup)
- Dimensions: **Half-width 8.5cm** or **full-width 17cm** (auto-adapted for journal)
- Border:统一 `axisbelow=True`，网格线 `0.5pt gray`

## 5. Statistical Methods Template System

### Template Matching Rules

Templates auto-match based on analyses performed in Stage 1. **STROBE compliance is mandatory** — every retrospective study submitted to SCI journals must address all applicable STROBE items:

| Analysis Type | Template Key | STROBE Item | Notes |
|--------------|-------------|-------------|-------|
| Study design | `study_design` | Item 4 | Retrospective cohort, case-control, or cross-sectional |
| Setting & participants | `setting` | Item 5-6 | Dates, location, eligibility, selection |
| Variables defined | `variables` | Item 7 | Outcome, exposure, confounders, effect modifiers |
| Bias control | `bias_control` | Item 9 | Selection bias, information bias mitigation |
| Sample size | `sample_size` | Item 10 | Justification (all available data / registry / consecutive enrollment) |
| Variable handling | `variable_handling` | Item 11 | Continuous vars: kept continuous or categorized; cutoff rationale |
| Descriptive stats | `descriptive` | Item 14 | mean±SD or median(IQR); n(%) |
| t-test | `t_test` | Item 14a | |
| Chi-square/Fisher | `chi_square` | Item 14a | |
| Kaplan-Meier | `survival` | Item 17 | |
| Cox regression | `survival` + `multivariate_adjustment` | Item 17 | HR + 95%CI |
| Logistic regression | `logistic_regression` | Item 14b | OR + 95%CI, univariate → multivariate |
| Correlation | `correlation` | Item 14a | |
| ROC / AUC | `roc_analysis` | Item 16 | Discrimination + AUC value + DeLong CI |
| Calibration plot | `calibration` | Item 16 | Hosmer-Lemeshow, calibration curve |
| Sensitivity analysis | `sensitivity_analysis` | Item 12d | Complete case / multiple imputation / alternative model |
| Missing data | `missing_data` | Item 12c | |
| Software | `software` | Item 12 | Python version + packages

### Template Rules JSON

```json
{
  "study_design": "This retrospective cohort study was conducted at [institution] between [start date] and [end date]. All consecutive patients meeting the following inclusion criteria were identified from [hospital database/registry name]: [list criteria]. Patients with [exclusion criteria] were excluded.",
  "setting": "Data were collected from [hospital name] trauma registry / HIS database / [data source]. The study period was [date range]. Follow-up data were obtained from [source].",
  "variables": "The primary outcome was [definition]. Exposure variables included [list]. Potential confounders identified a priori based on clinical relevance included age, sex, and [injury severity score/comorbidity index/other clinically relevant covariates]. Effect modifiers were assessed through subgroup analysis.",
  "bias_control": "To minimize selection bias, consecutive patients meeting the inclusion criteria were enrolled. To address confounding, multivariate regression adjusting for clinically relevant covariates was performed. Information bias was reduced by [blinding outcome assessors / using standardized definitions / data quality checks].",
  "sample_size": "The sample size was determined by the number of consecutive eligible patients during the study period. All patients meeting the inclusion criteria were included, representing the entire eligible population. No sample size calculation was performed as this was a retrospective analysis of available data.",
  "variable_handling": "Continuous variables were analyzed as presented or categorized based on clinical cutoffs. The choice of cutoff points for categorical variables was based on [clinical significance / median values / previously established thresholds / WHO guidelines].",
  "descriptive": "Continuous variables were presented as mean ± SD or median (IQR) as appropriate. Normality was assessed using the Shapiro-Wilk test. Categorical variables were expressed as n (%).",
  "t_test": "Between-group comparisons of continuous variables were performed using independent samples t-test (for normally distributed data) or Mann-Whitney U test (for non-normally distributed data). A two-sided P < 0.05 was considered statistically significant.",
  "chi_square": "Categorical variables were compared using χ² test or Fisher's exact test when expected cell counts were < 5.",
  "survival": "Survival curves were constructed using the Kaplan-Meier method, and between-group differences were assessed with the log-rank test. Hazard ratios (HR) with 95% confidence intervals (CI) were calculated using Cox proportional hazards regression. The proportionality assumption was verified using Schoenfeld residuals.",
  "logistic_regression": "Univariate logistic regression was initially performed to screen potential predictors. Variables with P < 0.10 in univariate analysis were included in multivariate logistic regression to identify independent risk factors. Results are presented as odds ratios (OR) with 95% CI.",
  "correlation": "Correlation between continuous variables was assessed using Pearson's r or Spearman's rho depending on data distribution (assessed by Shapiro-Wilk test).",
  "roc_analysis": "The discriminative ability of the prediction model was assessed using receiver operating characteristic (ROC) curve analysis. The area under the ROC curve (AUC) with 95% CI was calculated. Pairwise AUC comparisons were performed using the DeLong test.",
  "calibration": "Model calibration was evaluated using the Hosmer-Lemeshow goodness-of-fit test and calibration plots showing observed versus predicted probabilities across risk deciles.",
  "internal_validation": "Internal validation was performed using bootstrap resampling with [1,000/10,000] iterations to obtain optimism-corrected performance estimates. The bootstrap-corrected C-index was [X.XXX] (95% CI [X.XXX–X.XXX]).",
  "propensity_matching": "To control for confounding, 1:1 nearest-neighbor propensity score matching was performed using [caliper width, e.g., 0.2 SD of the logit]. Covariates included in the propensity model were [list]. Matching quality was assessed by standardized mean differences (<0.1 considered adequate balance).",
  "multiple_imputation": "Multiple imputation by chained equations (MICE) was used to handle missing data, with [N] imputations performed. Variables included in the imputation model were all predictors, outcome, and auxiliary variables related to missingness. Results were pooled according to Rubin's rules.",
  "multivariate_adjustment": "Multivariate analysis was adjusted for clinically relevant covariates including age, sex, and injury severity score (ISS). All clinically relevant variables were retained in the final model regardless of statistical significance to avoid overfitting.",
  "sensitivity_analysis": "Sensitivity analyses were performed to assess the robustness of our findings: (1) complete case analysis excluding patients with missing data; (2) [alternative model specification / multiple imputation for missing data / subgroup analysis by injury severity].",
  "missing_data": "Missing data were handled using complete case analysis. The proportion of missing values for each variable was reported in Table 1. [If multiple imputation used: Multiple imputation with 5 iterations was performed using the chained equations method, and results were pooled according to Rubin's rules.]",
  "software": "All statistical analyses were performed using Python (dynamically detected version) with scipy, statsmodels, and lifelines packages. Figures were generated using matplotlib and seaborn. A two-sided P < 0.05 was considered statistically significant."
}
```

### Cover Letter Template

Auto-generated based on: paper title, journal name, key finding (1 sentence), novelty statement, and author declaration.

Cover letter structure:
```
[Date]

Dear Editor,

Paragraph 1: Submission statement — "We would like to submit [title] for consideration as an original research article in [Journal Name]."

Paragraph 2: Key finding — 1-2 sentences highlighting main result and clinical significance.

Paragraph 3: Why this journal — alignment with journal scope, readership, and mission.

Paragraph 4: Novelty/contribution — what this study adds to existing literature.

Paragraph 5: Administrative statement:
  - "This manuscript has not been published elsewhere and is not under consideration."
  - "All authors have approved the submission and declare no conflict of interest."
  - [Ethics approval statement]
  - [Trial registration number if applicable]

Corresponding author:
  Name: [User to provide]
  Institution: [User to provide]
  Email: [User to provide]
  Phone: [User to provide]

Sincerely,
[Corresponding author name]
```

### Resume & Recovery Strategy

**Session interruption:** If a session ends mid-pipeline, the next invocation should:
1. Read `pipeline_state.json` from the project directory
2. Report current stage and what needs confirmation
3. Offer to resume from the last unconfirmed checkpoint

**Stage failure handling:**
- Stage 1 (analysis): If Python script fails → report error → offer retry with adjusted parameters
- Stage 3 (DOI verification): If API fails → fall back to CrossRef → if that fails too → flag as `[NEEDS_REVIEW]` automatically
- Stage 4 (formatting): If .docx generation fails → generate markdown fallback → notify user

**State file contract:**
```json
{
  "stage": 0,
  "project_name": "...",
  "data_sources": [],
  "data_plan_confirmed": false,
  "data_plan": "...",
  "analyses_performed": [],
  "figures_generated": [],
  "figure_legend": {},
  "stat_methods_paragraph": "",
  "paper_draft": "",
  "paper_confirmed": false,
  "references": [],
  "doi_verification_report": [],
  "references_confirmed": false,
  "target_journal": null,
  "final_output": null
}
```

## 6. Journal Format Configuration

### Supported Journals (Initial Set)

| Journal | Citation Style | Notes |
|---------|--------------|-------|
| Injury | Vancouver | Trauma/orthopaedics |
| Journal of Orthopaedic Trauma (JOT) | Vancouver | Orthopaedic trauma |
| The Journal of Trauma and Acute Care Surgery | Vancouver | Trauma surgery |
| Injury Epidemiology | Vancouver | Epidemiology focus |
| World Journal of Surgery | Vancouver | General surgery |
| BMJ | Vancouver | High-impact, very specific guidelines |
| The Lancet | Lancet style | Highly specific, separate config |
| New England Journal of Medicine | AMA | Highest impact |

### Format Parameters Per Journal

```json
{
  "citation_style": "Vancouver|AMA|ICMJE|Lancet",
  "figure_width": {"half": 8.5, "full": 17.0},
  "font": "Arial|Times New Roman",
  "line_spacing": 1.0|1.5|2.0,
  "reference_format": {...},
  "abstract_limit": 250|300|350,
  "keyword_count": 4|5|6
}
```

## 7. Tools Design

### doi_verifier.py

- Input: list of DOIs or reference strings
- Output: verification report + corrected references
- PubMed API: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
- Fallback: CrossRef API if PubMed fails
- Rate limiting: 3 req/sec (PubMed limit)

### figure_generator.py

- Input: analysis results + figure type + style config
- Output: TIFF 300dpi + SVG files
- Tool chain: matplotlib + seaborn + lifelines + plotly
- Auto dual-output: color + grayscale

### journal_formatter.py

- Input: draft text + target journal ID
- Output: formatted .docx file
- Library: python-docx for .docx generation

### paper_writer.py

- Input: Stage 1 statistical results + Stage 2 paper draft markdown + Stage 3 verified references
- Output: structured IMRaD markdown with figure legends and injected statistical methods
- Includes statistical methods injection from templates

## 8. Implementation Priority

1. **SKILL.md** - Full pipeline orchestration
2. **tools/stat_methods_templates.py** + **templates/stat_template_rules.json** - Template system
3. **tools/figure_generator.py** - Figure generation (highest complexity)
4. **tools/doi_verifier.py** - Reference verification
5. **tools/journal_formatter.py** - Journal adaptation
6. **templates/journal_specs.json** - Journal configuration
7. **tools/paper_writer.py** - Paper generation
8. **tools/response_letter_generator.py** - Peer review response letter
9. **tools/revision_tracker.py** - Revision round tracking
10. **tools/tracked_change_generator.py** - Tracked changes manuscript

## 9. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Single skill, not multi-skill | User wants a complete workflow, not 4 independent tools |
| JSON state file for pipeline | Allows interruption/resume, human checkpoints between stages |
| Python tool scripts, not inline code | Complex computations (stats, plotting, API calls) better in .py |
| Dual color/grayscale figures | Trauma journals vary in print quality, both needed |
| PubMed first, CrossRef fallback | PubMed has best medical article metadata |
| Cover letter at stage 4 | Full paper content finalized only after all stages confirmed |

## 10. Verification Checklist

**STROBE Compliance:**
- [ ] Patient flow chart generated (STROBE Item 13)
- [ ] Sample size justification included in Methods (STROBE Item 10)
- [ ] All confounders and effect modifiers defined (STROBE Item 7)
- [ ] Bias control strategy described (STROBE Item 9)
- [ ] Variable handling (continuous/categorical) explained (STROBE Item 11)
- [ ] Sensitivity analysis described (STROBE Item 12d)
- [ ] Missing data handling described (STROBE Item 12c)

**Core Requirements:**
- [ ] DOI verification catches at least 95% of invalid/mismatched references (PubMed + CrossRef fallback)
- [ ] Figures meet 300dpi TIFF submission standard (color + grayscale dual output)
- [ ] Statistical methods text matches exactly what was performed (template auto-match from analyses)
- [ ] Journal format applies correctly (citation style, dimensions, font, abstract limit)
- [ ] All stage transitions require explicit human confirmation
- [ ] Pipeline state persists across sessions via `pipeline_state.json`
- [ ] Session resume: AI reads state file and reports last checkpoint
- [ ] Stage failure: graceful degradation with fallback + user notification
- [ ] Cover letter auto-generated at Stage 4 from finalized paper content
- [ ] Figure legends auto-generated with appropriate scientific detail
- [ ] Figure/table numbering is sequential and consistent throughout manuscript
- [ ] Table 1 includes p-value + standardized mean difference (SMD)
- [ ] ROC curve accompanied by calibration plot (for prediction models)
- [ ] Cover letter includes corresponding author details block (name, institution, email, phone)
- [ ] Administrative statements in cover letter: no simultaneous submission, all authors approved, no COI, ethics approval

---

### Stage 5 · Peer Review Response Letter & Revision

**Trigger:** User pastes reviewer comments (PDF/text) or provides the decision letter

**AI Actions:**
1. Parse and structure reviewer comments — extract each comment point, reviewer number, and decision type (major/minor)
2. Categorize each comment type:
   - **Statistical/Methodological** → route to re-analysis or stat methods clarification
   - **Writing/Clarity** → route to text revision
   - **Literature/Reference** → route to DOI verification or new citation
   - **Data/Results** → route to supplementary analysis or clarification
   - **Ethics/Compliance** → route to ethics statement revision
   - **Editorial** → route to format/adherence revision
3. For each comment: draft point-by-point response + indicate manuscript change
4. Flag "unrevisable" comments (reviewer asks for impossible things) — suggest diplomatic language
5. Generate revised manuscript sections with **tracked changes** (or "changes marked")
6. Update `pipeline_state.json` with revision round number and response status

**Response Letter Structure (per reviewer):**
```
Response to Reviewer #X

Comment #X.1: [verbatim or summarized reviewer comment]
Response: [Your response — acknowledge, defend, or agree to revise]
Change: [Manuscript location + exact change made, or "No change — rationale: ..."]

Comment #X.2: ...
```

**Revision Classification:**
| Type | Code | Strategy |
|------|------|----------|
| Major revision (accept with changes) | R1/R2 | Full tracked changes + detailed response |
| Minor revision | Minor | Targeted changes + concise response |
| Resubmission required | Resub | Address all points, re-run analyses if needed |
| Reject & resubmit | Resubmit | Major overhaul, may need new data/analysis |

**Handling Unrevisable Comments:**
- Request impossible data/experiment → "Thank you for this suggestion. Due to [limitation], we addressed this through [alternative approach] and have clarified this in the Discussion (Page X, Para Y)."
- Disagree politely → Present evidence, cite literature, explain methodology rationale
- Statistical disagreement → Show both analyses (original + suggested method) with honest comparison

**Outputs:**
- `response_letter_draft.md`: Full point-by-point response letter
- `revision_summary.md`: Table of all comments, responses, and changes made
- `manuscript_revised.docx`: Full paper with tracked changes
- `pipeline_state.json` updated with `revision_round: N`

**Gate:** User reviews response letter + revised manuscript → confirm → ready for resubmission

---

### Stage 5 Tools

#### response_letter_generator.py

- Input: reviewer comments (text/PDF parsed) + original manuscript + stage 1-4 outputs
- Output: structured response letter markdown + revision summary table
- Response tone: professional, collaborative, non-defensive (acknowledge → explain → revise or defend)
- Auto-detect comment type → route to appropriate revision strategy

#### revision_tracker.py

- Input: list of reviewer comments + revision decisions
- Output: structured JSON tracking each comment's status
- States: `pending` → `addressed` → `response_drafted` → `confirmed`
- Handles multiple revision rounds: R1, R2, R3...

#### tracked_change_generator.py

- Input: original manuscript + list of changes per section
- Output: .docx with inline tracked changes (using python-docx redlines)
- If python-docx redline unsupported: output two versions (original highlighted + revised clean)

---

### Stage 5 Response Letter Template Rules

| Comment Type | Response Strategy | Change Required? |
|---|---|---|
| Statistical methods clarification | Re-state method with more detail, cite STROBE/guideline | Yes → add clarification to Methods |
| Additional analysis requested | Perform if feasible; if not, explain limitation + alternative | If feasible → Stage 1 rerun; else → Discussion caveat |
| Reference/citation gap | DOI verify + add new reference | Yes → Stage 3 + inject citation |
| Writing/clarity | Rewrite affected paragraph | Yes → revised text |
| Sample size critique | Defend with registry/consecutive enrollment rationale | Possibly → Discussion revision |
| Comparison to prior literature | Add nuance to Discussion with new/updated citations | Yes → Discussion + references |
| Ethical concern | Immediate consultation recommended; strengthen ethics statement | Yes → Ethics section revision |
| Formatting/editorial | Apply journal-specific rules | Yes → Stage 4 rerun |

---

### State File Extension for Stage 5

```json
{
  "revision_round": 1,
  "decision_letter_date": "YYYY-MM-DD",
  "decision_type": "major_revision|minor_revision|reject_resubmit",
  "reviewer_count": 3,
  "reviewer_comments": [
    {
      "reviewer_id": 1,
      "comment_count": 5,
      "comments": [
        {
          "id": "R1-C1",
          "verbatim": "...",
          "type": "statistical|writing|reference|data|ethics|editorial",
          "status": "pending|addressed|response_drafted|confirmed",
          "response": "...",
          "manuscript_change": "...",
          "location": "Page X, Para Y"
        }
      ]
    }
  ],
  "response_letter_confirmed": false,
  "revision_complete": false,
  "resubmission_ready": false
}
```

---

### Stage 5 Verification Checklist

**Response Letter Quality:**
- [ ] Every reviewer comment has a corresponding response entry
- [ ] All changes mentioned in responses are reflected in the revised manuscript
- [ ] Response tone is professional — no defensive or dismissive language
- [ ] Unrevisable comments handled with diplomatic language + alternative approach
- [ ] Statistical disagreements include honest comparison of methods
- [ ] No new references added without DOI verification (Stage 3 workflow)

**Revision Accuracy:**
- [ ] Tracked changes version matches all response letter commitments
- [ ] If new analysis was added → statistical methods paragraph updated
- [ ] If new references added → reference list reformatted per journal style
- [ ] Page/line references in response letter are accurate to revised manuscript

**Multi-Round Handling:**
- [ ] Each revision round tracked separately in `pipeline_state.json`
- [ ] R1 responses attached when preparing R2 resubmission
- [ ] All reviewer comments from all rounds addressed in final response

---

### Decision Key: Major vs Minor Revision Response

**Major revision response letter:**
- Use full formal structure
- For each comment: acknowledgment + detailed explanation + exact change + cite supporting literature if relevant
- Anticipate follow-up questions — preemptively address related concerns

**Minor revision response letter:**
- Concise responses acceptable
- Focus on exact changes made — omit lengthy explanations
- Use abbreviated format where appropriate

**Strategic principles:**
- Never ignore a comment — even "minor language" feedback deserves acknowledgment
- Be honest about limitations — reviewers respect candor over overclaiming
- Show deference to reviewer expertise while defending sound methodology
- Use "we" not "I" — team effort, shared ownership