from pathlib import Path
from urllib.error import URLError

import pytest

from security_guardrails import (
    PHIGuard,
    SafeHttpClient,
    SafePathPolicy,
    chmod_owner_only,
    mark_review_required,
    approve_review,
    block_if_review_not_approved,
    prepend_disclaimer,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_phi_detection_finds_phone_email_and_date():
    text = "Contact 555-123-4567 or dr@example.com, patient DOB: 2026-04-17."

    findings = PHIGuard().find(text)

    values = {finding.value for finding in findings}
    kinds = {finding.kind for finding in findings}
    assert "555-123-4567" in values
    assert "dr@example.com" in values
    assert "2026-04-17" in values
    assert {"phone", "email", "date"}.issubset(kinds)


def test_phi_detection_finds_parenthesized_and_plus_one_phone_formats():
    text = "Call (555) 123-4567 or +1 (555) 123-4567 for updates."

    findings = PHIGuard().find(text)

    phones = {finding.value for finding in findings if finding.kind == "phone"}
    assert "(555) 123-4567" in phones
    assert "+1 (555) 123-4567" in phones


def test_phi_detection_does_not_treat_unlabeled_numeric_token_as_mrn():
    text = "Accession 1234567 reviewed on 2026-04-17."

    findings = PHIGuard().find(text)

    assert all(not (finding.kind == "mrn" and finding.value == "1234567") for finding in findings)


def test_phi_redaction_replaces_mrn_and_date():
    text = "MRN 1234567, patient admission date: 2026-04-17."

    redacted = PHIGuard().redact(text)

    assert "1234567" not in redacted
    assert "2026-04-17" not in redacted
    assert "[REDACTED_MRN]" in redacted
    assert "[REDACTED_DATE]" in redacted


def test_phi_redaction_replaces_parenthesized_and_plus_one_phone_formats():
    text = "Call (555) 123-4567 or +1 (555) 123-4567."

    redacted = PHIGuard().redact(text)

    assert "(555) 123-4567" not in redacted
    assert "+1 (555) 123-4567" not in redacted
    assert redacted.count("[REDACTED_PHONE]") == 2


def test_safe_path_policy_allows_figures_path():
    policy = SafePathPolicy(REPO_ROOT)

    allowed = policy.is_allowed(REPO_ROOT / "figures" / "plot.png")

    assert allowed is True


def test_safe_path_policy_allows_relative_path_from_repo_root():
    policy = SafePathPolicy(REPO_ROOT)

    allowed = policy.is_allowed(Path("figures/plot.png"))

    assert allowed is True


def test_safe_path_policy_rejects_escaped_path():
    policy = SafePathPolicy(REPO_ROOT)

    allowed = policy.is_allowed(REPO_ROOT / "outputs" / ".." / ".." / "secret.txt")

    assert allowed is False


def test_prepend_disclaimer_is_idempotent():
    body = "Draft content"

    once = prepend_disclaimer(body)
    twice = prepend_disclaimer(once)

    assert once == twice
    assert once.startswith("AI-GENERATED DRAFT")


def test_chmod_owner_only_sets_600(tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("sensitive", encoding="utf-8")

    chmod_owner_only(target)

    assert target.stat().st_mode & 0o777 == 0o600


def test_safe_http_client_returns_final_error_after_bounded_retries(monkeypatch):
    attempts = []

    def fake_urlopen(*args, **kwargs):
        attempts.append(1)
        raise URLError("network down")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = SafeHttpClient(retries=3, timeout=0.1)

    text, error = client.fetch_text("https://example.com")

    assert text is None
    assert isinstance(error, URLError)
    assert len(attempts) == 3


def test_mark_review_required_creates_security_section():
    state = {}
    mark_review_required(state, "statistical_results.md")

    assert "security" in state
    assert state["security"]["review_gates"]["statistical_results.md"]["status"] == "human_review_required"


def test_block_if_review_not_approved_raises_for_pending_artifact():
    state = {"security": {"review_gates": {"figures/draft.png": {"status": "pending"}}}}
    with pytest.raises(ValueError, match="review.*not.*approved"):
        block_if_review_not_approved(state, "figures/draft.png")


def test_block_if_review_not_approved_does_not_raise_for_approved_artifact():
    state = {"security": {"review_gates": {"figures/draft.png": {"status": "human_review_approved"}}}}
    block_if_review_not_approved(state, "figures/draft.png")  # should not raise
