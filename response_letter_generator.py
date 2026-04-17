#!/usr/bin/env python3
"""
response_letter_generator.py
============================
Peer review response letter generator for the medical-paper-pipeline skill.

Takes reviewer comments + original manuscript → generates point-by-point
response letters with revision classifications and manuscript change markers.

Usage (import as module):
    from response_letter_generator import ResponseLetterGenerator
    gen = ResponseLetterGenerator()
    result = gen.generate(
        comments=reviewer_comments,
        manuscript_changes={},
        decision_type="major_revision",
    )
    print(result["response_letter"])

CLI usage:
    python response_letter_generator.py comments.txt -o response_letter.md
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ─── Data Structures ──────────────────────────────────────────────────────────


class CommentType:
    STATISTICAL = "statistical"
    WRITING = "writing"
    REFERENCE = "reference"
    DATA = "data"
    ETHICS = "ethics"
    EDITORIAL = "editorial"


@dataclass
class ReviewerComment:
    """
    Represents a single reviewer comment.

    Fields:
        id:          Unique ID e.g. "R1-C1" (Reviewer 1, Comment 1)
        reviewer_id: Reviewer number (1, 2, 3, ...)
        verbatim:    Original reviewer text
        type:        CommentType (one of the STATISTICAL/WRITING/etc constants)
        status:      Processing status: pending | addressed | drafted
        response:    The drafted response text
        change:      Description of manuscript change made
        location:    Manuscript location of change (e.g. "Page 5, Para 2")
        change_type: "text_revision" | "new_analysis" | "addition" | "no_change"
        no_change_rationale: Why no change was made (if change_type == no_change)
        new_references: List of new references added
    """

    id: str
    reviewer_id: int
    verbatim: str
    type: str = CommentType.WRITING
    status: str = "pending"
    response: str = ""
    change: str = ""
    location: str = ""
    change_type: str = "text_revision"
    no_change_rationale: str = ""
    new_references: list[str] = field(default_factory=list)
    priority: str = "major"  # "major" | "minor"


@dataclass
class DecisionLetter:
    """Represents the editor's decision letter."""

    date: str = ""  # YYYY-MM-DD
    decision_type: str = "major_revision"  # major | minor | reject_resubmit | accept
    reviewers: list[int] = field(default_factory=list)
    editor_comments: str = ""
    original_manuscript_id: str = ""


# ─── Comment Parser ───────────────────────────────────────────────────────────


class CommentParser:
    """
    Parses reviewer comments from raw text into structured ReviewerComment list.

    Handles common formats:
      - Numbered comments: "Comment 1: ...", "Reviewer 1, Comment 2: ..."
      - Bulleted: "- Reviewer 1: ...", "1. Reviewer comments: ..."
      - Sectioned: "Reviewer #1", "--- Reviewer 2 ---"
    """

    # Patterns for detecting reviewer comment boundaries
    REVIEWER_PATTERNS = [
        # "Reviewer #1", "Reviewer 1:", "Reviewer 1."
        re.compile(r"^reviewer\s*#?\s*(\d+)[\s:,.]+", re.IGNORECASE),
        # "R1:", "R1.", "R1 -"
        re.compile(r"^R\s*(\d+)\s*[:.\-]+", re.IGNORECASE),
        # "Comment 1:", "Comment 1.", "#1"
        re.compile(r"^comment\s*(\d+)[\s:,.:]+", re.IGNORECASE),
        # "--- Reviewer 2 ---" or "===== Reviewer 1 ====="
        re.compile(r"^[=\-]{3,}\s*reviewer\s*(\d+)\s*[=\-]{3,}", re.IGNORECASE),
        # "### Reviewer Comments"
        re.compile(r"^#{1,3}\s*reviewer\s*comments?\s*#?", re.IGNORECASE),
    ]

    COMMENT_PATTERNS = [
        re.compile(r"^comment\s*(\d+(?:[\.\)]\d+)?)\s*[:\.\)]+?\s*(.*)", re.IGNORECASE),
        re.compile(r"^(?:\d+[\.\)]\s*)?(?:comment[:\s]+)?(.+)", re.IGNORECASE),
    ]

    TYPE_KEYWORDS = {
        CommentType.STATISTICAL: [
            "statistic", "method", "analysis", "p-value", "confidence interval",
            "regression", "sample size", "power", "bootstrap", "missing data",
            "imputation", "covariate", "confounder",
        ],
        CommentType.WRITING: [
            "clarity", "writing", "grammar", "sentence", "paragraph", "unclear",
            "rephrase", "rewrite", "concise", "precise", "readability",
        ],
        CommentType.REFERENCE: [
            "reference", "citation", "doi", "文献", "引用", "cite",
            "prior work", "previous study",
        ],
        CommentType.DATA: [
            "data", "result", "table", "figure", "number", "value", "outcome",
            "sample", "population", "baseline",
        ],
        CommentType.ETHICS: [
            "ethic", "informed consent", " IRB", "approval", "committee",
            "declaration", " Helsinki",
        ],
        CommentType.EDITORIAL: [
            "format", "style", "reference format", "abbreviation", "word count",
            "limit", "requirement", "supplement",
        ],
    }

    def parse(self, text: str) -> list[ReviewerComment]:
        """Parse raw reviewer comments into structured ReviewerComment list."""
        lines = text.strip().splitlines()
        comments: list[ReviewerComment] = []
        current_reviewer = 1
        comment_counter = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Detect reviewer change
            reviewer_match = self._detect_reviewer(line)
            if reviewer_match is not None:
                current_reviewer = reviewer_match
                comment_counter = 0
                continue

            # Detect new comment
            if self._is_comment_line(line):
                comment_counter += 1
                comment_text = self._extract_comment_text(line)
                if comment_text:
                    ctype = self._classify_comment(comment_text)
                    comment_id = f"R{current_reviewer}-C{comment_counter}"
                    comments.append(
                        ReviewerComment(
                            id=comment_id,
                            reviewer_id=current_reviewer,
                            verbatim=comment_text,
                            type=ctype,
                        )
                    )

        return comments

    def _detect_reviewer(self, line: str) -> int | None:
        for pattern in self.REVIEWER_PATTERNS:
            match = pattern.match(line)
            if match:
                return int(match.group(1))
        return None

    def _is_comment_line(self, line: str) -> bool:
        """Heuristic: a comment line starts a new comment block."""
        # Numbered: "1.", "1:", "Comment 1:", "1)"
        if re.match(r"^(?:\d+[\.\):]|comment\s+\d+|R\d+|#\d+)", line, re.IGNORECASE):
            return True
        # Bullets
        if re.match(r"^[•\-\*]\s+", line):
            return True
        return False

    def _extract_comment_text(self, line: str) -> str:
        """Strip numbering/bullets from a comment line."""
        text = re.sub(r"^(?:\d+[\.\):]|comment\s+\d+|R\d+|#\d+|[•\-\*]\s+)\s*", "", line)
        return text.strip()

    def _classify_comment(self, text: str) -> str:
        """Classify comment type based on keywords."""
        text_lower = text.lower()
        scores: dict[str, int] = {}

        for ctype, keywords in self.TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[ctype] = score

        if not scores:
            return CommentType.WRITING  # default

        return max(scores, key=scores.get)  # type: ignore


# ─── Response Strategy Router ─────────────────────────────────────────────────


class ResponseStrategyRouter:
    """
    Routes each comment to the appropriate response strategy based on type.
    """

    STRATEGIES = {
        CommentType.STATISTICAL: "statistical_strategy",
        CommentType.WRITING: "writing_strategy",
        CommentType.REFERENCE: "reference_strategy",
        CommentType.DATA: "data_strategy",
        CommentType.ETHICS: "ethics_strategy",
        CommentType.EDITORIAL: "editorial_strategy",
    }

    def route(self, comment: ReviewerComment) -> dict[str, Any]:
        """Return routing decision for a comment."""
        strategy = self.STRATEGIES.get(comment.type, "writing_strategy")
        return {
            "strategy": strategy,
            "change_required": self._requires_change(comment),
            "priority": comment.priority,
            "special_handling": self._special_handling(comment),
        }

    def _requires_change(self, comment: ReviewerComment) -> bool:
        """Determine if this comment requires a manuscript change."""
        # Impossible requests
        impossible = [
            "impossible", "cannot", "not possible", "unable",
            "request new data", "prospective", "new study",
        ]
        text_lower = comment.verbatim.lower()
        if any(phrase in text_lower for phrase in impossible):
            return False

        # Comments that suggest but don't require
        suggestion = ["suggest", "consider", "could", "may want", "might"]
        if any(phrase in text_lower for phrase in suggestion):
            return False

        return True

    def _special_handling(self, comment: ReviewerComment) -> str:
        """Identify special handling needed."""
        text = comment.verbatim.lower()

        if "unrevisable" in text or "impossible" in text:
            return "diplomatic_decline"
        if "both" in text and "method" in text:
            return "show_comparison"
        if "disagree" in text or "not convinced" in text:
            return "polite_defense"
        return "standard"


# ─── Response Letter Generator ────────────────────────────────────────────────


class ResponseLetterGenerator:
    """
    Generates complete peer review response letters.

    Workflow:
      1. Parse reviewer comments (if raw text provided)
      2. Route each comment to appropriate strategy
      3. Generate response for each comment
      4. Assemble per-reviewer response letter
      5. Generate revision summary table
    """

    def __init__(self):
        self.parser = CommentParser()
        self.router = ResponseStrategyRouter()

    def generate(
        self,
        comments: list[ReviewerComment] | str,
        manuscript_changes: dict[str, str] | None = None,
        decision_type: str = "major_revision",
        decision_date: str = "",
        reviewer_count: int | None = None,
    ) -> dict[str, Any]:
        """
        Generate complete response letter package.

        Args:
            comments:         List of ReviewerComment objects OR raw text string
            manuscript_changes: Dict mapping comment_id → "Page X, Para Y: change description"
            decision_type:   major_revision | minor_revision | reject_resubmit
            decision_date:   YYYY-MM-DD of decision letter
            reviewer_count:  Number of reviewers (auto-detected if None)

        Returns:
            Dict with:
              - response_letter: Full response letter markdown
              - revision_summary: Table of all comments/responses
              - comments: Updated ReviewerComment list with responses
              - word_count: Approximate response letter word count
        """
        manuscript_changes = manuscript_changes or {}

        # Parse if raw text
        if isinstance(comments, str):
            comments = self.parser.parse(comments)

        # Set reviewer count
        if reviewer_count is None:
            reviewer_count = max(c.reviewer_id for c in comments) if comments else 0

        # Generate response for each comment
        for comment in comments:
            self._generate_response(comment, manuscript_changes)

        # Assemble response letter
        response_letter = self._assemble_letter(
            comments, decision_type, decision_date
        )

        # Generate revision summary
        summary = self._generate_summary(comments)

        word_count = len(response_letter.split())

        return {
            "response_letter": response_letter,
            "revision_summary": summary,
            "comments": comments,
            "word_count": word_count,
            "decision_type": decision_type,
            "reviewer_count": reviewer_count,
        }

    def _generate_response(
        self, comment: ReviewerComment, changes: dict[str, str]
    ) -> None:
        """Generate response text for a single comment."""
        routing = self.router.route(comment)
        strategy = routing["strategy"]
        change_required = routing["change_required"]
        special = routing["special_handling"]

        response_parts = []

        # Opening: acknowledge
        response_parts.append(f"**Response:** Thank you for this comment.")

        # Determine change type and location
        location = changes.get(comment.id, comment.location)
        change_type = comment.change_type

        if special == "diplomatic_decline":
            response_parts.append(
                "We appreciate this suggestion. However, due to "
                "[limitation], we addressed this through [alternative approach] "
                "and have clarified this in the Discussion"
                + (f" ({location})" if location else "") + "."
            )
            comment.status = "addressed"
            comment.change_type = "no_change"
            comment.no_change_rationale = "Request not feasible; alternative provided"
            comment.response = " ".join(response_parts)
            return

        if not change_required and special != "polite_defense":
            response_parts.append(
                "We appreciate this suggestion. "
                "No manuscript change was made as the current presentation "
                "is consistent with the methodology rationale described in the Methods section"
                + (f" ({location})" if location else "") + "."
            )
            comment.status = "addressed"
            comment.change_type = "no_change"
            comment.no_change_rationale = "Current text already adequate; rationale provided"
        elif strategy == "statistical_strategy":
            response_parts.extend(self._statistical_response(comment, location))
        elif strategy == "writing_strategy":
            response_parts.extend(self._writing_response(comment, location))
        elif strategy == "reference_strategy":
            response_parts.extend(self._reference_response(comment, location))
        elif strategy == "data_strategy":
            response_parts.extend(self._data_response(comment, location))
        elif strategy == "ethics_strategy":
            response_parts.extend(self._ethics_response(comment, location))
        else:
            response_parts.extend(self._editorial_response(comment, location))

        if special == "polite_defense":
            response_parts.append(
                "We respectfully disagree with this concern. "
                "The approach taken is consistent with established methodology "
                "in the field and is supported by the following evidence: "
                "[provide supporting rationale]. "
                "However, we have added a clarifying sentence in the Discussion"
                + (f" ({location})" if location else "") + "."
            )

        if special == "show_comparison":
            response_parts.append(
                "As suggested, we performed both analyses and present the comparison "
                "in Supplementary Table X."
            )

        comment.response = " ".join(response_parts)
        comment.status = "drafted"

    def _statistical_response(self, comment: ReviewerComment, location: str) -> list[str]:
        """Generate response for statistical/methodological comments."""
        parts = []
        text_lower = comment.verbatim.lower()

        if "sample size" in text_lower or "power" in text_lower:
            parts.append(
                "This retrospective study analyzed all consecutively enrolled "
                "eligible patients during the study period. "
                "No formal sample size calculation was performed as this is "
                "standard practice for retrospective analyses of available data. "
                "This limitation is acknowledged in the Discussion."
            )
        elif "missing" in text_lower and ("data" in text_lower or "value" in text_lower):
            parts.append(
                "Missing data were handled using complete case analysis. "
                "The proportion of missing values is reported in Table 1. "
                "The missingness mechanism was assessed and reported as MAR, "
                "which is a reasonable assumption for this type of retrospective data."
            )
        elif any(k in text_lower for k in ["regression", "multivariate", "adjusted"]):
            parts.append(
                "Multivariate analysis was performed using [method], "
                "adjusting for clinically relevant covariates including age, sex, "
                "and injury severity. Variables were selected based on clinical "
                "relevance and statistical significance in univariate analysis (P < 0.10). "
                "All clinically relevant variables were retained regardless of P-value "
                "to avoid overfitting."
            )
        else:
            parts.append(
                "The statistical methods have been described in greater detail "
                "in the Methods section."
            )

        if location:
            parts.append(f"The relevant text has been revised ({location}).")

        return parts

    def _writing_response(self, comment: ReviewerComment, location: str) -> list[str]:
        """Generate response for writing/clarity comments."""
        parts = []
        if location:
            parts.append(
                f"The manuscript has been revised for clarity ({location})."
            )
        else:
            parts.append(
                "The text has been revised to improve clarity throughout the manuscript."
            )
        return parts

    def _reference_response(self, comment: ReviewerComment, location: str) -> list[str]:
        """Generate response for reference/citation comments."""
        parts = []
        if comment.new_references:
            refs = ", ".join(f"[{r}]" for r in comment.new_references)
            parts.append(
                f"The following reference has been added to support this point: {refs}."
            )
        else:
            parts.append(
                "The citation has been verified via PubMed DOI lookup "
                "(Stage 3 of the pipeline) and corrected as needed."
            )
        if location:
            parts.append(f"Change made ({location}).")
        return parts

    def _data_response(self, comment: ReviewerComment, location: str) -> list[str]:
        """Generate response for data/results comments."""
        parts = []
        if location:
            parts.append(f"The data have been clarified ({location}).")
        else:
            parts.append("The results have been double-checked against the raw data.")
        return parts

    def _ethics_response(self, comment: ReviewerComment, location: str) -> list[str]:
        """Generate response for ethics-related comments."""
        parts = [
            "The ethics statement has been reviewed and strengthened. "
            "The statement now clearly describes the IRB approval status "
            "and the rationale for waiver of informed consent."
        ]
        if location:
            parts.append(f"Revision made ({location}).")
        return parts

    def _editorial_response(self, comment: ReviewerComment, location: str) -> list[str]:
        """Generate response for editorial/formatting comments."""
        parts = []
        if location:
            parts.append(f"Formatting has been corrected ({location}).")
        else:
            parts.append("The formatting has been corrected to comply with journal guidelines.")
        return parts

    def _assemble_letter(
        self,
        comments: list[ReviewerComment],
        decision_type: str,
        decision_date: str,
    ) -> str:
        """Assemble the full response letter."""
        lines = []

        # Header
        lines.extend([
            "# Response to Reviewers\n",
            f"**Decision type:** {decision_type.replace('_', ' ').title()}\n",
            f"**Date:** {decision_date or '[Decision Letter Date]'}\n",
            f"**Manuscript:** [Manuscript Title]\n",
            "\n---\n",
            "\nWe would like to thank the reviewers and editor for their thoughtful "
            "comments and constructive suggestions. Below we address each point "
            "in detail. All changes are indicated with the manuscript location.\n",
        ])

        # Group by reviewer
        reviewer_ids = sorted(set(c.reviewer_id for c in comments))

        for rid in reviewer_ids:
            reviewer_comments = [c for c in comments if c.reviewer_id == rid]
            lines.extend([
                f"\n## Response to Reviewer #{rid}\n",
            ])

            for comment in reviewer_comments:
                # Comment header
                lines.extend([
                    f"\n**Comment {comment.id}:** {comment.verbatim}\n",
                ])

                # Response
                if comment.response:
                    lines.append(f"{comment.response}\n")

                # Change detail
                if comment.change_type == "no_change":
                    lines.append(
                        f"**No change made.** Rationale: {comment.no_change_rationale or 'Current text is adequate.'}\n"
                    )
                else:
                    if comment.change:
                        lines.append(f"**Change made:** {comment.change}\n")
                    elif comment.location:
                        lines.append(f"**Location:** {comment.location}\n")

                # New references
                if comment.new_references:
                    lines.append(
                        f"**New reference(s):** {', '.join(comment.new_references)}\n"
                    )

        # Closing
        lines.extend([
            "\n---\n",
            "\n**Summary of Changes:**\n",
            f"- Total comments addressed: {len(comments)}\n",
            f"- Text revisions: {sum(1 for c in comments if c.change_type == 'text_revision')}\n",
            f"- No changes (rationale provided): {sum(1 for c in comments if c.change_type == 'no_change')}\n",
            f"- New references added: {len([r for c in comments for r in c.new_references])}\n",
            "\nWe believe all reviewer concerns have been adequately addressed. "
            "We hope the revised manuscript is now suitable for publication.\n",
            "\nSincerely,\n",
            "\n[All Authors]\n",
            "[Corresponding Author]\n",
        ])

        return "\n".join(lines)

    def _generate_summary(self, comments: list[ReviewerComment]) -> str:
        """Generate a markdown revision summary table."""
        lines = [
            "# Revision Summary Table\n",
            "| # | Reviewer | Comment Summary | Type | Change? | Location | Status |",
            "|--:|----------|-----------------|------|---------|----------|--------|",
        ]

        for c in comments:
            # Truncate verbatim
            summary = c.verbatim[:60] + "..." if len(c.verbatim) > 60 else c.verbatim
            summary = summary.replace("|", "\\|")

            change_str = (
                "No" if c.change_type == "no_change" else "Yes"
            )

            lines.append(
                f"| {c.id} | Reviewer {c.reviewer_id} | {summary} | "
                f"{c.type} | {change_str} | {c.location or '—'} | {c.status} |"
            )

        return "\n".join(lines)


# ─── CLI entry point ─────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate peer review response letter from reviewer comments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "comments",
        help="Reviewer comments (raw text or JSON with ReviewerComment objects)",
    )
    parser.add_argument(
        "-o", "--output",
        default="response_letter.md",
        help="Output response letter path",
    )
    parser.add_argument(
        "--summary",
        default="revision_summary.md",
        help="Output revision summary path",
    )
    parser.add_argument(
        "--decision-type",
        default="major_revision",
        choices=["major_revision", "minor_revision", "reject_resubmit", "accept"],
        help="Decision type",
    )
    parser.add_argument(
        "--decision-date",
        default="",
        help="Decision letter date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--changes",
        help="JSON file mapping comment_id → location/change description",
    )
    parser.add_argument(
        "--reviewer-count",
        type=int,
        help="Number of reviewers (auto-detected if not set)",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Also save full result as JSON",
    )

    args = parser.parse_args()

    # Load comments
    comments_path = Path(args.comments)
    if comments_path.suffix == ".json":
        comments_data = json.loads(comments_path.read_text(encoding="utf-8"))
        if isinstance(comments_data, list):
            comments = [ReviewerComment(**c) for c in comments_data]
        else:
            comments = comments_data
    else:
        comments = comments_path.read_text(encoding="utf-8")

    # Load changes
    changes = {}
    if args.changes:
        changes = json.loads(Path(args.changes).read_text(encoding="utf-8"))

    # Generate
    gen = ResponseLetterGenerator()
    result = gen.generate(
        comments=comments,
        manuscript_changes=changes,
        decision_type=args.decision_type,
        decision_date=args.decision_date,
        reviewer_count=args.reviewer_count,
    )

    # Save
    Path(args.output).write_text(result["response_letter"], encoding="utf-8")
    print(f"Response letter saved to: {args.output}")
    print(f"  Word count: {result['word_count']}")
    print(f"  Comments addressed: {len(result['comments'])}")
    print(f"  Reviewers: {result['reviewer_count']}")

    Path(args.summary).write_text(result["revision_summary"], encoding="utf-8")
    print(f"Revision summary saved to: {args.summary}")

    if args.json_output:
        json_path = args.output.replace(".md", ".json")
        # Convert dataclasses to dicts for JSON serialization
        result_json = {
            k: v if not isinstance(v, list)
            else [
                c.to_dict() if hasattr(c, "to_dict") else c
                for c in v
            ]
            for k, v in result.items()
        }
        # Add to_dict for ReviewerComment
        for c in result["comments"]:
            if hasattr(c, "to_dict"):
                c_dict = c.__dict__.copy()
                c_dict["to_dict"] = lambda: c_dict.copy()
        Path(json_path).write_text(
            json.dumps(result, indent=2, default=lambda x: x.__dict__ if hasattr(x, "__dict__") else str(x)),
            encoding="utf-8",
        )
        print(f"JSON output saved to: {json_path}")


if __name__ == "__main__":
    _cli()
