"""
Security documentation tests: verify README.md and SKILL.md contain required safety content.
"""
import pathlib

ROOT = pathlib.Path(__file__).parent.parent


def test_readme_mentions_deidentified_data_requirement():
    """README.md must contain 'de-identified' and 'not for clinical decision-making' (case insensitive)."""
    readme = (ROOT / "README.md").read_text().lower()
    assert "de-identified" in readme, "README.md must contain 'de-identified'"
    assert "not for clinical decision-making" in readme, "README.md must contain 'not for clinical decision-making'"


def test_skill_mentions_human_review_gate_and_needs_review_block():
    """
    SKILL.md must contain 'human review', 'needs_review' or 'NEEDS_REVIEW',
    and '脱敏' or 'de-identification'.
    """
    skill = (ROOT / "SKILL.md").read_text().lower()
    assert "human review" in skill, "SKILL.md must contain 'human review'"
    needs_review_found = "needs_review" in skill
    assert needs_review_found, "SKILL.md must contain 'needs_review' or 'NEEDS_REVIEW'"
    deid_found = "脱敏" in skill or "de-identification" in skill
    assert deid_found, "SKILL.md must contain '脱敏' or 'de-identification'"
