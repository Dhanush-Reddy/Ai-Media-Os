# ADR 0006: Minimal Operations Dashboard

## Status

Accepted

## Context

Milestones 1 through 4 provide local persistence, jobs, approvals, content versions, workflow state, and a manual research pipeline. A non-technical user now needs visibility into what exists, what is running, what needs approval, what failed, and what research output is available.

The dashboard must stay local-first, zero recurring cost, and scoped before Milestone 5 script generation.

## Decision

Build a minimal local operations dashboard using FastAPI, Jinja2 templates, local CSS, and small HTMX-style polling fragments. Use existing application services for state changes and dashboard query services for read-only view models.

Do not add React, a Node.js build pipeline, WebSockets, authentication, automated search, AI generation, script generation, media generation, publishing, analytics, Telegram, or Content Safety implementation.

## Rationale

Jinja and server-rendered pages are enough for local visibility and form submissions. They keep implementation simple, testable, and Python-first. Small polling fragments provide live-ish status without WebSockets or a frontend state framework.

## Alternatives Considered

- React or Next.js: deferred because it adds a separate toolchain and frontend architecture before the dashboard needs it.
- WebSockets: deferred because polling a few small fragments is simpler and reliable enough locally.
- Direct SQLAlchemy mutations in routes: rejected because approvals and jobs already have application services with business rules.
- Authentication now: deferred because the milestone is explicitly localhost-only.

## Consequences

- The dashboard can run locally with `python -m ai_media_os.web`.
- Approval decisions and job actions preserve existing service behavior.
- Progress and activity are derived from existing records, not stored as fake state.
- The dashboard must not be exposed beyond localhost until authentication is added.
