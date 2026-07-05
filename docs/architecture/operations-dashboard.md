# Minimal Operations Dashboard

## Status

Implemented for Milestone 4.5.

## Purpose

The operations dashboard is a local-only visibility and approval interface over existing AI Media OS services. It helps a non-technical user understand projects, research progress, pending approvals, queue activity, failed jobs, generated research outputs, and next expected actions.

## Technology Choice

The dashboard uses FastAPI, Jinja2 templates, local static CSS, and a small local HTMX-compatible polling helper. This fits the existing Python modular monolith and avoids a Node.js build pipeline.

React, Next.js, Vue, Svelte, Tailwind build tooling, WebSockets, and frontend state-management frameworks are deferred because Milestone 4.5 needs visibility and simple form actions, not a large interactive frontend.

## Boundaries

Routes validate input, call application or dashboard query services, build view models, and render templates. Approval routes use `ApprovalService`; job routes use `QueueService`. Routes do not mutate approval or job records directly through SQLAlchemy.

The dashboard does not implement script generation, media generation, publishing, analytics, authentication, Telegram, automated search, AI generation, or Content Safety behavior.

## Pages

Implemented pages:

```text
/
/projects
/projects/{project_id}
/projects/{project_id}/research
/approvals
/jobs
```

Small polling fragments live under `/ui/fragments/`.

## Polling

The dashboard polls small fragments only:

- Status counters
- Running jobs
- Pending approvals
- Recent activity

The default interval is `DASHBOARD_POLL_SECONDS=8`. Full pages are not refreshed repeatedly. WebSockets are intentionally deferred.

## Progress Calculation

Research progress is calculated from existing records, not stored in the database:

```text
Project created             10%
Sources imported            25%
Claims added                20%
Research brief generated    20%
Source report generated     10%
Readiness evaluated         10%
Research approved            5%
```

Overall media pipeline progress is currently capped to the implemented research portion, so it remains low until later media milestones exist.

## Security Assumptions

The dashboard binds to localhost by default and is not safe to expose publicly without authentication and transport security. State-changing forms use POST and CSRF validation. Source content and Markdown are escaped or rendered through a deliberately small safe Markdown subset. The dashboard does not expose arbitrary file downloads, shell execution, raw filesystem paths, full environment configuration, or arbitrary SQL filters.

## Launch

```powershell
.\.venv\Scripts\python.exe -m ai_media_os.web
```

or:

```powershell
.\.venv\Scripts\ai-media-os.exe dashboard
```

Default URL:

```text
http://127.0.0.1:8000
```

## Known Limitations

The dashboard is local-only and has no authentication. HTMX support is limited to the small polling behavior used by current templates. It does not provide advanced search, live WebSocket updates, full source snapshot browsing, or future milestone actions.

## Future Upgrade Path

Add authentication before any non-local exposure. Consider richer frontend tooling only after the media pipeline proves repeated revenue-oriented content production and the local dashboard becomes too limited for real workflows.
