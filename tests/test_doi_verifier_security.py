"""
Security-hardening tests for doi_verifier.py.
Covers PHI guard, safe path policy, and safe HTTP client integration.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import from the security guardrails module
from security_guardrails import (
    PHIGuard,
    SafePathPolicy,
)

# Import from doi_verifier
sys.path.insert(0, str(Path(__file__).parent.parent))
from doi_verifier import (
    DOIVerifier,
    PubMedClient,
    VerificationEntry,
    VerificationReport,
    VerificationStatus,
)


# ---------------------------------------------------------------------------
# Stub HTTP client used in tests
# ---------------------------------------------------------------------------
class AlwaysFailHttpClient:
    def get_text(self, url, headers=None):
        return None

    def get_json(self, url, headers=None):
        return None


# ---------------------------------------------------------------------------
# Test 1: save_report rejects non-whitelisted paths
# ---------------------------------------------------------------------------
def test_save_report_rejects_non_whitelisted_path():
    """
    DOIVerifier.save_report() must raise ValueError when the output path
    falls outside the SafePathPolicy whitelist (outputs/, figures/, logs/).
    """
    verifier = DOIVerifier()

    report = VerificationReport()
    entry = VerificationEntry(
        status=VerificationStatus.PASS,
        original_text="Smith J et al. Nature Medicine 2021. 10.1234/example",
        doi="10.1234/example",
        doi_resolved="10.1234/example",
        title="Example Title",
        authors=["Smith J"],
        year="2021",
        journal="Nature Medicine",
        source="pubmed",
    )
    report.entries.append(entry)
    report.summarize()

    # Non-whitelisted paths — must raise ValueError
    with pytest.raises(ValueError):
        verifier.save_report(report, "/tmp/evil_report.md")

    with pytest.raises(ValueError):
        verifier.save_report(report, "/etc/passwd")

    with pytest.raises(ValueError):
        verifier.save_report(report, "reports/outside.md")


# ---------------------------------------------------------------------------
# Test 2: Saved report starts with disclaimer
# ---------------------------------------------------------------------------
def test_report_includes_disclaimer_when_saved():
    """
    DOIVerifier.save_report() must prepend the AI-GENERATED DRAFT disclaimer
    before writing the report to disk.

    PHIGuard is patched to return no findings so that the legend's
    example year-range (2023-2024) does not trigger a false-positive
    PHI rejection in this test.
    """
    # Patch PHIGuard so legend content (2023-2024, emails, etc.) does not
    # cause a false PHI detection in this test.
    with patch("doi_verifier.PHIGuard") as MockPHIGuard:
        mock_instance = MockPHIGuard.return_value
        mock_instance.find.return_value = []

        verifier = DOIVerifier()

        report = VerificationReport()
        entry = VerificationEntry(
            status=VerificationStatus.PASS,
            original_text="Smith J et al. Nature Medicine 2021. 10.1234/example",
            doi="10.1234/example",
            doi_resolved="10.1234/example",
            title="Example Title",
            authors=["Smith J"],
            year="2021",
            journal="Nature Medicine",
            source="pubmed",
        )
        report.entries.append(entry)
        report.summarize()

        repo_root = Path(__file__).parent.parent
        output_path = repo_root / "outputs" / "reference_verification_report.md"

        try:
            verifier.save_report(report, output_path)
            content = output_path.read_text(encoding="utf-8")
        finally:
            if output_path.exists():
                output_path.unlink()

        assert content.startswith("AI-GENERATED DRAFT"), (
            f"Report does not start with disclaimer. Got: {content[:120]!r}"
        )


# ---------------------------------------------------------------------------
# Test 3: PubMedClient returns [] when HTTP client always fails
# ---------------------------------------------------------------------------
def test_pubmed_search_returns_empty_list_after_bounded_failure():
    """
    PubMedClient.search_by_doi() must return an empty list (not raise)
    when its HTTP client returns None on every request.
    """
    stub_client = AlwaysFailHttpClient()
    pubmed = PubMedClient(http_client=stub_client)

    # Must not raise — must return []
    result = pubmed.search_by_doi("10.1234/nonexistent")
    assert result == [], f"Expected [], got {result!r}"
