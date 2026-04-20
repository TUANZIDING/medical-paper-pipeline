from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.error import HTTPError, URLError
import urllib.request
from urllib.request import Request


DISCLAIMER_HEADER = (
    "AI-GENERATED DRAFT\n"
    "This content is a machine-generated draft and requires human review.\n\n"
)


@dataclass(frozen=True)
class PHIFinding:
    kind: str
    value: str


class PHIGuard:
    _PATTERNS = [
        ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
        (
            "phone",
            re.compile(
                r"(?<!\w)(?:\+?1[-.\s]*)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b"
            ),
        ),
        # Only flag ISO dates near patient-related keywords to avoid false positives
        # on publication dates, study periods, etc.
        ("date", re.compile(
            r"(?:patient|dob|birth|admission|discharge|onset|diagnosis|surgery|procedure|death|visit|followup|follow-up|outcome)\s*(?:date[s]?)?\s*:?\s*(\d{4}-\d{2}-\d{2})",
            re.IGNORECASE,
        )),
        ("mrn", re.compile(r"\bMRN[:\s#-]*(\d{6,10})\b", re.IGNORECASE)),
    ]

    def find(self, text: str) -> List[PHIFinding]:
        findings: List[PHIFinding] = []
        for kind, pattern in self._PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1) if kind in ("mrn", "date") and match.lastindex else match.group(0)
                findings.append(PHIFinding(kind=kind, value=value))
        return findings

    def redact(self, text: str) -> str:
        redacted = text
        for kind, pattern in self._PATTERNS:
            placeholder = f"[REDACTED_{kind.upper()}]"
            if kind == "mrn":
                redacted = pattern.sub(lambda match: match.group(0).replace(match.group(1), placeholder), redacted)
            else:
                redacted = pattern.sub(placeholder, redacted)
        return redacted


class SafePathPolicy:
    _ALLOWED_TOP_LEVEL_FILES = {"pipeline_state.json"}
    _ALLOWED_TOP_LEVEL_DIRS = {"figures", "outputs", "logs"}

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()

    def is_allowed(self, path: Path) -> bool:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.repo_root / candidate
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            return False

        try:
            relative = resolved.relative_to(self.repo_root)
        except ValueError:
            return False

        if not relative.parts:
            return False

        top_level = relative.parts[0]
        if len(relative.parts) == 1 and top_level in self._ALLOWED_TOP_LEVEL_FILES:
            return True
        return top_level in self._ALLOWED_TOP_LEVEL_DIRS


def prepend_disclaimer(text: str) -> str:
    if text.startswith(DISCLAIMER_HEADER):
        return text
    return f"{DISCLAIMER_HEADER}{text}"


def chmod_owner_only(path: Path) -> None:
    os.chmod(Path(path), 0o600)


class SafeHttpClient:
    def __init__(self, retries: int = 3, timeout: float = 5.0):
        self.retries = max(1, retries)
        self.timeout = timeout

    def fetch_text(self, url: str) -> Tuple[Optional[str], Optional[Exception]]:
        request = Request(url, headers={"User-Agent": "medical-paper-pipeline/guardrails"})
        last_error: Optional[Exception] = None
        for _ in range(self.retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    return response.read().decode(charset, errors="replace"), None
            except (URLError, HTTPError) as exc:
                last_error = exc
        return None, last_error


def mark_review_required(state: dict, artifact_name: str) -> None:
    state.setdefault("security", {})
    state["security"].setdefault("review_gates", {})
    state["security"]["review_gates"][artifact_name] = {
        "status": "human_review_required",
        "approved": False,
        "reviewed_by": None,
        "review_timestamp": None,
    }


def approve_review(state: dict, artifact_name: str, reviewer: str) -> None:
    if "security" not in state or artifact_name not in state["security"].get("review_gates", {}):
        raise KeyError(artifact_name)
    state["security"]["review_gates"][artifact_name] = {
        "status": "human_review_approved",
        "approved": True,
        "reviewed_by": reviewer,
        "review_timestamp": datetime.utcnow().isoformat(),
    }


def block_if_review_not_approved(state: dict, artifact_name: str) -> None:
    gates = state.get("security", {}).get("review_gates", {})
    entry = gates.get(artifact_name, {})
    if entry.get("status") != "human_review_approved":
        raise ValueError(f"Artifact '{artifact_name}' review has not been approved.")
