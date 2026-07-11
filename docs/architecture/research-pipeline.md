# Local Research Pipeline

## Status

Implemented for Milestone 4.

## Purpose

The local research pipeline stores manually supplied sources, notes, claims, source links, research briefs, source reports, and readiness evaluations without automated web search, scraping, browser automation, AI generation, or paid APIs.

## Manual Source Import

Milestone 4 starts with manual source import because the MVP needs copyright-aware, reviewable evidence before automated collection. Users provide a URL, metadata, source text, or a local UTF-8 text/Markdown file. The system stores normalized snapshots under:

```text
data/projects/{project_id}/research/sources/{source_id}/snapshot.txt
```

Database records store project-relative snapshot paths, hashes, source metadata, and duplicate-content references.

## URL and Duplicate Handling

Remote source URLs accept only `http` and `https`. Normalization lowercases scheme and host, removes fragments, removes common tracking parameters such as `utm_*`, preserves meaningful query parameters, and normalizes empty paths to `/`.

Each project has one record per canonical URL. Different projects may import the same URL independently. Identical source text is flagged through `duplicate_of_source_id` but is not merged automatically.

## Classification

Classification is deterministic and rule based. Manual source type overrides are allowed. Default authority mapping is:

- Tier 1: official, documentation, research paper, regulatory, government
- Tier 2: news, industry publication
- Tier 3: blog, forum, social media, video
- Unrated: other

The classifier uses small explicit rules for `.gov`, documentation paths, DOI/arXiv hosts, major forum/social/video hosts, and publisher hints. It intentionally avoids a large hardcoded publisher database.

## Notes and Claims

Research notes are lightweight editable records tied to a project and source. Notes may be summaries, key points, quotes, context, contradictions, risks, or ideas. Notes are not automatically treated as verified facts.

Claims store importance, confidence, verification status, and source links. Verified high-importance claims need non-discovery support. Verified critical claims need either one Tier 1 source or two distinct reliable secondary sources unless manually overridden with a reason. Contradicting sources block automatic verification.

## Reports and Readiness

Research briefs are deterministic Markdown `ContentVersion` records. They separate verified claims, unverified claims, contradictions, risks, source groups, and script boundaries.

Source reports may be Markdown or JSON `ContentVersion` records. They include source counts, authority tiers, duplicate content, missing metadata, unsupported claims, contradicted claims, manual-review items, snapshot paths, and hashes.

Readiness evaluation is rules based. Blockers include no approved sources, no snapshots, critical unverified or contradicted claims, unsupported high-importance claims, and all approved sources being Tier 3. Warnings include missing publication dates, missing publishers, high duplicate-content concentration, high source concentration, and too few primary sources.

## Queue and Workflow

Milestone 4 adds queue-compatible handlers for:

```text
IMPORT_RESEARCH_SOURCE
CLASSIFY_RESEARCH_SOURCE
GENERATE_RESEARCH_BRIEF
GENERATE_SOURCE_REPORT
EVALUATE_RESEARCH_READINESS
```

The existing database-backed queue still owns claiming, retries, leases, dependencies, and resource classes. `SimpleWorkflowOrchestrator` remains the active MVP workflow path. Milestone 4 stops before script generation.

## Limitations

Milestone 4 does not download pages, scrape websites, parse PDFs, call search APIs, or use AI summarization. Later milestones consume its stored claims and sources for scripts and local Content Safety checks. Publishing remains manual, and future search or extraction capabilities must remain behind provider interfaces.
