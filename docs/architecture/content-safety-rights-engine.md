# Content Safety and Rights Engine

## Status

Implemented as a local rules-based risk-reduction layer.

## Disclaimer

This system provides local risk-reduction checks and workflow gates. It does not provide legal advice or guarantee that content is copyright-safe or platform-compliant.

## Purpose

The engine evaluates rendered-video packages before publishing approval. It focuses on rights provenance, claim support, script and metadata risk, thumbnail risk, reused-content risk, AI disclosure, and final publishing-gate decisions.

## What It Checks

* Asset rights records for imported and generated assets
* Claim support against stored research sources
* Script safety for unapproved text, local file paths, unsupported claims, and repeated text
* Metadata safety for unsupported claims, risky marketing wording, and local file paths
* Thumbnail safety for missing files, rejected assets, unsupported thumbnail text, and disclosure risk
* Reused-content risk by comparing script, metadata, render, and thumbnail text across project versions
* AI disclosure requirements for synthetic scripts, metadata, thumbnails, images, audio, or provider metadata
* Publishing gate outcomes using `PASS`, `PASS_WITH_WARNINGS`, `NEEDS_REVIEW`, or `BLOCKED`
* Explicit render, metadata-version, and thumbnail-asset selections supplied to the gate
* Persisted blocked reports when a required package input is missing

## Rights Statuses

```text
SAFE
ATTRIBUTION_REQUIRED
EDITORIAL_REVIEW
UNKNOWN
BLOCKED
```

## Safety Severities

```text
INFO
LOW
MEDIUM
HIGH
CRITICAL
```

## Gate Statuses

```text
PASS
PASS_WITH_WARNINGS
NEEDS_REVIEW
BLOCKED
```

## Check Statuses

```text
PASSED
WARNING
FAILED
SKIPPED
```

## Pipeline Position

```text
Research
  ->
Script
  ->
Scene Plan
  ->
Image and Audio Assets
  ->
Render
  ->
Metadata
  ->
Thumbnail
  ->
Content Safety and Rights Engine
  ->
Publishing Gate
  ->
Manual Publishing
```

The engine runs locally and does not upload to YouTube.

## Data Stored

The implementation stores:

* Rights records per asset
* Safety findings per check type and target
* Publishing gate reports as content versions
* AI disclosure decisions and suggested disclosure text
* Blocking reasons, warnings, and rule version metadata

## Known Limitations

* The engine is deterministic and rules-based.
* It does not perform real plagiarism lookup.
* It does not query external copyright databases.
* It does not claim legal safety or platform compliance.
* It does not automate publishing.
* It does not perform OCR on thumbnails.
* It does not prove legal rights or platform-policy compliance.
* Similarity checks are project-local and advisory.

## Future Extensions

Future work may add:

* Local LLM-assisted claim review
* Real platform-specific publishing checks
* External plagiarism or copyright APIs if explicitly approved
* Stronger similarity analysis for reused-content risk

