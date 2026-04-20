from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from revision_tracker import RevisionTracker


class TestRevisionTrackerSecurity:
    def test_revision_tracker_save_sets_owner_only_permissions(self, tmp_path: Path) -> None:
        state_file = tmp_path / "pipeline_state.json"
        tracker = RevisionTracker(state_file)
        tracker.reviewer_count = 1
        tracker.save()

        mode = stat.S_IMODE(state_file.stat().st_mode)
        assert oct(mode) == "0o600"

    def test_revision_tracker_save_preserves_review_gate_metadata(self, tmp_path: Path) -> None:
        state_file = tmp_path / "pipeline_state.json"
        tracker = RevisionTracker(state_file)

        review_gates = {
            "response_letter.md": {
                "status": "human_review_required",
                "approved": False,
                "reviewed_by": None,
                "review_timestamp": None,
            },
        }
        tracker.save(review_gates=review_gates)

        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert (
            data["security"]["review_gates"]["response_letter.md"]["approved"] is False
        )
