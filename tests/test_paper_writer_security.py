import pytest
from pathlib import Path

from paper_writer import PaperWriter


def test_write_blocks_non_whitelisted_output(tmp_path):
    """Writing to a non-whitelisted path should raise ValueError."""
    # Create actual files so PaperWriter.__init__ can read them
    (tmp_path / "stat_results.md").write_text("Stats content")
    (tmp_path / "draft.md").write_text("# Introduction\n\nIntro")
    (tmp_path / "methods.md").write_text("Methods description")

    writer = PaperWriter(
        stat_results=tmp_path / "stat_results.md",
        draft=tmp_path / "draft.md",
        verified_refs=tmp_path / "refs.md",
        stat_methods=tmp_path / "methods.md",
    )
    # tmp_path / "manuscript.md" is not in the allowed whitelist (outputs/, figures/, logs/, pipeline_state.json)
    with pytest.raises(ValueError):
        writer.write(output=tmp_path / "manuscript.md")


def test_write_adds_disclaimer_to_outputs(tmp_path):
    """write() should prepend the AI-GENERATED DRAFT disclaimer and write it to file."""
    # Create outputs/ inside tmp_path so path resolves relative to cwd (the worktree root)
    # when SafePathPolicy(repo_root=Path.cwd()) is used.
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()

    # Use a path that SafePathPolicy(repo_root=Path.cwd()) will consider allowed:
    # outputs/manuscript_final.md is relative to cwd (worktree root), matching the policy.
    rel_output = Path("outputs/manuscript_final.md")
    result = PaperWriter().write(output=rel_output)

    # Return value should start with disclaimer
    assert result.startswith("AI-GENERATED DRAFT")

    # File on disk should also start with disclaimer
    written = rel_output.read_text(encoding="utf-8")
    assert written.startswith("AI-GENERATED DRAFT")
