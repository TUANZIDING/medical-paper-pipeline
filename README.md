# Medical Paper Pipeline

> End-to-end automation for clinical research: from raw data to SCI-ready manuscript submission.

A comprehensive skill for Claude Code that automates the entire medical research paper pipeline — data cleaning, statistical analysis, manuscript generation, reference verification, journal formatting, and peer review response letters.

Built for trauma surgeons and clinical researchers conducting retrospective observational studies.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![STROBE](https://img.shields.io/badge/STROBE-Compliant-green.svg)](https://www.strobe-statement.org/)

## Features

### Six-Stage Pipeline with Human Checkpoints

| Stage | What It Does | Output Files |
|-------|-------------|-------------|
| **0 · Project Init** | Data source assessment, ethics evaluation, variable definition | `init_data_assessment.md`, `pipeline_state.json` |
| **1 · Data Cleaning & Stats** | Impossible value detection, missing data analysis, unit standardization, descriptive stats, regression | `data_cleaning_log.md`, `statistical_results.md`, `stat_methods_paragraph.md`, `figures/` |
| **2 · Paper Draft** | Structured IMRaD manuscript generation with figure legends | `manuscript_draft.md` |
| **3 · Reference Verification** | DOI validation via PubMed + CrossRef, metadata consistency checks | `reference_verification_report.md` |
| **4 · Journal Adaptation** | Citation style conversion, figure resizing, cover letter generation | `manuscript_formatted.docx`, `cover_letter.docx` |
| **5 · Peer Review Response** | Point-by-point reviewer response letters, revision tracking | `response_letter.md`, `revision_summary.md` |

### 8 Publication-Ready Figure Types

All figures use **Okabe-Ito colorblind-friendly** palette, exported in **TIFF @ 300dpi + SVG**, with **color + grayscale** dual versions.

| Figure Type | Statistical Context | STROBE Item |
|------------|-------------------|-------------|
| Patient Flow Chart | Participant enrollment & exclusion | Item 13 |
| Kaplan-Meier Survival Curves | Prognosis analysis with risk table | Item 17 |
| Forest Plot | Subgroup analysis, OR/HR with 95%CI | Item 16 |
| ROC Curve | Diagnostic/prediction efficacy, AUC | Item 16 |
| Calibration Plot | Model calibration (observed vs predicted) | Item 16 |
| Heatmap | Correlation matrix, risk factor distribution | Item 14 |
| Box Plot | Group comparisons | Item 14 |
| Stacked Bar Chart | Epidemiological trend distribution | Item 14 |

### Supported Journals (with verified specs from official guidelines)

| Journal | Citation Style | Abstract Limit | References |
|---------|---------------|---------------|------------|
| [Injury](https://www.sciencedirect.com/journal/injury/publish/guide-for-authors) | Vancouver | 350 words | ≤40 |
| [World J Surg](https://onlinelibrary.wiley.com/page/journal/14322323/homepage/author-guidelines) | Vancouver | 350 words | ≤60 |
| [BMJ](https://www.bmj.com/about-bmj/resources-authors) | Vancouver | 300 words | ≤50 |
| [JAMA](https://jamanetwork.com/journals/jama/pages/instructions-for-authors) | AMA | 350 words | ~50 |
| [The Lancet](https://www.thelancet.com/lancet/about/information-for-authors) | Lancet | 300 words | ≤50 |
| NEJM | NEJM | 350 words | Verify |
| JOT | Vancouver | 250 words | Verify |

> Journal specifications sourced from official author guidelines. `_verified: false` fields require manual confirmation against the latest guidelines before first submission.

## Quick Start

### Installation

Clone this repository and place it in your Claude Code skills directory:

```bash
git clone https://github.com/YOUR_USERNAME/medical-paper-pipeline.git
cp -r medical-paper-pipeline ~/.claude/skills/medical-paper-pipeline/
```

Or use it as a standalone toolkit — all tools are self-contained Python scripts.

### Usage

Invoke the skill in Claude Code:

```
/medical-paper-pipeline
```

Then describe your study:

> "I have an Excel file with 800 trauma patients. Columns: age, sex, blood pressure, heart rate, admission date, outcome (survived/died), ICU length of stay. Data is messy — missing values, mixed date formats, some impossible values. I want to identify predictors of in-hospital mortality."

The AI will guide you through each stage with confirmation checkpoints.

### As Standalone CLI Tools

Each tool in `tools/` works independently:

```bash
# Verify a list of DOIs
python tools/doi_verifier.py references.txt -o verification_report.md

# Generate a Kaplan-Meier plot
python tools/figure_generator.py --type kaplan_meier --input km_data.json --output-dir figures/

# Format manuscript for Injury journal
python tools/journal_formatter.py manuscript.md --journal injury -o formatted.docx

# Generate peer review response letter
python tools/response_letter_generator.py reviewer_comments.txt -o response_letter.md

# Track revisions across rounds
python tools/revision_tracker.py pipeline_state.json --summary

# Generate tracked-changes manuscript
python tools/tracked_change_generator.py original.md --changes changes.json -o revised/
```

## Architecture

```
medical-paper-pipeline/
├── SKILL.md                              # Pipeline orchestration & stage definitions
├── design.md                             # Complete design document
├── tools/
│   ├── doi_verifier.py                   # DOI validation via PubMed E-utilities + CrossRef
│   ├── figure_generator.py               # 8 figure types, Okabe-Ito colors, dual export
│   ├── paper_writer.py                   # IMRaD assembly + STROBE compliance check
│   ├── journal_formatter.py              # Vancouver/AMA/Lancet/NEJM formatting
│   ├── stat_methods_templates.py         # Auto-generate statistical methods paragraph
│   ├── response_letter_generator.py      # Point-by-point reviewer response letters
│   ├── revision_tracker.py               # Multi-round revision state machine
│   └── tracked_change_generator.py       # Manuscript with tracked changes
└── templates/
    ├── stat_template_rules.json          # Template rules for stat methods
    └── journal_specs.json                # 7 journal formatting specifications
```

### Key Design Principles

1. **Zero third-party dependencies** — All tools use Python standard library only (`urllib`, `json`, `re`, `xml.etree`)
2. **State persistence** — `pipeline_state.json` enables session interruption/resume
3. **Human-in-the-loop** — Every stage requires explicit user confirmation
4. **Graceful degradation** — API fallbacks at every step (PubMed → CrossRef → NEEDS_REVIEW)
5. **STROBE compliance** — Built-in checklists and coverage analysis

## STROBE Compliance

The pipeline addresses all applicable STROBE items for observational studies:

| STROBE Item | Coverage | Notes |
|-------------|----------|-------|
| Item 4 — Study Design | Automatic | Included in statistical methods |
| Item 5 — Setting | Semi-automatic | User confirms institution/location |
| Item 6 — Participants | Automatic | Flowchart generated from data |
| Item 7 — Variables | Semi-automatic | User confirms outcome/exposure definitions |
| Item 8 — Data Sources | Semi-automatic | User provides source description |
| Item 9 — Bias | Automatic | Addressed in statistical methods |
| Item 10 — Sample Size | Automatic | Consecutive enrollment rationale |
| Item 11 — Quantitative Variables | Automatic | Explained in methods |
| Item 12 — Statistical Methods | Automatic | Template-matched to analyses performed |
| Item 13 — Participants Flow | **Automatic** | Flowchart with exclusion criteria |
| Item 14 — Descriptive Data | **Automatic** | Table 1 with p-values + SMD |
| Item 15 — Main Results | **Automatic** | OR/HR + 95%CI for all analyses |
| Item 16 — Other Analyses | Semi-automatic | Sensitivity/subgroup if performed |
| Item 17 — Survival Data | Semi-automatic | KM curves + Cox regression if applicable |
| Item 19 — Funding | Semi-automatic | User provides funding statement |
| Item 22 — Conflicts | Semi-automatic | User provides conflict statement |

## Data Sources

All journal specifications sourced from:

- [Injury Guide for Authors](https://www.sciencedirect.com/journal/injury/publish/guide-for-authors) (Elsevier)
- [World Journal of Surgery Author Guidelines](https://onlinelibrary.wiley.com/page/journal/14322323/homepage/author-guidelines) (Wiley)
- [ICMJE Recommendations](http://www.icmje.org)
- [JAMA Instructions for Authors](https://jamanetwork.com/journals/jama/pages/instructions-for-authors) (AMA)
- [BMJ Author Resources](https://www.bmj.com/about-bmj/resources-authors) (BMJ Publishing Group)
- [The Lancet Information for Authors](https://www.thelancet.com/lancet/about/information-for-authors) (Elsevier)

## License

MIT License — see [LICENSE](LICENSE) file.

## Acknowledgments

- [STROBE Statement](https://www.strobe-statement.org/) for observational study reporting guidelines
- [ICMJE](https://www.icmje.org/) for uniform manuscript preparation recommendations
- [Okabe & Ito](https://jfly.uni-koeln.de/color/) for colorblind-friendly palette
- PubMed E-utilities ([NCBI](https://www.ncbi.nlm.nih.gov/books/NBK25501/)) for reference verification
- CrossRef API ([crossref.org](https://www.crossref.org/)) for fallback DOI resolution
