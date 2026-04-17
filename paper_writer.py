#!/usr/bin/env python3
"""
paper_writer.py
==============
Structured manuscript generator for the medical-paper-pipeline skill.

Combines Stage 1 statistical results + Stage 2 paper draft + Stage 3 verified
references into a complete IMRaD manuscript with:
  - Injected statistical methods paragraph (from stat_methods_templates)
  - Figure legends auto-generated
  - References with verified DOIs
  - STROBE compliance checklist

Usage (import as module):
    from paper_writer import PaperWriter
    writer = PaperWriter(
        stat_results="statistical_results.md",
        draft="manuscript_draft.md",
        verified_refs="reference_verification_report.md",
        stat_methods="stat_methods_paragraph.md",
    )
    writer.write(output="manuscript_final.md")

CLI usage:
    python paper_writer.py --draft draft.md --stat-results results.md \
        --refs refs.md --stat-methods methods.md -o manuscript.md
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ─── Section Structure ────────────────────────────────────────────────────────


@dataclass
class FigureRef:
    """Represents a figure reference within the manuscript."""

    number: int
    filename: str = ""
    caption: str = ""
    in_text: str = ""  # e.g. "(Fig. 1A)" or "Figure 1B"


@dataclass
class TableRef:
    """Represents a table reference within the manuscript."""

    number: int
    filename: str = ""
    title: str = ""
    in_text: str = ""  # e.g. "(Table 1)" or "Table 2"


@dataclass
class Section:
    """A manuscript section with title and content."""

    title: str
    content: str = ""
    subsections: list["Section"] = field(default_factory=list)
    level: int = 2  # 1=Heading1, 2=Heading2, 3=Heading3

    def render(self) -> str:
        """Render section as markdown."""
        parts = [f"{'#' * self.level} {self.title}", ""]
        if self.content:
            parts.append(self.content.strip())
        for sub in self.subsections:
            sub.level = self.level + 1
            parts.append(sub.render())
        return "\n".join(parts)


# ─── Manuscript Builder ───────────────────────────────────────────────────────


class ManuscriptBuilder:
    """
    Assembles a complete scientific manuscript from structured components.

    Takes:
      - Statistical results (APA format tables)
      - Draft manuscript sections
      - Verified reference list
      - Statistical methods paragraph
      - Figure list with legends
      - Table list

    Produces:
      - Complete IMRaD manuscript in markdown
      - Optional .docx export
      - STROBE compliance report
    """

    # Standard IMRaD sections in order
    DEFAULT_STRUCTURE = [
        "title",
        "abstract",
        "keywords",
        "highlights",
        "introduction",
        "methods",
        "results",
        "discussion",
        "conclusions",
        "references",
        "supplementary",
    ]

    def __init__(
        self,
        project_name: str = "Untitled Study",
        study_type: str = "retrospective cohort",
    ):
        self.project_name = project_name
        self.study_type = study_type
        self.sections: dict[str, Section] = {}
        self.figures: list[FigureRef] = []
        self.tables: list[TableRef] = []
        self._authors: list[str] = []
        self._affiliations: list[str] = []
        self._correspondence: dict[str, str] = {}
        self._keywords: list[str] = []
        self._funding: str = ""
        self._conflicts: str = ""
        self._acknowledgements: str = ""

    # ─── Metadata setters ───────────────────────────────────────────────────

    def set_authors(self, authors: list[str]) -> "ManuscriptBuilder":
        self._authors = authors
        return self

    def set_affiliations(self, affiliations: list[str]) -> "ManuscriptBuilder":
        self._affiliations = affiliations
        return self

    def set_correspondence(
        self, name: str, email: str, phone: str = ""
    ) -> "ManuscriptBuilder":
        self._correspondence = {"name": name, "email": email, "phone": phone}
        return self

    def set_keywords(self, keywords: list[str]) -> "ManuscriptBuilder":
        self._keywords = keywords
        return self

    def set_funding(self, text: str) -> "ManuscriptBuilder":
        self._funding = text
        return self

    def set_conflicts(self, text: str) -> "ManuscriptBuilder":
        self._conflicts = text
        return self

    def set_acknowledgements(self, text: str) -> "ManuscriptBuilder":
        self._acknowledgements = text
        return self

    def add_figure(self, figure: FigureRef) -> "ManuscriptBuilder":
        self.figures.append(figure)
        return self

    def add_table(self, table: TableRef) -> "ManuscriptBuilder":
        self.tables.append(table)
        return self

    # ─── Section setters ──────────────────────────────────────────────────

    def set_title(self, title: str) -> "ManuscriptBuilder":
        self.sections["title"] = Section(title=title, content="", level=1)
        return self

    def set_abstract(self, content: str) -> "ManuscriptBuilder":
        self.sections["abstract"] = Section(
            title="Abstract",
            content=self._wrap_abstract(content),
            level=2,
        )
        return self

    def set_section(self, name: str, title: str, content: str) -> "ManuscriptBuilder":
        self.sections[name] = Section(title=title, content=content, level=2)
        return self

    def set_methods(
        self,
        stat_methods: str,
        ethics_statement: str = "",
        trial_registration: str = "",
    ) -> "ManuscriptBuilder":
        """Build the Methods section from statistical methods + ethics."""
        parts = [stat_methods]
        if ethics_statement:
            parts.extend(["", "### Ethical Considerations", "", ethics_statement])
        if trial_registration:
            parts.extend(["", trial_registration])
        self.sections["methods"] = Section(
            title="Methods",
            content="\n\n".join(parts),
            level=2,
        )
        return self

    def set_results(
        self,
        stat_results: str,
        table1_md: str = "",
        table2_md: str = "",
        table3_md: str = "",
    ) -> "ManuscriptBuilder":
        """Build the Results section with embedded tables."""
        parts = []
        if stat_results:
            parts.append(stat_results)
        if table1_md:
            parts.extend(["", "### Table 1. Baseline Characteristics", "", table1_md])
        if table2_md:
            parts.extend(["", "### Table 2. Univariate Analysis", "", table2_md])
        if table3_md:
            parts.extend(["", "### Table 3. Multivariate Analysis", "", table3_md])
        self.sections["results"] = Section(
            title="Results",
            content="\n\n".join(parts),
            level=2,
        )
        return self

    def set_references(self, references: list[str]) -> "ManuscriptBuilder":
        """Set the reference list."""
        ref_lines = []
        for i, ref in enumerate(references, 1):
            ref_lines.append(f"{i}. {ref}")
        self.sections["references"] = Section(
            title="References",
            content="\n".join(ref_lines),
            level=2,
        )
        return self

    # ─── Rendering ─────────────────────────────────────────────────────────

    def render(self) -> str:
        """Render the complete manuscript as a markdown string."""
        lines = []

        # Title
        if "title" in self.sections:
            lines.append(f"# {self.sections['title'].title}\n")

        # Authors & affiliations
        if self._authors:
            lines.extend(self._render_authors())
            lines.append("")

        # Abstract
        if "abstract" in self.sections:
            lines.append(self.sections["abstract"].render())
            lines.append("")

        # Keywords
        if self._keywords:
            lines.append(f"**Keywords:** {', '.join(self._keywords)}\n")

        # Main sections in order
        section_order = [
            "introduction",
            "methods",
            "results",
            "discussion",
            "conclusions",
        ]
        for name in section_order:
            if name in self.sections:
                lines.append(self.sections[name].render())
                lines.append("")

        # References
        if "references" in self.sections:
            lines.append(self.sections["references"].render())
            lines.append("")

        # Supplementary
        if "supplementary" in self.sections:
            lines.append(self.sections["supplementary"].render())
            lines.append("")

        # Figure legends
        if self.figures:
            lines.extend(self._render_figure_legends())

        # Tables
        if self.tables:
            lines.extend(self._render_tables())

        # Footers
        lines.extend(self._render_footers())

        return "\n".join(lines)

    def _render_authors(self) -> list[str]:
        """Render author list with superscript affiliations."""
        lines = []
        if not self._authors:
            return lines

        # Build author line with affiliation superscripts
        author_parts = []
        for i, author in enumerate(self._authors):
            affil_idx = i % max(1, len(self._affiliations))
            if self._affiliations:
                author_parts.append(f"{author}<sup>{affil_idx + 1}</sup>")
            else:
                author_parts.append(author)

        lines.append(", ".join(author_parts))

        # Affiliations
        for i, affil in enumerate(self._affiliations):
            lines.append(f"<sup>{i+1}</sup>{affil}")

        return lines

    def _render_figure_legends(self) -> list[str]:
        """Render figure legends section."""
        lines = ["", "## Figure Legends\n"]
        for fig in self.figures:
            lines.append(f"**Figure {fig.number}.** {fig.caption}")
            if fig.in_text:
                lines.append(f"*In text: {fig.in_text}*")
            lines.append("")
        return lines

    def _render_tables(self) -> list[str]:
        """Render table section."""
        lines = ["", "## Tables\n"]
        for tbl in self.tables:
            lines.append(f"**Table {tbl.number}.** {tbl.title}")
            if tbl.filename:
                lines.append(f"*{tbl.filename}*")
            lines.append("")
        return lines

    def _render_footers(self) -> list[str]:
        """Render funding, conflicts, acknowledgements, correspondence."""
        lines = []
        if self._funding:
            lines.extend(["", "## Funding", "", self._funding])
        if self._conflicts:
            lines.extend(["", "## Conflict of Interest", "", self._conflicts])
        if self._acknowledgements:
            lines.extend(["", "## Acknowledgements", "", self._acknowledgements])
        if self._correspondence:
            c = self._correspondence
            lines.extend([
                "",
                "## Correspondence",
                "",
                f"**Corresponding Author:** {c['name']}",
                f"**Email:** {c['email']}",
            ])
            if c.get("phone"):
                lines.append(f"**Phone:** {c['phone']}")
        return lines

    def _wrap_abstract(self, content: str) -> str:
        """Wrap abstract content in a styled block."""
        return f"> {content.strip()}\n"

    # ─── Figure legend auto-generation ───────────────────────────────────

    @staticmethod
    def auto_figure_legend(
        figure_type: str,
        figure_number: int,
        analysis_context: str,
        statistical_test: str = "",
        p_value: str = "",
        panel_labels: list[str] | None = None,
    ) -> str:
        """
        Auto-generate a figure legend from analysis metadata.

        Args:
            figure_type:     flow_chart | kaplan_meier | forest_plot | roc_curve |
                            calibration_plot | heatmap | box_plot | stacked_bar
            figure_number:   Sequential figure number (1, 2, ...)
            analysis_context: Brief description of what's shown
            statistical_test: The statistical test used (e.g. "log-rank test")
            p_value:         P-value string (e.g. "P < 0.001")
            panel_labels:    List of panel labels (e.g. ["A", "B", "C"])

        Returns:
            A properly formatted figure legend string.
        """
        # Base legend template by figure type
        templates = {
            "flow_chart": "{context} Abbreviations: ICU, intensive care unit; n, number of patients.",
            "kaplan_meier": "{context} Survival curves were compared using the {test}. {pval}",
            "forest_plot": "{context} {test} {pval}",
            "roc_curve": "{context} {test} {pval}",
            "calibration_plot": "{context} {test} {pval}",
            "heatmap": "{context}",
            "box_plot": "{context} Data are presented as median (IQR). {pval}",
            "stacked_bar": "{context}",
        }

        template = templates.get(figure_type, "{context}")
        pval_str = f"{p_value}" if p_value else ""
        test_str = statistical_test or "statistical test"

        legend = template.format(context=analysis_context, test=test_str, pval=pval_str)

        # Add panel labels if present
        if panel_labels:
            panels_str = " / ".join(f"({l})" for l in panel_labels)
            legend = f"{panels_str} {legend}"

        return f"Figure {figure_number}. {legend}"

    # ─── STROBE compliance checker ────────────────────────────────────────

    def check_strobe(self, stat_methods_content: str) -> dict[str, Any]:
        """
        Check STROBE compliance of the manuscript.

        Returns a dict with item → covered (bool) + suggestion.
        """
        text = self._get_all_text().lower()
        methods_lower = stat_methods_content.lower()

        checks = {
            "Item 4 (Study design)": self.study_type in text,
            "Item 5 (Setting/location)": any(k in text for k in ["setting", "hospital", "trauma registry", "icu"]),
            "Item 6 (Participants)": any(k in text for k in ["inclusion", "exclusion", "eligibility"]),
            "Item 7 (Variables)": any(k in text for k in ["outcome", "exposure", "confound"]),
            "Item 8 (Data sources)": any(k in text for k in ["database", "chart", "record", "his"]),
            "Item 9 (Bias)": any(k in methods_lower for k in ["bias", "confound", "adjust"]),
            "Item 10 (Sample size)": any(k in methods_lower for k in ["sample", "consecutive", "enrollment"]),
            "Item 11 (Quantitative variables)": any(k in methods_lower for k in ["continuous", "categorical", "cutoff"]),
            "Item 12 (Statistical methods)": "statistical" in methods_lower,
            "Item 13 (Participants flow)": any(k in text for k in ["flow", "diagram", "flowchart", "excluded"]),
            "Item 14 (Descriptive data)": any(k in text for k in ["baseline", "characteristic", "mean", "median"]),
            "Item 15 (Main results)": any(k in text for k in ["result", "association", "odds", "hazard"]),
            "Item 16 (Other analyses)": any(k in text for k in ["sensitivity", "subgroup", "secondary"]),
            "Item 17 (Survival data)": any(k in text for k in ["survival", "kaplan", "hazard", "cox"]),
            "Item 19 (Funding)": bool(self._funding),
            "Item 22 (Conflicts)": bool(self._conflicts),
        }

        covered = sum(1 for v in checks.values() if v)
        total = len(checks)
        compliance_pct = covered / total * 100 if total > 0 else 0

        return {
            "items": checks,
            "covered": covered,
            "total": total,
            "compliance_percent": round(compliance_pct, 1),
            "missing": [k for k, v in checks.items() if not v],
        }

    def _get_all_text(self) -> str:
        """Get all text content from all sections."""
        parts = []
        for section in self.sections.values():
            parts.append(section.title)
            parts.append(section.content)
            for sub in section.subsections:
                parts.append(sub.title)
                parts.append(sub.content)
        return "\n".join(parts)


# ─── Paper Writer (high-level orchestrator) ─────────────────────────────────


class PaperWriter:
    """
    High-level manuscript writer that reads Stage 1-3 outputs and produces
    a complete IMRaD manuscript.

    Input files (all optional — falls back to defaults if not provided):
      stat_results:     statistical_results.md (Stage 1)
      stat_methods:     stat_methods_paragraph.md (Stage 1)
      draft:            manuscript_draft.md (Stage 2)
      verified_refs:    reference_verification_report.md (Stage 3)
      table1_data:      Table 1 as markdown (Stage 1)
      ethics_statement: ethics statement text

    Output:
      Complete manuscript as markdown + optional STROBE report
    """

    def __init__(
        self,
        stat_results: str | Path | None = None,
        stat_methods: str | Path | None = None,
        draft: str | Path | None = None,
        verified_refs: str | Path | None = None,
        project_dir: str | Path = ".",
    ):
        self.project_dir = Path(project_dir)
        self.stat_results = self._read(stat_results)
        self.stat_methods = self._read(stat_methods)
        self.draft = self._read(draft)
        self.verified_refs = self._read(verified_refs)
        self.table1_md: str = ""
        self.table2_md: str = ""
        self.table3_md: str = ""
        self.ethics_statement: str = ""
        self.trial_registration: str = ""
        self._metadata: dict[str, Any] = {}

    def _read(self, path: str | Path | None) -> str:
        """Read a file, return empty string if not found."""
        if path is None:
            return ""
        p = Path(path)
        if not p.is_absolute():
            p = self.project_dir / p
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
        return ""

    def load_table(self, number: int, path: str | Path) -> "PaperWriter":
        """Load a table (1, 2, or 3) from a markdown file."""
        content = self._read(path)
        if number == 1:
            self.table1_md = content
        elif number == 2:
            self.table2_md = content
        elif number == 3:
            self.table3_md = content
        return self

    def set_metadata(
        self,
        title: str,
        authors: list[str],
        affiliations: list[str] | None = None,
        correspondence: dict[str, str] | None = None,
        keywords: list[str] | None = None,
        funding: str = "",
        conflicts: str = "",
        acknowledgements: str = "",
        study_type: str = "retrospective cohort",
        abstract: str = "",
        ethics_statement: str = "",
        trial_registration: str = "",
    ) -> "PaperWriter":
        """Set manuscript metadata."""
        self._metadata = {
            "title": title,
            "authors": authors,
            "affiliations": affiliations or [],
            "correspondence": correspondence or {},
            "keywords": keywords or [],
            "funding": funding,
            "conflicts": conflicts,
            "acknowledgements": acknowledgements,
            "study_type": study_type,
            "abstract": abstract,
            "ethics_statement": ethics_statement,
            "trial_registration": trial_registration,
        }
        return self

    def write(
        self,
        output: str | Path | None = None,
        include_strobe_report: bool = True,
    ) -> str:
        """
        Build and write the complete manuscript.

        Args:
            output:   Output file path (optional — returns string if not set)
            include_strobe_report: If True, append STROBE compliance report

        Returns:
            The complete manuscript as a string.
        """
        # Extract reference list from verified refs (simple parsing)
        references = self._extract_references()

        # Parse draft into sections
        sections = self._parse_draft()

        # Build manuscript
        mb = ManuscriptBuilder(
            project_name=self._metadata.get("title", "Untitled"),
            study_type=self._metadata.get("study_type", "retrospective cohort"),
        )

        # Set metadata
        m = self._metadata
        mb.set_title(m.get("title", ""))
        mb.set_authors(m.get("authors", []))
        if m.get("affiliations"):
            mb.set_affiliations(m["affiliations"])
        if m.get("correspondence"):
            c = m["correspondence"]
            mb.set_correspondence(c.get("name", ""), c.get("email", ""), c.get("phone", ""))
        if m.get("keywords"):
            mb.set_keywords(m["keywords"])
        if m.get("funding"):
            mb.set_funding(m["funding"])
        if m.get("conflicts"):
            mb.set_conflicts(m["conflicts"])
        if m.get("acknowledgements"):
            mb.set_acknowledgements(m["acknowledgements"])

        # Abstract
        if m.get("abstract"):
            mb.set_abstract(m["abstract"])

        # Introduction
        if "introduction" in sections:
            mb.set_section(
                "introduction", "Introduction", sections["introduction"]
            )

        # Methods (stat methods + ethics)
        stat_m = self.stat_methods or m.get("ethics_statement", "")
        ethics = m.get("ethics_statement", "")
        trial_reg = m.get("trial_registration", "")
        mb.set_methods(stat_m, ethics, trial_reg)

        # Results (stat results + tables)
        mb.set_results(
            stat_results=self.stat_results,
            table1_md=self.table1_md,
            table2_md=self.table2_md,
            table3_md=self.table3_md,
        )

        # Discussion (from draft)
        if "discussion" in sections:
            mb.set_section("discussion", "Discussion", sections["discussion"])

        # Conclusions (from draft or auto)
        if "conclusions" in sections:
            mb.set_section("conclusions", "Conclusions", sections["conclusions"])
        elif "discussion" in sections:
            # Auto-generate conclusion from discussion last paragraph
            disc = sections["discussion"]
            paras = disc.split("\n\n")
            if paras:
                mb.set_section("conclusions", "Conclusions", paras[-1].strip())
                sections["discussion"] = "\n\n".join(paras[:-1])
                mb.set_section("discussion", "Discussion", sections["discussion"])

        # References
        if references:
            mb.set_references(references)

        # Render
        manuscript = mb.render()

        # STROBE compliance report
        if include_strobe_report:
            strobe = mb.check_strobe(self.stat_methods)
            manuscript += self._render_strobe_report(strobe)

        # Write output
        if output:
            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(manuscript, encoding="utf-8")

        return manuscript

    def _extract_references(self) -> list[str]:
        """Extract reference list from verified refs or draft."""
        # Try to parse from verified_refs markdown report
        if self.verified_refs:
            # Simple: look for lines that look like references
            # (start with a number + dot, or contain a DOI)
            refs = []
            for line in self.verified_refs.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Skip markdown headers and table rows
                if line.startswith("#") or line.startswith("|") or line.startswith("**"):
                    continue
                # Skip empty entries and section markers
                if line.startswith("##") or line.startswith("**Total"):
                    continue
                # Try to extract DOI-based references
                doi_match = re.search(r"`(10\.\S+)`", line)
                if doi_match or re.match(r"^\d+\.", line):
                    # Clean up table cells and extract the reference text
                    # Remove status icons and formatting
                    cleaned = re.sub(r"^[✅🔧⚠️❌❓]\s*", "", line)
                    cleaned = re.sub(r"\|[^|]*$", "", cleaned)  # Remove trailing table cols
                    cleaned = cleaned.strip("| ")
                    # Keep only the reference-like part (after status and DOI)
                    parts = cleaned.split(")", 1)
                    if len(parts) > 1:
                        cleaned = parts[1].strip()
                    if cleaned and len(cleaned) > 10:
                        refs.append(cleaned)
                    elif len(parts) == 1:
                        # It's a standalone reference
                        ref_text = re.sub(r"^\d+\.\s*", "", parts[0])
                        if ref_text:
                            refs.append(ref_text)
            if refs:
                return refs

        # Fallback: extract from draft
        if self.draft:
            refs_section = re.search(
                r"(?:^|\n)# References\n(.*?)(?:\n\n#|\Z)",
                self.draft,
                re.DOTALL | re.IGNORECASE,
            )
            if refs_section:
                text = refs_section.group(1)
                refs = []
                for line in text.splitlines():
                    line = line.strip()
                    if re.match(r"^\d+\.", line):
                        refs.append(re.sub(r"^\d+\.\s*", "", line).strip())
                if refs:
                    return refs

        return []

    def _parse_draft(self) -> dict[str, str]:
        """Parse the draft markdown into named sections."""
        if not self.draft:
            return {}

        sections = {}
        current_title = None
        current_lines = []

        for line in self.draft.splitlines():
            # Detect section headers (# Introduction, ## Methods, etc.)
            match = re.match(r"^(#{1,3})\s+(.+)$", line.strip())
            if match:
                # Save previous section
                if current_title:
                    sections[current_title.lower()] = "\n".join(current_lines).strip()
                current_title = match.group(2).strip()
                current_lines = []
            else:
                current_lines.append(line)

        # Save last section
        if current_title:
            sections[current_title.lower()] = "\n".join(current_lines).strip()

        return sections

    def _render_strobe_report(self, strobe: dict[str, Any]) -> str:
        """Render STROBE compliance report as markdown."""
        lines = [
            "\n---\n",
            "## STROBE Compliance Report\n",
            f"**Overall compliance:** {strobe['covered']}/{strobe['total']} "
            f"items covered ({strobe['compliance_percent']}%)\n",
            "| STROBE Item | Status |",
            "|:------------|:-------|",
        ]

        for item, covered in strobe["items"].items():
            status = "✅ Covered" if covered else "❌ Missing"
            lines.append(f"| {item} | {status} |")

        if strobe["missing"]:
            lines.extend(["\n### Missing Items\n"])
            for item in strobe["missing"]:
                lines.append(f"- **{item}** — please add to manuscript\n")

        return "\n".join(lines)


# ─── CLI entry point ─────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a structured medical research manuscript.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--draft", help="Draft manuscript markdown file")
    parser.add_argument("--stat-results", help="Statistical results markdown (Stage 1)")
    parser.add_argument("--stat-methods", help="Statistical methods paragraph (Stage 1)")
    parser.add_argument("--refs", help="Reference verification report (Stage 3)")
    parser.add_argument("--table1", help="Table 1 markdown")
    parser.add_argument("--table2", help="Table 2 markdown")
    parser.add_argument("--table3", help="Table 3 markdown")
    parser.add_argument("--ethics", help="Ethics statement text")
    parser.add_argument("--trial-reg", help="Trial registration statement")
    parser.add_argument(
        "--metadata",
        help="JSON file with metadata (title, authors, affiliations, keywords, ...)",
    )
    parser.add_argument(
        "-o", "--output",
        default="manuscript_final.md",
        help="Output manuscript path",
    )
    parser.add_argument(
        "--no-strobe",
        action="store_true",
        help="Skip STROBE compliance report",
    )
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory (default: current directory)",
    )

    args = parser.parse_args()

    writer = PaperWriter(
        stat_results=args.stat_results,
        stat_methods=args.stat_methods,
        draft=args.draft,
        verified_refs=args.refs,
        project_dir=args.project_dir,
    )

    # Load tables
    if args.table1:
        writer.load_table(1, args.table1)
    if args.table2:
        writer.load_table(2, args.table2)
    if args.table3:
        writer.load_table(3, args.table3)

    # Load metadata
    if args.metadata:
        import json

        with open(args.metadata, encoding="utf-8") as f:
            metadata = json.load(f)
        writer.set_metadata(**metadata)

    # Set ethics/trial registration
    if args.ethics or args.trial_reg:
        m = writer._metadata
        m["ethics_statement"] = args.ethics or m.get("ethics_statement", "")
        m["trial_registration"] = args.trial_reg or m.get("trial_registration", "")
        writer.set_metadata(**m)

    # Write
    manuscript = writer.write(
        output=args.output,
        include_strobe_report=not args.no_strobe,
    )

    print(f"Manuscript written to: {args.output}")
    print(f"  Characters: {len(manuscript)}")
    print(f"  Words: ~{len(manuscript.split())}")


if __name__ == "__main__":
    _cli()
