# ADR 0005: Local Research Pipeline

## Status

Accepted

## Context

Milestone 4 needs research infrastructure for the first AI & Future channel while preserving the project constraints: zero recurring cost, no paid APIs, local-first execution, SQLite, filesystem snapshots, manual publishing, and human review for important decisions.

Automated web search and scraping would add network variability, copyright risk, provider coupling, and test fragility before the content pipeline has proven its manual workflow.

## Decision

Implement a local, provider-neutral research pipeline with manual source import, deterministic URL normalization, source snapshots, duplicate URL prevention, duplicate-content flagging, rule-based source classification, research notes, claim-source links, claim verification rules, deterministic research briefs, source reports, readiness evaluation, queue-compatible handlers, and minimal CLI commands.

Use existing SQLite, SQLAlchemy, Alembic, content-version, storage, and job-queue infrastructure. Store source snapshots on the local filesystem and project-relative paths in SQLite.

Do not add automated search, scraping, browser automation, AI text generation, LangGraph as a required dependency, or Content Safety and Rights Engine implementation in this milestone.

## Alternatives Considered

- Automated search first: deferred because it adds network and source-quality complexity before manual research records are stable.
- Scraping and extraction providers now: deferred because source text can be pasted or imported from local files for the MVP.
- AI-generated research summaries: rejected for Milestone 4 because the milestone must remain deterministic and provider neutral.
- A separate research database: rejected because the existing SQLite schema is sufficient and simpler to migrate.

## Consequences

- Users can build reviewable research sets locally without paid services.
- Important research outputs are immutable content versions.
- Snapshot hashes and project-relative paths preserve traceability without storing large text blobs as external assets.
- Verification rules are conservative and explainable, but they do not prove truth or legal safety.
- Future search and extraction providers can be added behind provider interfaces after the manual workflow is reliable.
