#!/usr/bin/env python3
"""
doi_verifier.py
===============
DOI verification and PubMed-backed reference validation for the medical-paper-pipeline skill.

Workflow:
  1. Extract DOIs from raw reference strings (handles 10+ formats)
  2. For each DOI:
     a. Query PubMed E-utilities (efetch) → get PMID, title, authors, year, journal
     b. If PubMed fails → fall back to CrossRef API
     c. If both fail → mark NEEDS_REVIEW
  3. Cross-validate: DOI→PMID→metadata consistency check
  4. Output verification report

Rate limit: 3 req/sec for PubMed (E-utilities), no limit for CrossRef.

Usage (import as module):
    from doi_verifier import DOIVerifier, VerificationStatus
    verifier = DOIVerifier(cache_dir=".doi_cache")
    report = verifier.verify_references(raw_references)
    for entry in report:
        print(entry.status, entry.doi, entry.pmid)

CLI usage:
    python doi_verifier.py references.txt -o verification_report.md
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# ─── Constants ────────────────────────────────────────────────────────────────

PUBMED_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CROSSREF_API_BASE = "https://api.crossref.org/works"

# PubMed rate limit: 3 requests/second (with API key: 10/s)
PUBMED_RATE_LIMIT = 3  # seconds between requests
PUBMED_DELAY_PER_REQUEST = 1.0 / 3.0

# CrossRef polite pool: add mailto for polite mode (higher rate limits)
CROSSREF_HEADERS = {
    "User-Agent": "MedicalPaperPipeline/1.0 (mailto:your_email@example.com)",
}

# Timeout for all HTTP requests
REQUEST_TIMEOUT = 15  # seconds

# Cache TTL: 7 days
CACHE_TTL_SECONDS = 7 * 24 * 3600


# ─── Enums & Dataclasses ──────────────────────────────────────────────────────


class VerificationStatus(Enum):
    """Verification result status codes."""

    PASS = "PASS"              # DOI verified, metadata consistent
    FIXED = "FIXED"           # DOI auto-corrected (e.g., format fix)
    NEEDS_REVIEW = "NEEDS_REVIEW"  # Manual check required
    ERROR = "ERROR"            # Verification failed (no API response)
    NO_DOI = "NO_DOI"         # No DOI found in reference string


@dataclass
class VerificationEntry:
    """
    Result of verifying a single reference.

    Fields:
        status:           VerificationStatus enum value
        original_text:    The raw reference string as provided
        doi:             Extracted DOI (or None if not found)
        pmid:            PubMed ID (or None if not found in PubMed)
        doi_resolved:    Final DOI used (may differ from extracted if auto-fixed)
        title:           Article title from PubMed/CrossRef
        authors:         List of author names
        year:            Publication year
        journal:         Journal name (abbreviated)
        volume:          Volume number
        issue:           Issue number
        pages:           Page range
        url:             Direct URL (https://doi.org/xxx)
        correction_note:  Human-readable note about what was changed/flagged
        error_message:   Error detail if status is ERROR
        matched:         bool — DOI→PMID metadata matched (True/False/None)
        source:          "pubmed" | "crossref" | "none" — where metadata came from
    """

    status: VerificationStatus = VerificationStatus.NO_DOI
    original_text: str = ""
    doi: str | None = None
    pmid: str | None = None
    doi_resolved: str | None = None
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    journal: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    url: str = ""
    correction_note: str = ""
    error_message: str = ""
    matched: bool | None = None
    source: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "original_text": self.original_text,
            "doi": self.doi,
            "pmid": self.pmid,
            "doi_resolved": self.doi_resolved,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "journal": self.journal,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "url": self.url,
            "correction_note": self.correction_note,
            "error_message": self.error_message,
            "matched": self.matched,
            "source": self.source,
        }


@dataclass
class VerificationReport:
    """
    Complete verification report for a batch of references.
    """

    entries: list[VerificationEntry] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    fixed: int = 0
    needs_review: int = 0
    errors: int = 0
    no_doi: int = 0

    def summarize(self) -> dict[str, int]:
        self.passed = sum(1 for e in self.entries if e.status == VerificationStatus.PASS)
        self.fixed = sum(1 for e in self.entries if e.status == VerificationStatus.FIXED)
        self.needs_review = sum(
            1 for e in self.entries if e.status == VerificationStatus.NEEDS_REVIEW
        )
        self.errors = sum(1 for e in self.entries if e.status == VerificationStatus.ERROR)
        self.no_doi = sum(
            1 for e in self.entries if e.status == VerificationStatus.NO_DOI
        )
        self.total = len(self.entries)
        return {
            "total": self.total,
            "PASS": self.passed,
            "FIXED": self.fixed,
            "NEEDS_REVIEW": self.needs_review,
            "ERROR": self.errors,
            "NO_DOI": self.no_doi,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summarize(),
            "entries": [e.to_dict() for e in self.entries],
        }


# ─── DOI Extraction ─────────────────────────────────────────────────────────


class DOIExtractor:
    """
    Extracts DOI from raw reference strings using regex patterns.

    Handles common formats:
      - https://doi.org/10.1234/abc123
      - doi: 10.1234/abc123
      - 10.1234/abc123
      - (10.1234/abc123)
      - https://pubmed.ncbi.nlm.nih.gov/12345678/  (extracts DOI if present)
    """

    # Primary pattern: starts with 10. + registrant code + slash + suffix
    # Handles dots, hyphens, slashes in suffix, stops at common trailing chars
    DOI_PATTERN = re.compile(
        r"\b(?:doi[:\s]*(?:https?://(?:dx\.)?doi\.org/)?)\s*"
        r"(10\.\d{4,}(?:\.\d+)*/\S+?)"
        r"(?=\s*[,;)\]]|$)",
        re.IGNORECASE,
    )
    # Bare DOI (no prefix)
    BARE_DOI_PATTERN = re.compile(
        r"(?<![a-zA-Z0-9])"
        r"(10\.\d{4,}(?:\.\d+)*/\S+?)"
        r"(?=\s*[,;)\]]|$)",
    )

    def extract(self, text: str) -> str | None:
        """
        Extract DOI from a reference string.

        Returns the cleaned DOI (lowercase) or None if not found.
        Applies auto-fixes for common format errors.
        """
        if not text:
            return None

        # Try primary pattern first
        match = self.DOI_PATTERN.search(text)
        if match:
            doi = match.group(1).strip()
            return self._clean_doi(doi)

        # Fall back to bare DOI
        match = self.BARE_DOI_PATTERN.search(text)
        if match:
            doi = match.group(1).strip()
            # Be more conservative with bare pattern — verify it looks like a DOI
            if doi.startswith("10."):
                return self._clean_doi(doi)

        return None

    def _clean_doi(self, doi: str) -> str:
        """
        Normalize a DOI string:
        - Strip trailing punctuation
        - Strip trailing URL fragments (#page, ?format, etc.)
        - Lowercase
        """
        # Remove trailing punctuation that's not part of the DOI
        doi = doi.rstrip(".,;:")
        # Remove common URL parameters/fragments that get appended
        doi = re.sub(r"[#?].*$", "", doi)
        # Strip any whitespace
        doi = doi.strip()
        return doi.lower()

    def extract_all(self, texts: list[str]) -> list[str | None]:
        """Extract DOIs from multiple reference strings."""
        return [self.extract(t) for t in texts]


# ─── Rate Limiter ─────────────────────────────────────────────────────────────


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter for PubMed API calls.

    Configured for 3 requests/second (PubMed public limit).
    With API key: 10 requests/second (not implemented here).
    """

    def __init__(self, rate: float = 1.0 / 3.0):
        """
        Args:
            rate: Minimum seconds between requests (default: 1/3 for 3 req/sec).
        """
        self.rate = rate
        self.last_request_time: float | None = None

    def wait(self) -> None:
        """Block until enough time has passed since the last request."""
        if self.last_request_time is None:
            self.last_request_time = time.monotonic()
            return

        elapsed = time.monotonic() - self.last_request_time
        if elapsed < self.rate:
            time.sleep(self.rate - elapsed)

        self.last_request_time = time.monotonic()


# ─── HTTP Utilities ──────────────────────────────────────────────────────────


class HTTPClient:
    """Simple HTTP client with timeout, error handling, and JSON/XML support."""

    def __init__(self, timeout: int = REQUEST_TIMEOUT):
        self.timeout = timeout

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict | None:
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return None

    def get_text(self, url: str, headers: dict[str, str] | None = None) -> str | None:
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception:
            return None


# ─── PubMed API ──────────────────────────────────────────────────────────────


class PubMedClient:
    """
    PubMed E-utilities API client.

    Workflow for DOI → PMID:
      1. esearch?db=pubmed&term=doi[-aid]  → get PMID list
      2. efetch?db=pubmed&id=PMID           → get full metadata XML

    Requires rate limiting (3 req/sec without API key).
    """

    def __init__(self, http_client: HTTPClient | None = None, api_key: str | None = None):
        self.http = http_client or HTTPClient()
        self.api_key = api_key or os.environ.get("NCBI_API_KEY", "")
        self.rate_limiter = TokenBucketRateLimiter(rate=PUBMED_DELAY_PER_REQUEST)

    def _build_url(self, endpoint: str, params: dict[str, str]) -> str:
        """Build PubMed E-utilities URL with optional API key."""
        base_params = {"retmode": "json", "tool": "medical_paper_pipeline"}
        if self.api_key:
            base_params["api_key"] = self.api_key
        base_params.update(params)
        query = urllib.parse.urlencode(base_params)
        return f"{PUBMED_EUTILS_BASE}/{endpoint}.efetch?{query}"

    def search_by_doi(self, doi: str) -> list[str]:
        """
        Search PubMed for a DOI and return matching PMIDs.

        Returns list of PMIDs (usually 0 or 1 for a DOI).
        """
        self.rate_limiter.wait()

        url = (
            f"{PUBMED_EUTILS_BASE}/esearch.fcgi"
            f"?db=pubmed&term={urllib.parse.quote(doi)}[DOI]&retmode=json"
        )
        if self.api_key:
            url += f"&api_key={self.api_key}"

        result = self.http.get_json(url)
        if not result:
            return []

        try:
            ids = result.get("esearchresult", {}).get("idlist", [])
            return ids
        except (KeyError, TypeError):
            return []

    def fetch_metadata(self, pmid: str) -> dict[str, Any] | None:
        """
        Fetch full article metadata from PubMed by PMID.

        Returns a dict with: title, authors, year, journal, volume, issue, pages, doi
        """
        self.rate_limiter.wait()

        # Fetch XML (efetch returns XML, not JSON for article metadata)
        url = (
            f"{PUBMED_EUTILS_BASE}/efetch.fcgi"
            f"?db=pubmed&id={pmid}&retmode=xml"
        )
        if self.api_key:
            url += f"&api_key={self.api_key}"

        xml_text = self.http.get_text(url)
        if not xml_text:
            return None

        return self._parse_pubmed_xml(xml_text)

    def _parse_pubmed_xml(self, xml_text: str) -> dict[str, Any]:
        """Parse PubMed Efetch XML to extract article metadata."""
        try:
            import xml.etree.ElementTree as ET

            root = ET.fromstring(xml_text)
            article = root.find(".//Article")
            if article is None:
                return {}

            # Title
            title_el = article.find("ArticleTitle")
            title = "".join(title_el.itertext()) if title_el is not None else ""

            # Journal
            journal_el = article.find("Journal/Title")
            journal = journal_el.text if journal_el is not None else ""
            # ISO abbreviation if available
            journal_abbr_el = article.find("Journal/ISOAbbreviation")
            if journal_abbr_el is not None and journal_abbr_el.text:
                journal = journal_abbr_el.text

            # Volume / Issue / Pages
            volume_el = article.find("Journal/JournalIssue/Volume")
            volume = volume_el.text if volume_el is not None else ""
            issue_el = article.find("Journal/JournalIssue/Issue")
            issue = issue_el.text if issue_el is not None else ""
            pages_el = article.find("Pagination/MedlinePgn")
            pages = pages_el.text if pages_el is not None else ""

            # Year — try PubDate first, then ArticleDate, then JournalIssue PubDate
            year = ""
            for date_path in [
                "Journal/JournalIssue/PubDate/Year",
                "ArticleDate/Year",
                "Journal/JournalIssue/PubDate/MedlineDate",
            ]:
                year_el = article.find(date_path)
                if year_el is not None and year_el.text:
                    year = year_el.text
                    # Extract 4-digit year if it's a range like "2023-2024"
                    y_match = re.search(r"(\d{4})", year)
                    if y_match:
                        year = y_match.group(1)
                    break

            # Authors
            authors = []
            author_list_el = article.find("AuthorList")
            if author_list_el is not None:
                for author_el in author_list_el.findall("Author"):
                    last_name = author_el.findtext("LastName", "")
                    fore_name = author_el.findtext("ForeName", "")
                    initials = author_el.findtext("Initials", "")
                    if last_name:
                        if fore_name:
                            authors.append(f"{fore_name} {last_name}")
                        elif initials:
                            authors.append(f"{initials} {last_name}")
                        else:
                            authors.append(last_name)

            # DOI — search ArticleIdList
            doi = ""
            article_ids = article.find("ArticleIdList")
            if article_ids is not None:
                for aid in article_ids.findall("ArticleId"):
                    if aid.get("IdType") == "doi":
                        doi = aid.text or ""
                        break

            return {
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
                "volume": volume,
                "issue": issue,
                "pages": pages,
                "doi": doi.lower(),
            }
        except Exception:
            return {}

    def resolve_doi(self, doi: str) -> tuple[str | None, dict[str, Any] | None]:
        """
        Resolve a DOI to PubMed metadata.

        Args:
            doi: The DOI string (lowercase).

        Returns:
            Tuple of (pmid, metadata_dict). pmid is None if not found.
            metadata_dict contains: title, authors, year, journal, volume, issue, pages, doi
        """
        pmids = self.search_by_doi(doi)
        if not pmids:
            return None, None

        pmid = pmids[0]
        metadata = self.fetch_metadata(pmid)
        return pmid, metadata


# ─── CrossRef API ────────────────────────────────────────────────────────────


class CrossRefClient:
    """
    CrossRef API client for DOI resolution (fallback when PubMed fails).

    CrossRef has no strict rate limit but requires a User-Agent with contact info
    (polite pool). Use the mailto parameter for higher rate limits.
    """

    def __init__(self, http_client: HTTPClient | None = None, email: str | None = None):
        self.http = http_client or HTTPClient()
        self.email = email or os.environ.get("CROSSREF_EMAIL", "")
        self.headers = dict(CROSSREF_HEADERS)
        if self.email:
            self.headers["User-Agent"] = (
                f"MedicalPaperPipeline/1.0 (mailto:{self.email})"
            )

    def resolve_doi(self, doi: str) -> dict[str, Any] | None:
        """
        Resolve a DOI via CrossRef API.

        Returns a dict with: title, authors, year, journal, volume, issue, pages, doi
        Returns None if DOI not found or API error.
        """
        url = f"{CROSSREF_API_BASE}/{urllib.parse.quote(doi)}"
        # Add mailto param for polite pool
        if self.email:
            url += f"?mailto={urllib.parse.quote(self.email)}"

        result = self.http.get_json(url, headers=self.headers)
        if not result:
            return None

        try:
            message = result.get("message", {})
            return self._parse_crossref(message, doi.lower())
        except (KeyError, TypeError):
            return None

    def _parse_crossref(self, message: dict, original_doi: str) -> dict[str, Any]:
        """Parse CrossRef API response to standard metadata dict."""
        # Title
        title_list = message.get("title", [])
        title = title_list[0] if title_list else ""

        # Authors
        authors = []
        for author in message.get("author", []):
            given = author.get("given", "")
            family = author.get("family", "")
            if family:
                if given:
                    authors.append(f"{given} {family}")
                else:
                    authors.append(family)

        # Year
        published = message.get("published-print") or message.get("published-online") or {}
        date_parts = published.get("date-parts", [[]])
        year = ""
        if date_parts and date_parts[0]:
            year = str(date_parts[0][0])

        # Journal
        container = message.get("container-title", [])
        journal = container[0] if container else ""

        # Volume / Issue / Pages
        volume = message.get("volume", "")
        issue = message.get("issue", "")
        pages = message.get("page", "")

        # DOI (canonical form from CrossRef)
        doi = message.get("DOI", original_doi)

        return {
            "title": title,
            "authors": authors,
            "year": year,
            "journal": journal,
            "volume": volume,
            "issue": issue,
            "pages": pages,
            "doi": doi.lower() if doi else original_doi,
        }


# ─── Metadata Consistency Checker ────────────────────────────────────────────


class MetadataConsistencyChecker:
    """
    Checks consistency between DOI metadata and reference metadata.

    Checks:
    1. DOI string normalized match
    2. Title word overlap (at least 3 non-stopword words in common)
    3. Year match (if available in reference)
    4. Journal name similarity
    """

    STOPWORDS = {
        "a", "an", "the", "of", "in", "on", "for", "to", "and", "or",
        "with", "by", "from", "is", "as", "at", "be", "are", "was",
        "were", "been", "being", "this", "that", "these", "those",
    }

    def check(
        self,
        extracted_doi: str,
        metadata: dict[str, Any],
        reference_text: str,
    ) -> tuple[bool, str]:
        """
        Check metadata consistency.

        Returns:
            Tuple of (consistent: bool, reason: str)
        """
        reasons = []
        issues = []

        # 1. DOI format normalization check
        # If metadata has a DOI, check it's the same (normalized)
        meta_doi = metadata.get("doi", "").lower().strip()
        if meta_doi:
            # Normalize both DOIs for comparison
            norm_extracted = self._normalize_doi(extracted_doi)
            norm_meta = self._normalize_doi(meta_doi)
            if norm_extracted != norm_meta:
                issues.append(
                    f"DOI mismatch: extracted={norm_extracted}, metadata={norm_meta}"
                )

        # 2. Title overlap check
        title = metadata.get("title", "")
        if title:
            overlap = self._title_overlap(title, reference_text)
            if overlap < 3:
                issues.append(f"Title overlap too low: {overlap} words (need ≥3)")

        # 3. Year check
        year = metadata.get("year", "")
        if year and year not in reference_text:
            # Allow some flexibility — check if any year-like number is in reference
            ref_years = re.findall(r"\b(19|20)\d{2}\b", reference_text)
            if year not in ref_years:
                reasons.append(f"Year {year} not found in reference text")

        # 4. Journal name check
        journal = metadata.get("journal", "")
        if journal:
            journal_short = journal.split(".")[0].strip()
            if journal_short.lower() not in reference_text.lower():
                reasons.append(f"Journal '{journal_short}' not clearly in reference")

        consistent = len(issues) == 0
        reason = "; ".join(issues) if issues else "; ".join(reasons) if reasons else "Consistent"
        return consistent, reason

    def _normalize_doi(self, doi: str) -> str:
        """Normalize DOI for comparison: lowercase, strip, remove https://doi.org/ prefix."""
        doi = doi.lower().strip()
        doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
        return doi

    def _title_overlap(self, title: str, reference: str) -> int:
        """Count overlapping significant words between title and reference text."""
        title_words = set(
            w.lower().strip(".,;:()[]{}")
            for w in title.split()
            if len(w) > 3 and w.lower() not in self.STOPWORDS
        )
        ref_lower = reference.lower()
        return sum(1 for w in title_words if w in ref_lower)


# ─── Main Verifier ───────────────────────────────────────────────────────────


class DOIVerifier:
    """
    Main DOI verification orchestrator.

    Coordinates: DOI extraction → PubMed → CrossRef fallback → consistency check
    Caches results to avoid re-querying the same DOI within 7 days.

    Usage:
        verifier = DOIVerifier(cache_dir=".doi_cache")
        report = verifier.verify_references(ref_list)
        verifier.save_report(report, "verification_report.md")
    """

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        email: str | None = None,
        pubmed_api_key: str | None = None,
    ):
        """
        Args:
            cache_dir: Directory for caching API responses. Defaults to .doi_cache
                       in the current working directory.
            email: Email for CrossRef polite pool (and optionally PubMed API key).
            pubmed_api_key: NCBI API key for higher PubMed rate limits (10 req/s).
        """
        self.cache_dir = Path(cache_dir) if cache_dir else Path(".doi_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.email = email
        self.pubmed_api_key = pubmed_api_key

        self.extractor = DOIExtractor()
        self.pubmed = PubMedClient(api_key=pubmed_api_key)
        self.crossref = CrossRefClient(email=email)
        self.checker = MetadataConsistencyChecker()

    # ─── Cache ─────────────────────────────────────────────────────────────

    def _cache_path(self, doi: str) -> Path:
        """Get cache file path for a DOI."""
        # Sanitize DOI for filesystem
        safe = re.sub(r"[^\w\-.~]", "_", doi)
        return self.cache_dir / f"{safe}.json"

    def _cache_get(self, doi: str) -> dict[str, Any] | None:
        """Load cached metadata for a DOI if fresh."""
        path = self._cache_path(doi)
        if not path.exists():
            return None

        try:
            age = time.time() - path.stat().st_mtime
            if age > CACHE_TTL_SECONDS:
                return None  # expired
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _cache_set(self, doi: str, data: dict[str, Any]) -> None:
        """Save metadata to cache."""
        try:
            path = self._cache_path(doi)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # Cache write failure is non-fatal

    # ─── Core verification ─────────────────────────────────────────────────

    def verify_reference(self, reference_text: str) -> VerificationEntry:
        """
        Verify a single reference string.

        Returns a VerificationEntry with the result.
        """
        entry = VerificationEntry(original_text=reference_text)

        # Step 1: Extract DOI
        doi = self.extractor.extract(reference_text)
        if doi is None:
            entry.status = VerificationStatus.NO_DOI
            entry.correction_note = "No DOI found in reference string"
            return entry

        entry.doi = doi
        entry.doi_resolved = doi

        # Step 2: Check cache
        cached = self._cache_get(doi)
        if cached:
            self._apply_cached(entry, cached)
            return entry

        # Step 3: Query PubMed
        pmid, metadata = self.pubmed.resolve_doi(doi)

        if metadata:
            entry.pmid = pmid
            entry.source = "pubmed"
            self._populate_entry(entry, metadata)

            # Step 4: Consistency check
            consistent, reason = self.checker.check(doi, metadata, reference_text)
            entry.matched = consistent
            if consistent:
                entry.status = VerificationStatus.PASS
            else:
                entry.status = VerificationStatus.NEEDS_REVIEW
                entry.correction_note = f"Consistency issue: {reason}"

            # Cache the result
            cache_data = {
                "pmid": pmid,
                "source": "pubmed",
                "metadata": metadata,
                "matched": consistent,
                "verified_at": time.time(),
            }
            self._cache_set(doi, cache_data)
            return entry

        # Step 5: PubMed failed — try CrossRef
        metadata = self.crossref.resolve_doi(doi)

        if metadata:
            entry.source = "crossref"
            self._populate_entry(entry, metadata)

            # CrossRef doesn't have PMID — mark as "no PMID" but still verify
            # Check title overlap at minimum
            consistent, reason = self.checker.check(doi, metadata, reference_text)
            entry.matched = consistent
            if consistent:
                entry.status = VerificationStatus.PASS
                entry.correction_note = "Verified via CrossRef (PubMed not found)"
            else:
                entry.status = VerificationStatus.NEEDS_REVIEW
                entry.correction_note = (
                    f"CrossRef verified but consistency issue: {reason}"
                )

            cache_data = {
                "pmid": None,
                "source": "crossref",
                "metadata": metadata,
                "matched": consistent,
                "verified_at": time.time(),
            }
            self._cache_set(doi, cache_data)
            return entry

        # Step 6: Both failed
        entry.status = VerificationStatus.ERROR
        entry.error_message = "Both PubMed and CrossRef returned no results for this DOI"
        entry.correction_note = "DOI could not be verified — manual check required"

        cache_data = {
            "pmid": None,
            "source": "none",
            "metadata": {},
            "matched": None,
            "verified_at": time.time(),
        }
        self._cache_set(doi, cache_data)
        return entry

    def verify_references(
        self, references: list[str]
    ) -> VerificationReport:
        """
        Verify a list of reference strings.

        Returns a VerificationReport with summary and per-entry results.
        """
        report = VerificationReport()

        for ref in references:
            entry = self.verify_reference(ref)
            report.entries.append(entry)

        report.summarize()
        return report

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _populate_entry(self, entry: VerificationEntry, metadata: dict) -> None:
        """Fill entry fields from a metadata dict."""
        entry.title = metadata.get("title", "")
        entry.authors = metadata.get("authors", [])
        entry.year = metadata.get("year", "")
        entry.journal = metadata.get("journal", "")
        entry.volume = metadata.get("volume", "")
        entry.issue = metadata.get("issue", "")
        entry.pages = metadata.get("pages", "")
        if entry.doi_resolved:
            entry.url = f"https://doi.org/{entry.doi_resolved}"

    def _apply_cached(self, entry: VerificationEntry, cached: dict) -> None:
        """Populate entry from cache data."""
        metadata = cached.get("metadata", {})
        entry.pmid = cached.get("pmid")
        entry.source = cached.get("source", "none")
        entry.matched = cached.get("matched")
        self._populate_entry(entry, metadata)

        # Re-check consistency with current reference if cached was inconsistent
        if cached.get("matched") is False:
            entry.status = VerificationStatus.NEEDS_REVIEW
            consistent, reason = self.checker.check(
                entry.doi or "", metadata, entry.original_text
            )
            if consistent:
                # Cached was inconsistent but now reference text matches
                entry.status = VerificationStatus.FIXED
                entry.correction_note = f"Previously flagged but re-checked: {reason}"
            entry.matched = consistent
        else:
            entry.status = VerificationStatus.PASS

    # ─── Output formatting ─────────────────────────────────────────────────

    def format_report_markdown(
        self, report: VerificationReport
    ) -> str:
        """
        Format a verification report as a markdown table.

        Output:
        - Summary bar (PASS / FIXED / NEEDS_REVIEW / ERROR counts)
        - Per-reference table with status, DOI, PMID, title, year, journal
        """
        summary = report.summarize()

        lines = [
            "# Reference Verification Report\n",
            f"**Total references:** {summary['total']}  "
            f"**PASS:** {summary['PASS']}  "
            f"**FIXED:** {summary['FIXED']}  "
            f"**NEEDS_REVIEW:** {summary['NEEDS_REVIEW']}  "
            f"**ERROR:** {summary['ERROR']}  "
            f"**NO_DOI:** {summary['NO_DOI']}\n",
            "## Detail Table\n",
            "| # | Status | DOI | PMID | Title | Year | Journal | Source | Note |",
            "|--:|--------|-----|------|-------|------|---------|--------|------|",
        ]

        for i, entry in enumerate(report.entries, 1):
            status_icon = self._status_icon(entry.status)
            status_str = f"{status_icon} {entry.status.value}"

            # Truncate title
            title_short = entry.title[:60] + "..." if len(entry.title) > 60 else entry.title

            # Journal abbreviated
            journal_short = entry.journal[:40] if entry.journal else ""

            # Note (truncated)
            note = entry.correction_note or entry.error_message or ""
            note_short = note[:50] + "..." if len(note) > 50 else note

            # Authors summary
            authors_str = ""
            if entry.authors:
                if len(entry.authors) > 2:
                    authors_str = f"{entry.authors[0]} et al."
                else:
                    authors_str = "; ".join(entry.authors)

            lines.append(
                f"| {i} | {status_str} | `{entry.doi or 'N/A'}` | "
                f"{entry.pmid or '—'} | {title_short} | "
                f"{entry.year or '—'} | {journal_short} | {entry.source} | {note_short} |"
            )

        # Add legend
        lines.extend(
            [
                "\n## Status Legend\n",
                "| Symbol | Meaning |",
                "|--------|---------|",
                "| :white_check_mark: PASS | DOI verified, metadata consistent |",
                "| :wrench: FIXED | DOI auto-corrected or previously flagged but now verified |",
                "| :warning: NEEDS_REVIEW | Manual check required — possible mismatch |",
                "| :x: ERROR | Both PubMed and CrossRef failed |",
                "| :question: NO_DOI | No DOI found in reference string |",
                "\n## References Requiring Review\n",
            ]
        )

        # List only NEEDS_REVIEW and ERROR entries in detail
        for i, entry in enumerate(
            [
                e
                for e in report.entries
                if e.status
                in (VerificationStatus.NEEDS_REVIEW, VerificationStatus.ERROR)
            ],
            1,
        ):
            lines.append(f"\n### {i}. {entry.status.value}\n")
            lines.append(f"**Original text:** {entry.original_text}\n")
            if entry.doi:
                lines.append(f"**DOI:** `{entry.doi}`\n")
            if entry.pmid:
                lines.append(f"**PMID:** {entry.pmid}\n")
            if entry.title:
                lines.append(f"**Title:** {entry.title}\n")
            if entry.authors:
                lines.append(f"**Authors:** {', '.join(entry.authors[:3])}\n")
            if entry.year:
                lines.append(f"**Year:** {entry.year}\n")
            if entry.journal:
                lines.append(f"**Journal:** {entry.journal}\n")
            if entry.correction_note:
                lines.append(f"**Note:** {entry.correction_note}\n")
            if entry.error_message:
                lines.append(f"**Error:** {entry.error_message}\n")

        return "\n".join(lines)

    def _status_icon(self, status: VerificationStatus) -> str:
        icons = {
            VerificationStatus.PASS: "✅",
            VerificationStatus.FIXED: "🔧",
            VerificationStatus.NEEDS_REVIEW: "⚠️",
            VerificationStatus.ERROR: "❌",
            VerificationStatus.NO_DOI: "❓",
        }
        return icons.get(status, "❓")

    def save_report(
        self, report: VerificationReport, output_path: str | Path
    ) -> None:
        """Save verification report to markdown file."""
        content = self.format_report_markdown(report)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # ─── Convenience: verify file of references ─────────────────────────────

    def verify_file(self, input_path: str | Path) -> VerificationReport:
        """
        Read references from a text file (one per line) and verify all.

        Handles:
        - Plain text files (one reference per line)
        - JSON files: {"references": ["ref1", "ref2", ...]}
        """
        path = Path(input_path)
        text = path.read_text(encoding="utf-8").strip()

        # Try JSON
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "references" in data:
                references = data["references"]
            elif isinstance(data, list):
                references = data
            else:
                references = text.splitlines()
        except json.JSONDecodeError:
            # Plain text: one reference per line, skip empty lines
            references = [line.strip() for line in text.splitlines() if line.strip()]

        return self.verify_references(references)


# ─── CLI entry point ─────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify DOIs and reference metadata via PubMed + CrossRef.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input",
        help="Input file (plain text, one ref/line; or JSON with 'references' key)",
    )
    parser.add_argument(
        "-o", "--output",
        default="reference_verification_report.md",
        help="Output markdown report path (default: reference_verification_report.md)",
    )
    parser.add_argument(
        "--cache-dir",
        default=".doi_cache",
        help="Cache directory for API responses (default: .doi_cache)",
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("CROSSREF_EMAIL", ""),
        help="Email for CrossRef polite pool (env: CROSSREF_EMAIL)",
    )
    parser.add_argument(
        "--pubmed-api-key",
        default=os.environ.get("NCBI_API_KEY", ""),
        help="NCBI API key for higher PubMed rate limits (env: NCBI_API_KEY)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of markdown",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only extract DOIs, don't query APIs (for debugging)",
    )

    args = parser.parse_args()

    verifier = DOIVerifier(
        cache_dir=args.cache_dir,
        email=args.email or None,
        pubmed_api_key=args.pubmed_api_key or None,
    )

    if args.list_only:
        # Quick DOI extraction only
        references = _load_references(args.input)
        extractor = DOIExtractor()
        for i, ref in enumerate(references, 1):
            doi = extractor.extract(ref)
            print(f"{i}. {doi or '(no DOI)'} → {ref[:80]}")
        return

    print(f"Verifying references from: {args.input}")
    report = verifier.verify_file(args.input)

    summary = report.summarize()
    print(f"\nSummary: {summary['total']} references checked")
    print(f"  PASS:         {summary['PASS']}")
    print(f"  FIXED:        {summary['FIXED']}")
    print(f"  NEEDS_REVIEW: {summary['NEEDS_REVIEW']}")
    print(f"  ERROR:        {summary['ERROR']}")
    print(f"  NO_DOI:       {summary['NO_DOI']}")

    if args.json:
        output_path = args.output.with_suffix(".json") if args.output else "verification_report.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"\nJSON report saved to: {output_path}")
    else:
        verifier.save_report(report, args.output)
        print(f"\nMarkdown report saved to: {args.output}")

    # Exit with non-zero if there are issues
    if summary["NEEDS_REVIEW"] > 0 or summary["ERROR"] > 0:
        sys.exit(1)


def _load_references(path: str | Path) -> list[str]:
    """Load references from a file (JSON or plain text)."""
    text = Path(path).read_text(encoding="utf-8").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "references" in data:
            return data["references"]
        elif isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    return [line.strip() for line in text.splitlines() if line.strip()]


if __name__ == "__main__":
    _cli()
