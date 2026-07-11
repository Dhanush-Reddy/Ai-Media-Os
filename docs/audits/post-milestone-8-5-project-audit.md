# Post-Milestone 8.5 Project Audit

Audit date: 2026-07-11  
Audited baseline: `main` at `929f136`  
Audit branch: `audit/post-milestone-8-5`

## 1. Executive Summary

**Overall decision: `ON_TRACK_WITH_FIXES`**  
**Confidence: High**  
**Milestone 9A readiness: `READY_FOR_9A_AFTER_FIXES`**

AI Media OS is recognizably one reusable, local-first content engine rather than a collection of
channel-specific scripts. SQLite is the operational source of truth, large outputs live in safe
project-relative filesystem paths, important text outputs are versioned, replaceable providers are
established, and fake/manual providers can produce an inspectable package without paid APIs.

The strongest parts are the database-backed queue, content-version and approval foundations,
strict schemas, provider protocols, filesystem containment, deterministic fake providers, local
dashboard, and the now-safeguarded `0010` migration. A disposable service-level run completed the
full current pipeline and produced source snapshots, PNG images, WAV narration, a fake MP4,
metadata, a thumbnail PNG, safety findings, and a publishing-gate report.

The project should not begin Ollama integration immediately. The current workflow orchestrator can
commit jobs and approvals before its event record and state transition, several workflow events do
not prove the referenced object is actually approved or verified, approved scene assets can be
regenerated in place, and publishing-gate checks can evaluate the latest metadata/thumbnail rather
than the explicitly selected package. The text-provider request/result and script fingerprint also
need model/version/settings/timeout semantics before a nondeterministic local model is introduced.

Recommended next milestone: a small **Milestone 8.6 - Reliability and Audit Remediation**, followed
by Milestone 9A.

## 2. Repository State

- `main` was clean and updated from `origin/main` at `929f136` (`Safeguard content safety migration
  downgrade (#14)`).
- Milestone 8.5 is present on `main`; its implementation landed in PR #13 and migration safeguards
  landed in PR #14.
- Tags present: `v0.4.5-pre-ponytail`, `v0.6.0`, `v0.7.0`, and `v0.8.0`.
- There is no `v0.8.5` tag. This is not a correctness issue, but release tagging is behind the
  milestone state.
- No pull requests were open when repository state was checked.
- Several old remote milestone branches are not graph ancestors of `main` because the repository
  used squash/merge commits. Their work is represented on `main`; no active unmerged feature was
  identified. The branches should not be deleted as part of this audit.
- History is understandable, although duplicate ADR number `0006` and squash-merged branch tips
  make mechanical ancestry checks less clear than the product history.

## 3. Implemented System Map

The actual working path is:

```text
Channel + VideoProject (ORM bootstrap only)
  -> manually imported Source snapshots
  -> Claims + ClaimSource links + deterministic verification
  -> Research brief and source report ContentVersions
  -> rules-based Script ContentVersion + Approval
  -> fact-check report and script quality result
  -> Scene-plan ContentVersion + persisted Scene rows + Approval
  -> planned Asset rows
  -> fake/manual image and voice files + review statuses
  -> Render plan + fake or FFmpeg composition + verification/review
  -> Metadata ContentVersion + Approval
  -> Thumbnail-concept ContentVersion + thumbnail Asset + review
  -> RightsRecord and ContentSafetyCheck rows
  -> copyright/safety report ContentVersion + PublishingGate
  -> manual review; no publishing implementation
```

CLI commands, queue handlers, and dashboard views exist for most stages after project creation.
There is no CLI command to create a channel or project, so a clean user flow cannot start without
ORM/database bootstrap.

## 4. Milestone-by-Milestone Verification

| Milestone | Assessment | Evidence and qualification |
|---|---|---|
| 1 - Foundation | Implemented | Python 3.12 project, settings, logging, SQLite WAL/foreign keys, SQLAlchemy, Alembic, tests. |
| 2 - Job queue | Implemented | Atomic `BEGIN IMMEDIATE` claiming, ownership, leases, retries, stale recovery, dependencies, resource classes, worker loop. |
| 3 - Versions/approvals/cache | Implemented with limitations | Version numbering and approvals use short write transactions; cache validates paths and hashes. Database-level content immutability remains intentionally unenforced. |
| Workflow evaluation | Proof of concept extended, reliability incomplete | `SimpleWorkflowOrchestrator` remains selected and LangGraph optional, but event/state/job atomicity and approval validation need repair. |
| 4 - Research | Implemented with replay gap | Source snapshots, claims, links, readiness, briefs and reports work. Brief/source-report generation creates duplicate versions on identical replay. |
| 4.5 - Dashboard | Implemented | Local Jinja/FastAPI views, CSRF-protected actions, safe previews, and all current project pages rendered in the smoke test. |
| 5 - Script/scenes | Implemented | Provider-neutral script generation, fact check, quality checks, approvals, strict scene schema, and scene persistence work. |
| 6 - Image/voice | Implemented with immutability gap | Fake PNG/WAV and manual imports work, but generation/import mutates the same asset and file even after approval. |
| 7 - Video composition | Foundation implemented | Planning, fake/FFmpeg composition boundary, verification and review work. Captions, richer motion, and final-render quality remain deferred as documented. |
| 8 - Metadata/thumbnail | Implemented | Strict metadata, deterministic providers, approvals, concepts, valid thumbnail PNG, imports, dashboard and handlers work. |
| 8.5 - Safety/rights | Implemented with gate-selection gap | Deterministic checks, disclosure, reports, rights records and gate persistence work. Missing/explicit package handling needs correction. |

## 5. Architecture Findings

### Critical

No critical defect was confirmed during this audit.

### High

1. **Workflow state, jobs, approvals, and event idempotency are not atomic.**
   `SimpleWorkflowOrchestrator` calls services that commit inside event handlers, then records the
   event and commits workflow state later (`simple_orchestrator.py:83-128`, with intermediate commits
   at lines 166, 180, 190 and 215). A crash can leave a created job or decided approval without the
   event record/state transition, and replay can create duplicate work.
2. **Workflow “approved/verified” events do not consistently verify persisted state.**
   Scene-plan and metadata handlers validate project/type but not `VersionStatus.APPROVED`;
   asset approval trusts the event; render verification trusts a string ID; thumbnail approval does
   not load and verify the asset; safety completion trusts status metadata rather than a persisted
   gate (`simple_orchestrator.py:221-349`). Required approvals can therefore be bypassed through the
   orchestrator API even though direct application services are stricter.
3. **Approved scene assets can be overwritten in place.**
   Image and voice generation/import write the existing planned asset path and reset review status
   to pending without rejecting approved assets (`assets.py:212-303`, `assets.py:388-480`). This
   violates the repository's approved-output immutability rule and can change bytes already used by
   a reviewed render.
4. **Publishing gates can inspect a different or incomplete package.**
   `run_publishing_gate()` resolves optional explicit metadata and thumbnail IDs, but then calls
   public checks that independently select the latest records (`safety.py:242-260`). Those checks
   raise when metadata/thumbnail is absent before the later “Missing metadata/thumbnail” blockers
   can be recorded (`safety.py:285-291`). A gate can therefore fail to produce a report for missing
   inputs or evaluate a record different from the one stored on the gate.

### Medium

1. `TextGenerationRequest/Result` has no model version, structured-output contract, timeout/cancel
   semantics, provider options, or error taxonomy. Script idempotency filters on provider name but
   not model/version/settings (`text_generation.py:8-29`, `scripts.py:85-106`, `scripts.py:282-299`).
2. Research brief and source report generation always creates a new content version for identical
   inputs (`research.py:642-676`). A worker crash after service completion but before job completion
   creates duplicates on retry.
3. Asset planning performs check-then-insert without a unique `(scene_id, asset_role)` constraint.
   Concurrent planners can create duplicate visual/narration rows; the model has only a non-unique
   index (`models.py:466-470`). Similar check-then-insert risks exist in some render and packaging
   paths, although version/render uniqueness constraints convert most races into explicit failures.
4. `render_allow_pending_assets` defaults to true (`settings.py:76`, `renders.py:226-239`), allowing
   direct CLI/service render planning before asset review. The workflow intends asset review first.
5. Manual image/audio/thumbnail imports use `shutil.copyfile` rather than the atomic storage helper
   and infer MIME from extension without file-signature validation. Destination containment and size
   checks are present, but interruption can leave a partial destination.
6. Historical migrations `0003` through `0009` have destructive downgrade operations with mixed
   backup quality. `0006`-`0009` preserve selected data but do not verify backup/source row counts;
   `0004` and `0005` drop workflow/research data without equivalent backup tables.
7. Dashboard routes bind to a module-global `SessionLocal` (`dashboard/routes.py:33,48-49`) while
   `create_app(settings)` accepts custom settings. Normal startup works because environment settings
   are loaded globally, but injected/test/multi-profile app settings can point file and DB access at
   different configurations.
8. CLI usability is blocked at the first step: no create/list channel or create-project command.
   Most commands require internal IDs, and top-level help lists commands without descriptions or
   workflow grouping.

### Low / Informational

- `safety.py`, `research.py`, `cli.py`, and `dashboard/queries.py` are large. They remain cohesive
  enough for the MVP; split them only while making demonstrated fixes.
- README and several older architecture notes contradict current implementation. README says 8.5
  is implemented near the top but later says it is the next task and not implemented. Milestone 6/7
  notes still say thumbnails and Content Safety are absent.
- ADR numbering contains both autonomous PR agent and dashboard records as `0006`.
- The local `.env` emitted a python-dotenv parse warning during commands. `.env.example` itself is
  valid; local uncommitted environment content was not inspected.

## 6. Data Flow Findings

| Stage | Provenance/hash/idempotency | Approval and integration |
|---|---|---|
| Sources/claims | Snapshot paths and hashes stored; canonical URL unique per project | CLI, workers, dashboard present; project bootstrap absent |
| Research outputs | ContentVersions preserve inputs | Identical replay creates duplicate brief/report versions |
| Script | Research/claim hashes, provider/model/prompt stored | Idempotent for current provider; approval enforced before scene planning |
| Scene plan/scenes | Script/claim hashes and strict schema stored | Generation and rows persist before approval request; replay normally repairs missing approval |
| Assets | Prompt/provider/model/hash/path stored; fake cache works | Approved records can be overwritten; concurrent planning lacks uniqueness |
| Render | Scene plan, ordered input hashes and settings fingerprint stored | Missing/corrupt files rejected; pending assets allowed by default |
| Metadata | Script/scene/render hashes and provider metadata stored | Approved script/scene required; provider metadata assumes a `fingerprint` key not declared by protocol |
| Thumbnail | Metadata/concept fingerprints and file hash stored | New assets preserve approved history; verification checks file/hash |
| Safety/gate | Rule version and deterministic fingerprints stored | Replay is idempotent; explicit/missing package selection is incorrect |

No stage was completely disconnected. The queue handlers call application services rather than
mutating ORM models directly. The persisted workflow is the least reliable integration layer and
should not be treated as the authoritative full-pipeline executor until fixed.

## 7. Transaction and Concurrency Findings

- Queue claiming correctly uses `BEGIN IMMEDIATE` and a conditional status update.
- Content version numbering and approval decisions use `BEGIN IMMEDIATE`; uniqueness constraints
  protect version numbers. The session-depth convention used by safety reports avoids the earlier
  nested transaction failure.
- Application services generally own commits, which is acceptable for CLI use cases but prevents
  the orchestrator from composing them atomically. Introduce explicit no-commit/unit-of-work paths
  for orchestration rather than adding more hidden depth flags.
- `QueueService.complete_job()` commits completion and then separately reevaluates dependencies.
  A crash can leave dependents waiting until the next reevaluation; this is recoverable, not data
  corruption.
- Script/scene status is committed before approval creation. Replay can usually create the missing
  approval, but users may temporarily see pending content with no request.
- Filesystem writes cannot be transactionally committed with SQLite. Generated/cache writes use
  atomic replacement and can leave safe orphan files; manual imports should use the same primitive.
- Safety findings, rights rows, report content version and gate are created under one service-owned
  write transaction and protected by unique fingerprints.

## 8. Migration Findings

The revision chain is linear and consistent from `0001` through `0010`. Fresh upgrade, downgrade
`-1`, re-upgrade, and `alembic check` all passed against a temporary database. The focused migration
suite passed 14 tests.

Migration `0010_content_safety_rights_engine.py` now meets its intended safeguards:

- creates all three backup tables when absent;
- clears and reuses existing backup tables without duplication;
- copies every column created by `0010` for rights, checks and gates;
- verifies source and backup row counts before dropping any source table;
- raises before destructive DDL on mismatch;
- handles empty tables;
- restores populated backups during re-upgrade and verifies restored counts;
- keeps backup tables excluded from Alembic autogenerate drift checks.

Remaining migration risk is historical: `0006`-`0009` backup selected data without row-count
verification, while earlier destructive downgrades preserve less. Do not rewrite released
migrations casually; add a tested policy/remediation only if multi-revision downgrade is a supported
operator workflow.

## 9. Provider Readiness

### Ollama

Boundary exists but is not ready without small contract work. Add model/version/options, timeout and
cancellation behavior, typed provider errors, structured-output validation/retry semantics, and
include provider/model/version/settings in script fingerprints. Add configuration/factory selection
so CLI and workers can choose Ollama while fake/manual remains default.

### ComfyUI

`ImageGenerationProvider` is a suitable adapter boundary and cache inputs already include prompt,
negative prompt, dimensions, seed and model identity. Before integration, prevent approved-asset
overwrite, add request timeout/cancellation/error semantics, and decide whether generations create
asset revisions rather than mutate one row.

### Local TTS

`VoiceGenerationProvider` is replaceable and tracks voice/language/rate/seed. Apply the same approved
asset revision and timeout/error fixes. Add explicit output format/sample-rate metadata before
supporting multiple engines.

No paid, cloud, GPU, FFmpeg, or network dependency is required by the current test suite.

## 10. Cache and Idempotency Findings

- Canonical JSON rejects non-finite floats, preserves list order, sorts mapping keys, and avoids
  timestamps in generation keys.
- Image, voice, render, metadata and thumbnail fingerprints include the important current fake
  provider inputs; missing/corrupt cache files invalidate reuse.
- Approved metadata and thumbnail history is preserved through revisions/new assets.
- Weak points are research-report replay, approved scene-asset mutation, script keys lacking model
  version/settings, and safety reused-content fingerprinting based partly on `project.updated_at`,
  which can create a new advisory finding after unrelated project updates.
- `MetadataService` assumes provider metadata contains `fingerprint`, although the provider protocol
  does not declare that requirement. Make fingerprint construction application-owned.

## 11. Security and Filesystem Findings

Strengths:

- `FileStorage` rejects absolute, Windows drive, UNC-style and parent traversal paths, resolves final
  targets, and prevents symlink/junction escape from approved roots.
- Generated and cached files use same-directory temporary files, `fsync`, and atomic replacement.
- Preview routes load assets/renders by database ID, validate type, and resolve paths under the data
  root. Templates do not expose raw paths.
- Dashboard forms use POST and constant-time CSRF validation; content is escaped or passed through a
  small safe Markdown renderer.
- FFmpeg uses argument arrays and `shell=False`; diagnostics are bounded.

Gaps:

- Manual media imports are not atomic and validate extension/size rather than actual MIME/signature.
- FFmpeg/ffprobe subprocesses have no timeout, which matters for future worker cancellation and
  hung local executables.
- Dashboard remains localhost-only and has no authentication, as documented.

No path that writes generated/imported project output outside configured storage was found.

## 12. Approval and Workflow Findings

Approval records are append-only after a terminal decision, duplicate pending requests are prevented
inside a SQLite write transaction, approved content versions supersede prior approved versions, and
rejected history is preserved.

Direct services enforce approved scripts for scene planning and approved/latest content for most
downstream operations. The workflow layer does not enforce equivalent invariants. Specifically,
`SCENE_PLAN_APPROVED`, `ASSETS_APPROVED`, `RENDER_VERIFIED`, `METADATA_APPROVED`,
`THUMBNAIL_APPROVED`, and `SAFETY_REVIEW_COMPLETED` can advance based on event payloads without
loading and proving the persisted decision. `SAFETY_REVIEW_COMPLETED` correctly stops before
publishing, but its trusted status string can falsely complete Milestone 8.5.

## 13. Safety Engine Findings

The engine is deterministic and uses advisory language. It does not claim legal certainty and an
LLM is not in the decision path. Generated assets trigger disclosure; manual unknown rights trigger
review; missing/rejected assets and failed checks block; reports and findings are historical and
fingerprint-idempotent.

The main defect is package selection in `run_publishing_gate()`. Checks must operate on the selected
script/metadata/thumbnail/render inputs and must synthesize blocking findings when required inputs
are absent instead of raising before report creation. Add tests for missing render, metadata,
thumbnail and explicit non-latest metadata/thumbnail IDs.

AI disclosure currently forces `NEEDS_REVIEW`, which is conservative and appropriate for a manual
MVP. A future LLM may propose summaries but must never supply or override deterministic gate status.

## 14. Dashboard and CLI Findings

The dashboard displays project, research, script, scenes, assets, renders, metadata, thumbnail,
safety/gate, approvals and jobs. The smoke test received HTTP 200 from all nine project-stage pages.
Safe preview routes exist for images/audio metadata, thumbnails and renders. Project detail includes
status and next-action summaries, although advanced actions still rely on CLI.

CLI coverage is broad after project creation, but discoverability is weak:

- no channel/project bootstrap commands;
- no top-level project listing command;
- many commands require IDs that must be found in dashboard output or prior command output;
- top-level help has command names but no descriptions/groups;
- README documents only later-stage demos, not one clean start-to-gate flow.

## 15. Test Coverage Findings

The suite is meaningful for schemas, queue claims/retries, cache corruption, filesystem traversal,
content versions, approvals, individual providers, CLI handlers, dashboard pages and `0010`
migration preservation. It runs without network, GPU, paid APIs, FFmpeg or external services.

Important missing tests:

1. failure injection between orchestrator side effects and workflow event commit;
2. rejection of unapproved scene/metadata/thumbnail/render workflow events;
3. approved scene asset regeneration/import protection;
4. concurrent scene asset planning and render/packaging creation;
5. publishing gate with missing inputs and explicit non-latest package IDs;
6. research brief/source-report retry idempotency;
7. local text-provider model/settings fingerprint changes;
8. file-signature mismatch and interrupted manual imports;
9. a committed clean-database service/CLI smoke flow;
10. dashboard tests that validate more content semantics rather than only status/text markers.

## 16. End-to-End Smoke-Test Results

A disposable SQLite database and data root were created under `.audit_tmp`, exercised, and removed.
The run used real application services with fake image, voice, video, metadata and thumbnail
providers.

Succeeded:

- source import/snapshot, approval, claim link and verification;
- research readiness, brief and source report;
- script, fact-check, quality check and script approval;
- scene plan, two persisted scenes and scene-plan approval;
- four planned/generated/approved scene assets;
- fake render composition, verification and approval;
- metadata generation and approval;
- thumbnail concept, 128x72 PNG generation and approval;
- six safety findings, disclosure decision and publishing gate;
- dashboard project, research, script, scenes, assets, renders, metadata, thumbnail and safety pages.

Files produced included two PNG scene visuals, two WAV narration files, one fake MP4, one thumbnail
PNG, one source snapshot and source metadata JSON. The final gate was `NEEDS_REVIEW` because AI
disclosure was required, which is expected policy behavior.

Manual manipulation required: initial `Channel` and `VideoProject` ORM insertion, plus test-only
dashboard session-factory injection because no CLI bootstrap exists and dashboard sessions are
module-global. No later pipeline stage required direct SQL mutation.

## 17. Overengineering Assessment

The project is not materially overengineered. SQLite, a modular monolith, server-rendered dashboard,
database queue, explicit workflow state, and fake providers are proportionate to the goal. LangGraph
remaining optional is the correct choice.

Complexity is beginning to concentrate in large service/query modules and duplicated service-owned
transaction patterns. Do not introduce repositories, event buses, microservices, Redis, Celery or a
frontend rewrite. Extract a shared unit-of-work boundary only where required to make workflow events
atomic. Postpone Shorts, Telegram, analytics, autonomous publishing, multi-channel scheduling and
external safety APIs until one real-model long-form package is repeatedly good.

MVP direction answers:

- One reusable engine: yes.
- Channels primarily as configuration: structurally yes, though the first-channel style is still
  hardcoded in some rule-based prompts and metadata defaults.
- Providers replaceable: yes, with contract hardening needed for real models.
- Zero paid APIs: yes.
- Database as operational truth: yes, except filesystem bytes remain integrity-linked external state.
- Important outputs versioned/auditable: mostly yes.
- Approvals enforceable: in direct services, not fully in workflow events.
- Jobs restart-safe: queue yes; composed workflow side effects not fully.
- Suitable for local model adapters: yes after focused fixes.
- Inspectable fake/manual package today: yes, demonstrated.

## 18. Missing MVP Capabilities

- CLI/dashboard project creation and one guided start-to-gate flow.
- Reliable transaction composition for workflow events.
- Asset revision/immutability policy for approved scene media.
- Correct selected-package publishing gate behavior.
- Real local text/image/voice providers and their operational controls.
- Caption/subtitle generation and a stronger final-render quality pass.
- Exportable local publishing package/checklist; publishing itself should remain manual.

## 19. Recommended Fixes Before Milestone 9A

### Must fix

1. Make workflow event record, workflow state, created jobs and approval decisions one recoverable
   unit, or implement deterministic side-effect keys that make crash replay provably idempotent.
2. Validate persisted approval/review/verification/gate records for every workflow transition.
3. Reject regeneration/import of approved scene assets or create a new asset revision/path.
4. Make publishing-gate checks use explicit selected inputs and produce blocked reports for missing
   inputs.
5. Extend text provider and script fingerprint contracts with model version, provider settings,
   timeout/cancellation and typed failures before adding Ollama.

### Should fix

1. Add channel/project create/list CLI commands and document one complete local flow.
2. Make research brief/source-report generation idempotent for identical inputs.
3. Default render planning to approved assets and add a unique scene/role planning invariant.
4. Use atomic writes and signature checks for manual media imports.
5. Align dashboard session creation with app-injected settings.
6. Update README, old architecture limitations, task status and ADR numbering/index.
7. Decide and document support expectations for historical multi-revision downgrades.

### Can defer

- Splitting large cohesive modules.
- Database triggers for content immutability.
- PostgreSQL, Redis, Celery, Docker and cloud storage.
- Authentication while dashboard remains localhost-only.
- Real plagiarism/copyright services, OCR and platform-specific policy APIs.
- Telegram, analytics, Shorts and automated publishing.

## 20. Milestone 9A Readiness Decision

**`READY_FOR_9A_AFTER_FIXES`**

The provider boundary is close, Pydantic protects downstream structured documents, fake/manual
providers can remain defaults, CPU/GPU resource classes already exist, and deterministic safety
decisions are separate from generation. The blockers are the text contract/fingerprint omissions
and the workflow/immutability issues that a slower, nondeterministic provider would make more
frequent and costly. Complete Milestone 8.6 first; then add Ollama only for script generation before
expanding it to metadata or thumbnail concepts.

## 21. Recommended Next Five Milestones

1. **8.6 - Reliability and audit remediation:** workflow atomicity, persisted transition validation,
   approved-asset immutability, selected-package safety gate, CLI project bootstrap and regression
   tests.
2. **9A - Ollama local LLM provider:** script generation first, strict output/timeout/failure/cache
   behavior, fake/manual providers retained.
3. **9B - ComfyUI local image provider:** versioned scene assets, resource-aware queue execution,
   deterministic workflow settings.
4. **9C - Local TTS provider:** one approved engine, voice configuration, format validation and
   narration quality checks.
5. **9D - Real-model end-to-end quality pass:** one complete AI & Future episode, captions/final
   render checks, packaging quality, rights review and manual export checklist.

Shorts should follow proven long-form quality and an exportable manual publishing package, not
precede them.
