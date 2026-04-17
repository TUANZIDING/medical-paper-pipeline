# Security Hardening Design for medical-paper-pipeline

## Summary

This design adds a focused security layer to the existing project without restructuring the repository. It addresses five approved hardening goals:

1. Protect patient privacy with default PHI detection-and-blocking, plus optional redaction.
2. Enforce human review gates for all core AI-generated artifacts.
3. Restrict output writes to normalized, whitelisted project paths.
4. Standardize API timeout, retry, and rate-limit behavior with bounded failure modes.
5. Document explicit safety boundaries in README.md and SKILL.md, including a prohibition on real non-de-identified patient data.

The design intentionally avoids a broad architectural rewrite. It introduces one shared security module and incrementally integrates it into the highest-risk entry points first.

## Goals

- Default to blocking unredacted PHI from flowing into subsequent stages.
- Require explicit human approval before AI-generated core outputs are treated as ready for the next stage.
- Ensure generated text artifacts include visible disclaimer text.
- Prevent writes outside approved project-local destinations.
- Bound all external API behavior with timeout, retry, and rate-limit controls.
- Treat exhausted API attempts as `NEEDS_REVIEW`, never as silent success.
- Update project documentation so privacy and academic-integrity constraints are explicit.

## Non-Goals

- No full repository reorganization.
- No user identity, role, or multi-user audit system.
- No external secrets manager or encrypted storage layer.
- No attempt to perfectly detect every PHI variant; the system aims for strong default heuristics and safe failure behavior.
- No automated approval of human review gates.

## Existing Context

Current risk hotspots in the repository:

- `revision_tracker.py` writes `pipeline_state.json` but does not restrict permissions or add security metadata.
- `doi_verifier.py` performs external HTTP requests with timeout and rate-limit constants, but retry and fallback behavior are not centralized.
- `paper_writer.py` assembles high-risk AI-generated manuscript output without mandatory disclaimer insertion or review-gate enforcement.
- `README.md` and `SKILL.md` describe human checkpoints, but they do not yet define mandatory security gates for PHI, review approval, or path restrictions.
- The documented architecture in `README.md` references `tools/`, while the current repository stores the scripts at the root. The hardening work should not widen scope by restructuring the project.

## Recommended Approach

Adopt a centralized “core guardrails” approach:

- Add a new shared module: `security_guardrails.py`
- Integrate it into the highest-risk scripts first:
  - `revision_tracker.py`
  - `doi_verifier.py`
  - `paper_writer.py`
- Update `README.md` and `SKILL.md` so the workflow documentation matches the enforced behavior.

This keeps the implementation focused, avoids duplicated security logic across scripts, and leaves room to extend the same controls to `journal_formatter.py`, `response_letter_generator.py`, and `tracked_change_generator.py` in a follow-up pass.

## Architecture

### New shared module: `security_guardrails.py`

This module will define four focused components plus small helpers.

#### 1. `PHIGuard`

Responsibilities:

- Scan text for likely protected health information (PHI).
- Support two modes:
  - `detect_and_block` (default)
  - `detect_and_redact` (explicit opt-in)
- Return structured findings describing what was detected and where.
- Provide a redaction path that replaces sensitive values with placeholders such as `[PATIENT_NAME]`, `[MRN]`, `[DATE]`, `[PHONE]`, and `[EMAIL]`.

Detection scope should cover high-risk identifiers and near-identifiers relevant to this project, including:

- Patient names when presented in common labeled patterns
- Phone numbers
- Email addresses
- National ID-like numbers
- Medical record / admission / hospital number patterns
- Exact calendar dates in common formats

Expected behavior:

- In `detect_and_block`, any detected PHI blocks write/advance operations and records findings.
- In `detect_and_redact`, findings are recorded and matching values are replaced before the write proceeds.

#### 2. `ReviewGate`

Responsibilities:

- Mark AI-generated artifacts as requiring human review.
- Record approval state inside `pipeline_state.json`.
- Refuse stage progression when required artifacts are not approved.

Core status model:

- `human_review_required`
- `human_review_approved`

Tracked metadata per artifact:

- `status`
- `approved` (boolean)
- `reviewed_by`
- `review_timestamp`

#### 3. `SafePathPolicy`

Responsibilities:

- Normalize candidate output paths.
- Prevent path traversal and project escape.
- Allow writes only to an approved whitelist.

Approved write targets for this phase:

- `./pipeline_state.json`
- `./figures/`
- `./outputs/`
- `./logs/`

Enforcement rules:

- Resolve paths before checking.
- Reject absolute or relative paths that resolve outside the repository root.
- Reject writes to any non-whitelisted destination.
- Keep this strict by default; no user-configurable exceptions in this phase.

#### 4. `SafeHttpClient`

Responsibilities:

- Centralize HTTP timeout, retry, and rate-limit handling.
- Bound retries and surface terminal outcomes clearly.
- Support eventual downgrade to `NEEDS_REVIEW` after retry exhaustion.

Required behavior:

- Per-request timeout
- Fixed or exponential backoff between attempts
- Max retry count
- Explicit handling for timeout, transport errors, 429 responses, and 5xx responses
- No infinite retry loops
- No silent success on terminal failure

#### Helper functions

- `prepend_disclaimer(text, artifact_type)`
- `chmod_owner_only(path)`
- `load_pipeline_state(path)` / `save_pipeline_state(path)` helpers if useful for keeping state logic consistent

## Data Model Changes

Add a `security` section to `pipeline_state.json` without replacing the existing structure.

Example shape:

```json
{
  "security": {
    "phi_mode": "detect_and_block",
    "phi_findings": [],
    "review_gates": {
      "statistical_results.md": {
        "status": "human_review_required",
        "approved": false,
        "reviewed_by": null,
        "review_timestamp": null
      }
    },
    "blocked_reason": null
  }
}
```

### State semantics

- `phi_mode` defaults to `detect_and_block`
- `phi_findings` stores the latest blocking or redaction findings
- `review_gates` stores artifact-level review requirements
- `blocked_reason` stores the active reason a stage cannot proceed, such as PHI detection or missing human approval

## Artifact-Level Review Policy

The following core AI-generated artifacts must automatically require human review:

- `statistical_results.md`
- `stat_methods_paragraph.md`
- `manuscript_draft.md`
- `reference_verification_report.md`
- `response_letter.md`
- `revision_summary.md`
- Core generated text artifacts under `outputs/`

Rules:

1. When a covered artifact is generated or materially rewritten, prepend a disclaimer header.
2. Register or update its review gate in `pipeline_state.json`.
3. Prevent stage advancement while its gate remains unapproved.
4. Require explicit user confirmation before setting the gate to approved.

## Disclaimer Policy

All covered AI-generated text artifacts must include a short, visible disclaimer header.

The disclaimer must communicate three points:

1. The content was generated or transformed with AI assistance.
2. The content must be manually reviewed, verified, and revised by a qualified researcher before submission or external use.
3. The tool must not be used with real identifiable patient data and must not be used for clinical decision-making.

The exact wording can be standardized per artifact type, but the meaning should remain fixed.

## PHI Handling Flow

### Default mode: `detect_and_block`

Before writing covered text or advancing a stage:

1. Run `PHIGuard.scan_text(...)`
2. If findings exist:
   - Reject the write or stage transition
   - Record findings in `pipeline_state.json.security.phi_findings`
   - Set `blocked_reason`
   - Surface a clear error for the user to resolve

### Optional mode: `detect_and_redact`

When explicitly enabled:

1. Scan the text
2. Redact detected values
3. Record findings and replacements
4. Write only the redacted output

The default must remain blocking, not redaction.

## Output Path Policy

All output writes for covered scripts must follow this sequence:

1. Normalize the candidate path with `Path.resolve()`
2. Verify it stays inside the repository root
3. Verify it is one of the approved destinations
4. Refuse the write on failure

This prevents `../` traversal, accidental absolute-path writes, and writes into arbitrary project files.

## External API Policy

External API calls must use `SafeHttpClient`.

### Required controls

- Timeout on every request
- Bounded retries
- Rate-limit aware waits
- Clear terminal failure state after retry exhaustion

### Failure outcome

When retries are exhausted:

- Do not mark the item as verified or successful
- Downgrade the affected entry or step to `NEEDS_REVIEW`
- Preserve enough error detail for the user to understand why manual review is required

## File-Level Integration Plan

### `revision_tracker.py`

Changes:

- Validate the `pipeline_state.json` path through `SafePathPolicy`
- After write, force owner-only permissions with `chmod 600`
- Add and update review-gate metadata for Stage 5 AI-generated artifacts
- Scan high-risk text fields before saving relevant generated content or state summaries

Special note:

- Permission hardening of `pipeline_state.json` is mandatory here because this script clearly persists workflow state.

### `doi_verifier.py`

Changes:

- Replace direct `urllib` request handling paths with `SafeHttpClient`
- Move timeout, retry, and rate-limit behavior into shared guardrails
- Convert terminal API failures to `NEEDS_REVIEW`
- Validate output report destinations with `SafePathPolicy`
- Prepend disclaimer text to generated reports
- Run PHI scans against generated report text before write

Special note:

- This script already has timeout and rate-limit concepts. The goal is not to change behavior arbitrarily, but to centralize and bound it.

### `paper_writer.py`

Changes:

- Prepend disclaimer text to generated manuscript output
- Register generated manuscript artifacts with `ReviewGate`
- Refuse downstream progression when required approvals are absent
- Validate all output paths through `SafePathPolicy`
- Run PHI checks before writing generated manuscript text

Special note:

- This is a high-risk output surface because it creates text intended for eventual submission.

### `README.md`

Add explicit safety documentation covering:

- Real identifiable patient data must not be used
- Only de-identified data is recommended and supported
- `pipeline_state.json` should be treated as sensitive workflow state and restricted to owner-only permissions
- AI-generated content requires human verification before submission
- `NEEDS_REVIEW` does not equal successful verification
- The tool is not for clinical diagnosis or treatment decisions

### `SKILL.md`

Strengthen the workflow contract by documenting:

- Stage 0 de-identification expectation before pipeline use
- Human review gates across Stages 1–5 for core generated artifacts
- `NEEDS_REVIEW` as a blocking/manual-review condition rather than a pass
- Restricted output locations and path validation requirements

## Error Handling

### PHI findings

- In default mode, block the current write or stage transition
- Record findings in state
- Set a clear `blocked_reason`

### Path violations

- Fail immediately
- Do not write partial output

### API timeout / retry exhaustion

- Stop retrying at the configured cap
- Return `NEEDS_REVIEW`
- Preserve actionable error context

### Permission hardening failures

- If initial creation or protected save of `pipeline_state.json` cannot be completed safely, fail the operation
- If permission tightening fails after a non-critical rewrite, surface a warning and preserve enough context for manual correction

## Testing Strategy

At minimum, add or run coverage for these scenarios:

1. **PHI detection**
   - Detect phone numbers, email addresses, ID-like values, MRN-like values, and exact dates
2. **PHI redaction**
   - In redaction mode, replace sensitive values with placeholders
3. **Whitelist enforcement**
   - Allow `./figures/a.png`
   - Reject `../secret.txt`
   - Reject `/tmp/out.txt`
4. **Review-gate enforcement**
   - Unapproved `manuscript_draft.md` cannot advance to the next stage
5. **API bounded failure**
   - Simulate timeout / 429 / 5xx and verify eventual `NEEDS_REVIEW`
6. **State file permissions**
   - `pipeline_state.json` is saved with mode `600`

## Acceptance Criteria

This hardening work is complete when all of the following are true:

- Unredacted PHI is blocked by default from flowing into later stages
- Optional redaction mode exists, but is not the default
- Covered AI-generated text artifacts include disclaimer headers
- Covered AI-generated core artifacts require explicit human approval
- Unapproved artifacts block stage advancement
- Output writes are limited to the approved project-local whitelist
- Exhausted API attempts result in `NEEDS_REVIEW`, not silent success
- `pipeline_state.json` is saved with owner-only permissions
- `README.md` and `SKILL.md` clearly communicate privacy, review, and usage boundaries

## Implementation Order

Recommended order:

1. Add `security_guardrails.py`
2. Integrate `revision_tracker.py`
3. Integrate `doi_verifier.py`
4. Integrate `paper_writer.py`
5. Update `README.md`
6. Update `SKILL.md`
7. Optionally extend the same guardrails to `journal_formatter.py`, `response_letter_generator.py`, and `tracked_change_generator.py`

## Rationale for Scope

This design deliberately focuses on the highest-value controls that match the approved requirements.

It does not introduce a larger audit system, repository restructure, or broad platform-level security program. That would be unnecessary complexity for the current project and would violate the goal of delivering strong guardrails with minimal churn.
