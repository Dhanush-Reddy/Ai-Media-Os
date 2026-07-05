# Content Safety and Rights Engine

## Status

Planned. Do not implement before the active milestone explicitly calls for it.

## Purpose

The Content Safety and Rights Engine is a future subsystem for reducing the risk of copyright claims, strikes, reused-content monetization rejection, unlicensed asset usage, plagiarism, misleading AI-generated content, defamation, trademark confusion, missing attribution, and unsafe automatic publishing.

The engine cannot guarantee that a video will never receive a claim, strike, complaint, or monetization rejection. Its role is to reduce risk, preserve evidence, block unsafe assets, and require human review where needed.

## Core Principle

Copyright safety and monetization eligibility are separate concerns.

The system must check both:

1. Rights and licensing safety
2. Originality and viewer-value risk

## Pipeline Position

The engine should run before final publishing approval:

```text
Research
    ->
Script
    ->
Fact Check
    ->
Scene Plan
    ->
Asset Generation and Collection
    ->
Voice and Video Composition
    ->
Content Safety and Rights Engine
    ->
Human Review
    ->
Publishing Approval
    ->
Manual or Assisted Upload
```

No video should be automatically published during early phases.

## Rights Registry

Every external asset should have a stored rights record for images, video clips, music, sound effects, fonts, icons, screenshots, charts, logos, voice samples, templates, stock media, and generated media.

Each asset rights record should include source URL, creator, publisher, asset type, license type, commercial-use permission, modification permission, attribution requirement, attribution text, retrieval date, license verification date, license proof path, original file path, file hash, notes, and review status.

Recommended rights statuses:

```text
SAFE
ATTRIBUTION_REQUIRED
EDITORIAL_REVIEW
UNKNOWN
BLOCKED
```

Rules:

* `SAFE` assets may enter final renders.
* `ATTRIBUTION_REQUIRED` assets may enter only when attribution is included.
* `EDITORIAL_REVIEW` assets require manual review.
* `UNKNOWN` assets must not enter final renders automatically.
* `BLOCKED` assets must never enter final renders.

The system should preserve a local snapshot or proof of the license where practical.

## Originality and Similarity

The engine should estimate whether a video adds meaningful original value using script similarity to sources and previous videos, scene reuse, asset reuse, visual uniqueness, commentary depth, analysis depth, story structure, template repetition, hook/title/thumbnail/voice-over similarity, generated-or-original visual ratio, externally sourced visual ratio, unique claim count, and original explanation count.

Risk indicators include copied article structure, long near-verbatim passages, generic AI narration, repeated visual templates, repeated scene sequences, minimal analysis, minimal transformation, heavy stock-asset use, heavy reuse of previous videos, compilation-style editing, and low educational or entertainment value.

The exact thresholds should be configurable and reviewed after real channel data becomes available.

The script should synthesize information from multiple sources rather than follow one article line by line. Checks should include exact sentence matching, near-duplicate sentence matching, paragraph similarity, structural similarity, sequence similarity, excessive quoting, source concentration, and repeated phrases from previous scripts.

Preferred source-concentration policy:

* Largest single-source contribution under 40%.
* At least one primary source for important product or company claims.
* At least two reliable sources for disputed or high-risk claims.
* Discovery sources cannot be the only evidence for high-risk claims.

These percentages are risk heuristics, not legal guarantees.

## Audio, Voice, and Disclosure

Use only music and audio with clear commercial-use permission. Do not trust labels such as "No Copyright Music", "Copyright Free", or "Free to Use" without verifying the actual license.

The voice pipeline should prefer original or licensed synthetic voices and avoid cloning or impersonating real people without permission. Store provider, model, voice profile, license, commercial-use permission, consent record when applicable, generation date, and audio hash.

The engine should recommend or require AI-content disclosure for photorealistic synthetic people, synthetic public figures, realistic fake events, altered real-world footage, synthetic voice imitating a real person, fake interviews, fake product demonstrations, synthetic news footage, artificial locations presented as real, manipulated evidence, and deepfake-like content.

Disclosure recommendations, reasons, confidence, reviewer decisions, and upload disclosure values should be stored.

## Claim, Trademark, Thumbnail, Clip, and Generated-Image Safety

The engine should identify high-risk claims, including criminal allegations, fraud allegations, misconduct accusations, safety claims, medical claims, financial claims, investment predictions, layoffs, bankruptcy, data breaches, product defects, legal disputes, leaks, rumors, private personal information, quotes attributed to real people, claims about public companies, and claims that could damage reputation.

The system should never invent legal certainty. It should recommend careful wording such as "reportedly", "according to the company", "according to the filing", "the publication reported", "the claim has not been independently confirmed", and "early reports suggest" when appropriate.

The engine should flag fake endorsements, misleading sponsorship, false official branding, deceptive logo usage, counterfeit-looking product imagery, fake company announcements, official-looking thumbnails without disclosure, channel names that imply ownership by another company, unauthorized merchandise branding, and manipulated logos used to mislead.

Thumbnails should receive separate review because they create high reputational and policy risk.

Screenshots and clips should record source URL, source title, publisher, timestamp or page location, purpose of use, duration, cropping or transformation, commentary present, license or legal basis, and manual-review status.

Generated images should be checked for copyrighted characters, famous fictional characters, brand confusion, real-person impersonation, celebrity likeness, watermarks, accidental text, fake logos, unsafe imagery, misleading product depictions, and model license restrictions.

Avoid prompts that copy a living artist, copyrighted character, movie poster, or other protected expression. Prefer descriptive visual attributes.

## Content Safety Report

Every final video should receive a generated report saved as:

```text
data/projects/{project_id}/reports/content_safety_report_v001.json
data/projects/{project_id}/reports/content_safety_report_v001.md
```

The report should include copyright risk, reused-content risk, AI disclosure, music license verification, voice license verification, image license counts, unknown assets, blocked assets, attribution requirements, high-risk claims, script-to-source similarity, previous-video similarity, unique visual ratio, trademark risk, defamation risk, thumbnail risk, manual-review requirement, and publishing status.

## Risk Levels and Publishing Gate

Use:

```text
LOW
MEDIUM
HIGH
CRITICAL
```

Suggested behavior:

```text
LOW -> may continue
MEDIUM -> human review required
HIGH -> block final approval until resolved
CRITICAL -> block rendering or publishing
```

The final publishing gate should require acceptable rights status for all assets, included attribution where required, no blocked assets, no unresolved high-risk claims, no critical plagiarism findings, a recorded AI-disclosure decision, approved thumbnail, approved final video, and explicit publishing approval.

No timeout should automatically approve publishing.

## Human Review

The engine is a decision-support and blocking system, not a replacement for human judgment.

Human approval should remain required for final video, thumbnail, publishing, medium or higher copyright risk, editorial-review assets, fair-use-like situations, real-person synthetic content, high-risk allegations, trademark ambiguity, AI disclosure decisions, unverified leaks, and sensitive current events.

All human decisions should record reviewer, decision, timestamp, reason, related report version, and related content version.

## Preliminary Entities

Possible entities:

* `RightsRecord`
* `ContentSafetyCheck`
* `SimilarityFinding`
* `DisclosureDecision`
* `PublishingGate`

These are preliminary design ideas and must be refined before implementation.

## Suggested Jobs

Possible jobs:

```text
VERIFY_ASSET_RIGHTS
CHECK_SCRIPT_SIMILARITY
CHECK_PREVIOUS_VIDEO_SIMILARITY
CHECK_AUDIO_RIGHTS
CHECK_GENERATED_IMAGE_SAFETY
CHECK_THUMBNAIL_SAFETY
CHECK_HIGH_RISK_CLAIMS
EVALUATE_AI_DISCLOSURE
GENERATE_CONTENT_SAFETY_REPORT
EVALUATE_PUBLISHING_GATE
```

Most metadata checks should be `CPU_LIGHT`, similarity analysis should be `CPU_HEAVY`, image safety may be `GPU_LIGHT` or `CPU_HEAVY`, and manual rights decisions should be `MANUAL`.

## Development Sequence

Do not implement the full system all at once.

1. Rights metadata
2. Script similarity
3. Publishing gate
4. AI disclosure
5. Advanced checks

## Limitations

The system cannot truthfully guarantee no copyright claim, no copyright strike, no Content ID match, no trademark complaint, no privacy complaint, no defamation complaint, guaranteed monetization approval, guaranteed fair-use protection, or guaranteed policy compliance forever.

The system should provide evidence, traceability, conservative blocking, human review, source records, license records, similarity findings, disclosure recommendations, and auditable publishing decisions.
