#!/usr/bin/env python3
"""
revision_tracker.py
====================
Revision round tracker for the medical-paper-pipeline skill.

Tracks each reviewer comment across revision rounds, manages state transitions,
and persists tracking data in pipeline_state.json.

Usage (import as module):
    from revision_tracker import RevisionTracker
    tracker = RevisionTracker("pipeline_state.json")
    tracker.load()
    tracker.add_comment("R1-C1", "statistical", "Please clarify the missing data handling...")
    tracker.update_status("R1-C1", "addressed")
    tracker.save()

CLI usage:
    python revision_tracker.py pipeline_state.json --add "R1-C1" --type statistical
    python revision_tracker.py pipeline_state.json --list
    python revision_tracker.py pipeline_state.json --summary
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class CommentStatus(Enum):
    PENDING = "pending"
    ADDRESSED = "addressed"
    RESPONSE_DRAFTED = "response_drafted"
    CONFIRMED = "confirmed"
    NO_CHANGE = "no_change"


class RevisionStage(Enum):
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass
class TrackedComment:
    """
    A reviewer comment being tracked through revision rounds.

    Fields:
        id:              Unique comment ID (e.g. "R1-C1")
        reviewer_id:     Reviewer number
        round:           Which revision round this belongs to (R1/R2/R3)
        type:            Comment type (statistical/writing/reference/data/ethics/editorial)
        verbatim:        Original reviewer text
        response:        Drafted response
        status:          Current status (pending/addressed/response_drafted/confirmed)
        change_type:     text_revision | new_analysis | addition | no_change
        change_location: Manuscript location (e.g. "Page 5, Para 2")
        change_summary:  Brief description of change
        no_change_reason: Reason if no change was made
        priority:        major | minor
        history:         List of status change timestamps
    """

    id: str
    reviewer_id: int
    round: str = "R1"
    type: str = "writing"
    verbatim: str = ""
    response: str = ""
    status: str = "pending"
    change_type: str = "text_revision"
    change_location: str = ""
    change_summary: str = ""
    no_change_reason: str = ""
    priority: str = "major"
    history: list[dict] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrackedComment":
        return cls(**data)


@dataclass
class RevisionTracker:
    """
    Tracks all reviewer comments across revision rounds.

    Manages the full lifecycle: pending → addressed → response_drafted → confirmed.
    Persists to pipeline_state.json and supports multi-round tracking.
    """

    state_path: Path
    round: str = "R1"
    decision_type: str = "major_revision"
    reviewer_count: int = 0
    comments: list[TrackedComment] = field(default_factory=list)
    decision_letter_date: str = ""
    submitted_at: str = ""
    resolved_at: str = ""

    def __init__(self, state_path: str | Path):
        self.state_path = Path(state_path)

    # ─── Lifecycle ─────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load tracker state from pipeline_state.json."""
        if not self.state_path.exists():
            return

        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        stage5 = data.get("stage_5", {})
        self.round = stage5.get("round", "R1")
        self.decision_type = stage5.get("decision_type", "major_revision")
        self.reviewer_count = stage5.get("reviewer_count", 0)
        self.decision_letter_date = stage5.get("decision_letter_date", "")
        self.submitted_at = stage5.get("submitted_at", "")
        self.resolved_at = stage5.get("resolved_at", "")

        self.comments = []
        for c_data in stage5.get("comments", []):
            self.comments.append(TrackedComment.from_dict(c_data))

    def save(self) -> None:
        """Save tracker state to pipeline_state.json."""
        data = {}
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}

        stage5 = {
            "round": self.round,
            "decision_type": self.decision_type,
            "reviewer_count": self.reviewer_count,
            "decision_letter_date": self.decision_letter_date,
            "submitted_at": self.submitted_at,
            "resolved_at": self.resolved_at,
            "comments": [c.to_dict() for c in self.comments],
        }
        data["stage_5"] = stage5

        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ─── Comment management ───────────────────────────────────────────────

    def add_comment(
        self,
        comment_id: str,
        reviewer_id: int,
        verbatim: str,
        comment_type: str = "writing",
        priority: str = "major",
        round: str | None = None,
    ) -> TrackedComment:
        """Add a new comment to track."""
        c = TrackedComment(
            id=comment_id,
            reviewer_id=reviewer_id,
            verbatim=verbatim,
            type=comment_type,
            priority=priority,
            round=round or self.round,
        )
        self.comments.append(c)
        return c

    def get_comment(self, comment_id: str) -> TrackedComment | None:
        """Get a comment by ID."""
        for c in self.comments:
            if c.id == comment_id:
                return c
        return None

    def update_status(
        self,
        comment_id: str,
        new_status: str,
        response: str = "",
        change_type: str = "",
        location: str = "",
        summary: str = "",
        no_change_reason: str = "",
    ) -> bool:
        """Update a comment's status and related fields."""
        c = self.get_comment(comment_id)
        if c is None:
            return False

        old_status = c.status
        c.status = new_status
        c.updated_at = datetime.now().isoformat()

        if response:
            c.response = response
        if change_type:
            c.change_type = change_type
        if location:
            c.change_location = location
        if summary:
            c.change_summary = summary
        if no_change_reason:
            c.no_change_reason = no_change_reason

        # Record history
        c.history.append({
            "from": old_status,
            "to": new_status,
            "at": c.updated_at,
        })

        return True

    def remove_comment(self, comment_id: str) -> bool:
        """Remove a comment from tracking."""
        for i, c in enumerate(self.comments):
            if c.id == comment_id:
                self.comments.pop(i)
                return True
        return False

    # ─── Query ───────────────────────────────────────────────────────────

    def get_by_status(self, status: str) -> list[TrackedComment]:
        return [c for c in self.comments if c.status == status]

    def get_by_reviewer(self, reviewer_id: int) -> list[TrackedComment]:
        return [c for c in self.comments if c.reviewer_id == reviewer_id]

    def get_by_round(self, round: str) -> list[TrackedComment]:
        return [c for c in self.comments if c.round == round]

    def get_by_type(self, comment_type: str) -> list[TrackedComment]:
        return [c for c in self.comments if c.type == comment_type]

    def get_pending(self) -> list[TrackedComment]:
        return self.get_by_status(CommentStatus.PENDING.value)

    def get_unconfirmed(self) -> list[TrackedComment]:
        return [c for c in self.comments if c.status != CommentStatus.CONFIRMED.value]

    # ─── Round management ─────────────────────────────────────────────────

    def advance_round(self) -> str:
        """Advance to the next revision round."""
        round_order = ["R1", "R2", "R3"]
        try:
            idx = round_order.index(self.round)
            self.round = round_order[min(idx + 1, len(round_order) - 1)]
        except ValueError:
            self.round = "R1"
        return self.round

    def is_round_complete(self) -> bool:
        """Check if all comments in the current round are confirmed."""
        round_comments = self.get_by_round(self.round)
        if not round_comments:
            return False
        return all(c.status == CommentStatus.CONFIRMED.value for c in round_comments)

    def round_progress(self) -> dict[str, int]:
        """Get progress stats for the current round."""
        round_comments = self.get_by_round(self.round)
        total = len(round_comments)
        confirmed = sum(1 for c in round_comments if c.status == CommentStatus.CONFIRMED.value)
        addressed = sum(1 for c in round_comments if c.status == CommentStatus.ADDRESSED.value)
        pending = sum(1 for c in round_comments if c.status == CommentStatus.PENDING.value)
        return {
            "round": self.round,
            "total": total,
            "confirmed": confirmed,
            "addressed": addressed,
            "pending": pending,
            "percent_complete": round(confirmed / total * 100, 1) if total else 100,
        }

    # ─── Reporting ───────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Get a comprehensive summary of the tracking state."""
        total = len(self.comments)
        if total == 0:
            return {
                "round": self.round,
                "decision_type": self.decision_type,
                "total_comments": 0,
                "complete": True,
            }

        by_status = {
            "pending": sum(1 for c in self.comments if c.status == "pending"),
            "addressed": sum(1 for c in self.comments if c.status == "addressed"),
            "response_drafted": sum(1 for c in self.comments if c.status == "response_drafted"),
            "confirmed": sum(1 for c in self.comments if c.status == "confirmed"),
            "no_change": sum(1 for c in self.comments if c.status == "no_change"),
        }

        by_type = {}
        for c in self.comments:
            by_type[c.type] = by_type.get(c.type, 0) + 1

        by_reviewer = {}
        for c in self.comments:
            by_reviewer[c.reviewer_id] = by_reviewer.get(c.reviewer_id, 0) + 1

        return {
            "round": self.round,
            "decision_type": self.decision_type,
            "total_comments": total,
            "confirmed": by_status["confirmed"],
            "percent_complete": round(by_status["confirmed"] / total * 100, 1),
            "by_status": by_status,
            "by_type": by_type,
            "by_reviewer": by_reviewer,
            "complete": by_status["confirmed"] == total,
            "round_progress": self.round_progress(),
        }

    def render_markdown(self) -> str:
        """Render a human-readable tracking report."""
        s = self.summary()
        lines = [
            f"# Revision Tracking Report\n",
            f"**Round:** {s['round']}  **Decision:** {s['decision_type']}\n",
            f"**Total comments:** {s['total_comments']}\n",
        ]

        if s["total_comments"] == 0:
            lines.append("\nNo comments tracked yet.\n")
            return "\n".join(lines)

        lines.extend([
            f"**Confirmed:** {s['confirmed']}/{s['total_comments']} "
            f"({s['percent_complete']}%)\n",
            "\n## By Status\n",
        ])
        for status, count in s["by_status"].items():
            lines.append(f"- {status}: {count}")

        lines.extend(["\n## By Type\n"])
        for ctype, count in s.get("by_type", {}).items():
            lines.append(f"- {ctype}: {count}")

        lines.extend(["\n## By Reviewer\n"])
        for rid, count in s.get("by_reviewer", {}).items():
            lines.append(f"- Reviewer {rid}: {count}")

        lines.extend(["\n## Comment Detail\n"])
        for c in self.comments:
            status_icon = "✅" if c.status == "confirmed" else "⏳" if c.status == "pending" else "🔧"
            lines.append(
                f"\n### {status_icon} {c.id} (Reviewer {c.reviewer_id})\n"
                f"**Type:** {c.type} | **Status:** {c.status} | **Priority:** {c.priority}\n"
                f"**Text:** {c.verbatim[:100]}"
                + ("..." if len(c.verbatim) > 100 else "")
                + "\n"
            )
            if c.change_location:
                lines.append(f"**Location:** {c.change_location}\n")
            if c.change_summary:
                lines.append(f"**Change:** {c.change_summary}\n")
            if c.no_change_reason:
                lines.append(f"**No change:** {c.no_change_reason}\n")
            if c.response:
                lines.append(f"**Response:** {c.response[:100]}"
                             + ("..." if len(c.response) > 100 else "") + "\n")

        return "\n".join(lines)

    def render_table(self) -> str:
        """Render a compact table of all comments."""
        lines = [
            "| ID | Reviewer | Type | Status | Priority | Location |",
            "|--:|----------|------|--------|----------|---------|",
        ]
        for c in self.comments:
            lines.append(
                f"| {c.id} | R{c.reviewer_id} | {c.type} | "
                f"{c.status} | {c.priority} | {c.change_location or '—'} |"
            )
        return "\n".join(lines)


# ─── CLI entry point ─────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Track reviewer comments across revision rounds.",
    )
    parser.add_argument("state_file", help="Path to pipeline_state.json")
    parser.add_argument(
        "--add",
        help="Add a new comment (format: id|reviewer_id|verbatim)",
    )
    parser.add_argument("--type", default="writing", help="Comment type")
    parser.add_argument("--priority", default="major", help="Priority: major/minor")
    parser.add_argument("--round", help="Revision round (R1/R2/R3)")
    parser.add_argument(
        "--update",
        help="Update comment status (format: comment_id|new_status)",
    )
    parser.add_argument("--list", action="store_true", help="List all tracked comments")
    parser.add_argument("--summary", action="store_true", help="Show summary")
    parser.add_argument("--table", action="store_true", help="Show comment table")
    parser.add_argument("--advance", action="store_true", help="Advance to next round")
    parser.add_argument("--set-decision", help="Set decision type")
    parser.add_argument("--pending", action="store_true", help="Show pending comments")

    args = parser.parse_args()

    tracker = RevisionTracker(args.state_file)
    tracker.load()

    if args.round:
        tracker.round = args.round

    if args.set_decision:
        tracker.decision_type = args.set_decision

    if args.add:
        parts = args.add.split("|")
        if len(parts) < 3:
            print("Error: --add format: id|reviewer_id|verbatim")
            sys.exit(1)
        tracker.add_comment(
            comment_id=parts[0],
            reviewer_id=int(parts[1]),
            verbatim=parts[2],
            comment_type=args.type,
            priority=args.priority,
            round=args.round,
        )
        tracker.save()
        print(f"Added comment: {parts[0]}")
        return

    if args.update:
        parts = args.update.split("|")
        if len(parts) < 2:
            print("Error: --update format: comment_id|new_status")
            sys.exit(1)
        ok = tracker.update_status(parts[0], parts[1])
        tracker.save()
        print(f"{'Updated' if ok else 'Not found'}: {parts[0]} → {parts[1]}")
        return

    if args.advance:
        new_round = tracker.advance_round()
        tracker.save()
        print(f"Advanced to round: {new_round}")
        return

    if args.pending:
        pending = tracker.get_pending()
        print(f"Pending comments: {len(pending)}")
        for c in pending:
            print(f"  {c.id}: {c.verbatim[:80]}")
        return

    if args.list:
        for c in tracker.comments:
            print(f"{c.id} | R{c.reviewer_id} | {c.type} | {c.status}")
        return

    if args.summary:
        s = tracker.summary()
        print(json.dumps(s, indent=2))
        return

    if args.table:
        print(tracker.render_table())
        return

    # Default: show full markdown report
    print(tracker.render_markdown())


if __name__ == "__main__":
    _cli()
