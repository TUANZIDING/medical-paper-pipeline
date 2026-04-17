#!/usr/bin/env python3
from __future__ import annotations

"""
stat_methods_templates.py
=========================
Statistical methods paragraph generator for the medical-paper-pipeline skill.

Loads template rules from templates/stat_template_rules.json and generates
a STROBE-compliant statistical methods paragraph by matching templates to
analyses performed in Stage 1, then filling placeholders with study-specific values.

Usage (import as module):
    from stat_methods_templates import StatTemplateEngine
    engine = StatTemplateEngine(templates_dir="templates")
    engine.generate(
        analyses_performed=["descriptive", "t_test", "chi_square", "logistic_regression"],
        values={
            "institution": "Department of Trauma Surgery, XX Hospital",
            "start_date": "2019-01",
            "end_date": "2023-12",
            "outcome_definition": "in-hospital mortality defined as death within the same hospital admission",
            ...
        },
        options={
            "study_design_variant": "retrospective_cohort",
            "proportionality_violated": False,
            ...
        }
    )

CLI usage:
    python stat_methods_templates.py --analyses "descriptive,t_test,logistic_regression" --values values.json
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


# Analysis name → template key mapping.
# Maps analysis names (from pipeline_state.json analyses_performed)
# to the corresponding template key(s) in stat_template_rules.json.
ANALYSIS_TO_TEMPLATE = {
    "descriptive": ["descriptive"],
    "t_test": ["t_test"],
    "mann_whitney": ["t_test"],
    "chi_square": ["chi_square"],
    "fisher_exact": ["chi_square"],
    "logistic_regression": ["logistic_regression"],
    "cox_regression": ["cox_regression", "survival"],
    "kaplan_meier": ["survival"],
    "survival_analysis": ["survival"],
    "correlation": ["correlation"],
    "roc_auc": ["roc_analysis"],
    "calibration": ["calibration"],
    "bootstrap_validation": ["internal_validation"],
    "propensity_matching": ["propensity_matching"],
    "propensity_weighting": ["propensity_score_weighting"],
    "multiple_imputation": ["multiple_imputation"],
    "sensitivity_analysis": ["sensitivity_analysis"],
    "subgroup_analysis": ["subgroup_analysis"],
    "missing_data": ["missing_data"],
}


class StatTemplateEngine:
    """
    Loads template rules from JSON and generates statistical methods paragraphs.

    The engine:
    1. Loads stat_template_rules.json
    2. Resolves which templates apply based on analyses performed
    3. Fills [placeholders] with study-specific values
    4. Composes templates in STROBE-compliant order
    5. Optionally checks STROBE coverage
    """

    REQUIRED_TEMPLATES = [
        "study_design", "setting", "variables", "descriptive", "software"
    ]
    """Templates that should always be included regardless of analysis type."""

    def __init__(self, templates_dir: str | Path | None = None):
        """
        Args:
            templates_dir: Directory containing stat_template_rules.json.
                          Defaults to the 'templates/' subdirectory of the
                          directory containing this script.
        """
        if templates_dir is None:
            templates_dir = Path(__file__).parent.parent / "templates"
        self.templates_dir = Path(templates_dir)
        self.json_path = self.templates_dir / "stat_template_rules.json"
        self.data = self._load()

    # ─── Loading ────────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not self.json_path.exists():
            raise FileNotFoundError(
                f"Template file not found: {self.json_path}. "
                "Run from the skill directory or pass templates_dir."
            )
        with open(self.json_path, encoding="utf-8") as f:
            data = json.load(f)
        self._validate(data)
        return data

    def _validate(self, data: dict) -> None:
        for key in ["template_keys", "template_order", "strobe_item_mapping"]:
            if key not in data:
                raise ValueError(f"Missing required key in template JSON: {key}")
        stored_order = set(data["template_order"])
        declared = set(data["template_keys"].keys())
        if stored_order != declared:
            missing = stored_order - declared
            extra = declared - stored_order
            raise ValueError(
                f"template_order mismatch: missing from template_keys: {missing}, "
                f"extra in template_keys: {extra}"
            )

    # ─── Core generation ──────────────────────────────────────────────────────

    def generate(
        self,
        analyses_performed: list[str] | None = None,
        values: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        check_strobe: bool = True,
    ) -> str:
        """
        Generate the complete statistical methods paragraph.

        Args:
            analyses_performed: List of analysis names (e.g., ["descriptive", "t_test",
                              "logistic_regression"]). Maps to template keys via
                              ANALYSIS_TO_TEMPLATE. Pass None to include only the
                              required templates (study design, setting, etc.).
            values:          Dictionary of placeholder → value mappings.
                             e.g., {"institution": "XX Hospital", "start_date": "2019-01"}
                             All [placeholders] in the used templates should be covered.
                             Missing ones are left as [placeholder_name] in the output.
            options:         Generation options:
                             - study_design_variant: "retrospective_cohort" |
                                                    "retrospective_case_control" |
                                                    "cross_sectional"
                             - proportionality_violated: bool (for survival template)
                             - heterogeneity: bool (for t_test template)
                             - mi_used: bool (overrides missing_data template)
                             - psm_failed: bool (propensity matching fallback)
                             - forced_entry: bool (logistic regression forced entry)
                             - hl_supplementary: bool (Hosmer-Lemeshow only, no new metrics)
                             - comprehensive_sa: bool (4-part sensitivity analysis)
            check_strobe:    If True, warn about missing STROBE items.

        Returns:
            The complete statistical methods paragraph as a single string.
        """
        analyses_performed = analyses_performed or []
        values = values or {}
        options = options or {}

        templates_to_use = self._resolve_templates(analyses_performed)
        paragraphs = []

        for key in self.data["template_order"]:
            if key not in templates_to_use:
                continue

            paragraph = self._render_template(key, values, options)
            if paragraph:
                paragraphs.append(paragraph)

        output = "\n\n".join(paragraphs)

        if check_strobe:
            self._stobe_warning(analyses_performed, templates_to_use)

        return output

    def _resolve_templates(self, analyses_performed: list[str]) -> set[str]:
        """Map analysis names to template keys."""
        templates = set(self.REQUIRED_TEMPLATES)
        for analysis in analyses_performed:
            keys = ANALYSIS_TO_TEMPLATE.get(analysis.lower(), [])
            templates.update(keys)
        return templates

    def _render_template(
        self, key: str, values: dict, options: dict
    ) -> str | None:
        """Fill placeholders in a single template and return the result."""
        template_data = self.data["template_keys"].get(key)
        if template_data is None:
            return None

        template = self._select_variant(key, template_data, options)
        if template is None:
            return None

        filled = self._substitute(template, values)
        return filled.strip()

    def _select_variant(
        self, key: str, template_data: dict, options: dict
    ) -> str | None:
        """Select the appropriate template variant based on options."""
        if key == "study_design":
            variant = options.get("study_design_variant", "retrospective_cohort")
            variants = template_data.get("variants", {})
            template = variants.get(variant)
            if template is None:
                # Fallback to the first available variant
                template = next(iter(variants.values()), None)
            return template

        if key == "survival":
            if options.get("proportionality_violated"):
                return template_data.get("template_no_proportionality")
            return template_data.get("template")

        if key == "t_test":
            if options.get("heterogeneity"):
                return template_data.get("template_with_heterogeneity")
            return template_data.get("template")

        if key == "logistic_regression":
            if options.get("forced_entry"):
                return template_data.get("template_forced_entry")
            return template_data.get("template")

        if key == "calibration":
            if options.get("hl_supplementary"):
                return template_data.get("template_with_hl_only")
            return template_data.get("template")

        if key == "missing_data":
            if options.get("mi_used"):
                return template_data.get("template_with_mi")
            return template_data.get("template")

        if key == "propensity_matching":
            if options.get("psm_failed"):
                return template_data.get("template_psm_failure")
            return template_data.get("template")

        if key == "sensitivity_analysis":
            if options.get("comprehensive_sa"):
                return template_data.get("template_comprehensive")
            return template_data.get("template")

        if key == "multiple_imputation":
            if options.get("mi_diagnostics"):
                return template_data.get("template_mice_diagnostics")
            return template_data.get("template")

        # Default: use the primary "template" field
        return template_data.get("template")

    def _substitute(self, template: str, values: dict) -> str:
        """
        Replace [placeholder] tokens with values from the values dict.
        Bracket-style placeholders are case-sensitive and must match exactly.
        Missing placeholders are left as-is (not silently dropped).
        """
        if not template:
            return ""

        def replacer(match: re.Match) -> str:
            key = match.group(1).strip()
            value = values.get(key)
            if value is None:
                # Leave as [placeholder] to signal missing value
                return match.group(0)
            return str(value)

        # Replace [placeholder] and [placeholder with spaces] patterns
        result = re.sub(r"\[([^\]]+)\]", replacer, template)
        return result

    # ─── STROBE compliance checking ───────────────────────────────────────────

    def check_strobe_coverage(
        self, analyses_performed: list[str] | None = None
    ) -> dict:
        """
        Check which STROBE items are covered by the current analysis plan.

        Returns a dict: strobe_item → covered (bool) + template_keys
        """
        analyses_performed = analyses_performed or []
        templates_used = self._resolve_templates(analyses_performed)

        coverage = {}
        for strobe_item, template_keys in self.data["strobe_item_mapping"].items():
            if isinstance(template_keys, str):
                template_keys = [template_keys]
            covered = any(k in templates_used for k in template_keys)
            coverage[strobe_item] = {
                "covered": covered,
                "template_keys": template_keys,
                "status": "covered" if covered else "MISSING",
            }
        return coverage

    def _stobe_warning(
        self, analyses_performed: list[str], templates_used: set[str]
    ) -> None:
        """Print a warning for any uncovered STROBE items."""
        coverage = self.check_strobe_coverage(analyses_performed)
        missing = [
            f"  {item}: {info['template_keys']}"
            for item, info in coverage.items()
            if not info["covered"] and info["template_keys"] != "patient flow chart"
        ]
        if missing:
            sys.stderr.write(
                f"WARNING: The following STROBE items are not covered by the "
                f"current analysis plan:\n"
                + "\n".join(missing)
                + "\nConsider adding these analyses or manually describing the methods.\n"
            )

    # ─── Utility methods ──────────────────────────────────────────────────────

    def list_templates(self) -> list[str]:
        """Return all available template key names."""
        return list(self.data["template_keys"].keys())

    def describe_template(self, key: str) -> dict | None:
        """Return description and STROBE item for a template key."""
        template_data = self.data["template_keys"].get(key)
        if template_data is None:
            return None
        return {
            "key": key,
            "strobe_item": template_data.get("strobe_item"),
            "description": template_data.get("description"),
            "has_variants": "variants" in template_data,
            "has_notes": "note" in template_data,
            "variants": list(template_data.get("variants", {}).keys()),
            "placeholder_rules": template_data.get("placeholder_rules"),
        }

    def preview_template(
        self, key: str, options: dict | None = None
    ) -> str | None:
        """Return the unfilled template text for inspection."""
        options = options or {}
        template_data = self.data["template_keys"].get(key)
        if template_data is None:
            return None
        return self._select_variant(key, template_data, options)

    def templates_for_analysis(self, analysis_name: str) -> list[str]:
        """Return which template keys are triggered by a given analysis name."""
        return ANALYSIS_TO_TEMPLATE.get(analysis_name.lower(), [])


# ─── CLI entry point ───────────────────────────────────────────────────────────

def _cli() -> None:
    """Simple CLI for testing and quick paragraph generation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a statistical methods paragraph from templates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--analyses",
        default="",
        help="Comma-separated list of analysis names "
             "(e.g., descriptive,t_test,logistic_regression)",
    )
    parser.add_argument(
        "--values",
        default="",
        help="Path to JSON file with placeholder values",
    )
    parser.add_argument(
        "--options",
        default="",
        help="Path to JSON file with generation options",
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List all available template keys and exit",
    )
    parser.add_argument(
        "--check-strobe",
        action="store_true",
        default=True,
        help="Check STROBE coverage (default: True)",
    )
    parser.add_argument(
        "--no-check-strobe",
        action="store_false",
        dest="check_strobe",
        help="Disable STROBE coverage check",
    )

    args = parser.parse_args()

    engine = StatTemplateEngine()

    if args.list_templates:
        print("Available template keys:")
        for key in engine.list_templates():
            info = engine.describe_template(key)
            print(f"  {key}")
            print(f"    STROBE: {info['strobe_item']}")
            print(f"    {info['description']}")
            if info["has_variants"]:
                variants_str = ", ".join(info["variants"])
                print(f"    Variants: {variants_str}}}")
            print()
        return

    analyses = [a.strip() for a in args.analyses.split(",") if a.strip()]
    values = {}
    if args.values:
        with open(args.values, encoding="utf-8") as f:
            values = json.load(f)

    options = {}
    if args.options:
        with open(args.options, encoding="utf-8") as f:
            options = json.load(f)

    paragraph = engine.generate(
        analyses_performed=analyses,
        values=values,
        options=options,
        check_strobe=args.check_strobe,
    )
    print(paragraph)


if __name__ == "__main__":
    _cli()
