"""Minimal local CLI for Milestone 2 queue operations."""

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from sqlalchemy import select

from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.cache import CacheKeyRequest, CacheService
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.prompt_templates import PromptTemplateService
from ai_media_os.application.research import (
    ClaimService,
    ResearchNoteService,
    ResearchReportService,
    SourceService,
)
from ai_media_os.domain.enums import (
    ApprovalType,
    ClaimImportance,
    ClaimSupportType,
    ContentFormat,
    ContentType,
    ResearchNoteType,
    ResourceClass,
    SourceAuthorityTier,
    SourceStatus,
    SourceType,
    VerificationStatus,
)
from ai_media_os.infrastructure.database.models import Job
from ai_media_os.infrastructure.database.session import SessionLocal
from ai_media_os.infrastructure.settings import get_settings
from ai_media_os.workers.job_worker import JobWorker
from ai_media_os.workers.research_handlers import research_job_handlers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-media-os")
    subcommands = parser.add_subparsers(dest="command", required=True)

    create_job = subcommands.add_parser("create-job")
    create_job.add_argument("--project-id", required=True)
    create_job.add_argument("--job-type", required=True)
    create_job.add_argument("--priority", type=int, default=100)
    create_job.add_argument(
        "--resource-class",
        choices=[item.value for item in ResourceClass],
        default="CPU_LIGHT",
    )

    subcommands.add_parser("list-jobs")

    run_worker = subcommands.add_parser("run-worker")
    run_worker.add_argument("--worker-id")

    subcommands.add_parser("recover-stale-jobs")

    cancel_job = subcommands.add_parser("cancel-job")
    cancel_job.add_argument("job_id")

    pause_job = subcommands.add_parser("pause-job")
    pause_job.add_argument("job_id")

    resume_job = subcommands.add_parser("resume-job")
    resume_job.add_argument("job_id")

    create_version = subcommands.add_parser("create-content-version")
    create_version.add_argument("--project-id", required=True)
    create_version.add_argument(
        "--type", required=True, choices=[item.value for item in ContentType]
    )
    create_version.add_argument(
        "--format", required=True, choices=[item.value for item in ContentFormat]
    )
    create_version.add_argument("--content", required=True)

    list_versions = subcommands.add_parser("list-content-versions")
    list_versions.add_argument("--project-id", required=True)
    list_versions.add_argument(
        "--type", required=True, choices=[item.value for item in ContentType]
    )

    request_approval = subcommands.add_parser("request-approval")
    request_approval.add_argument("--project-id", required=True)
    request_approval.add_argument(
        "--type", required=True, choices=[item.value for item in ApprovalType]
    )
    request_approval.add_argument("--content-version-id")
    request_approval.add_argument("--job-id")

    for command_name in ("approve", "reject", "request-changes"):
        command = subcommands.add_parser(command_name)
        command.add_argument("approval_id")
        command.add_argument("--feedback")

    create_prompt = subcommands.add_parser("create-prompt-version")
    create_prompt.add_argument("--name", required=True)
    create_prompt.add_argument("--category", required=True)
    create_prompt.add_argument("--template-text", required=True)

    activate_prompt = subcommands.add_parser("activate-prompt")
    activate_prompt.add_argument("prompt_template_id")

    cache_put = subcommands.add_parser("cache-put-text")
    cache_put.add_argument("--operation", required=True)
    cache_put.add_argument("--provider", required=True)
    cache_put.add_argument("--model")
    cache_put.add_argument("--text", required=True)

    cache_get = subcommands.add_parser("cache-get")
    cache_get.add_argument("cache_key")

    cache_verify = subcommands.add_parser("cache-verify")
    cache_verify.add_argument("cache_key")

    cache_invalidate = subcommands.add_parser("cache-invalidate")
    cache_invalidate.add_argument("cache_key")
    cache_invalidate.add_argument("--reason", default="Manual invalidation")

    import_source = subcommands.add_parser("import-source")
    import_source.add_argument("--project-id", required=True)
    import_source.add_argument("--url", required=True)
    import_source.add_argument("--title")
    import_source.add_argument("--publisher")
    import_source.add_argument("--author")
    import_source.add_argument("--source-type", choices=[item.value for item in SourceType])
    import_source.add_argument(
        "--authority-tier", choices=[item.value for item in SourceAuthorityTier]
    )
    import_source.add_argument("--text")
    import_source.add_argument("--file")
    import_source.add_argument("--notes")

    list_sources = subcommands.add_parser("list-sources")
    list_sources.add_argument("--project-id", required=True)

    review_source = subcommands.add_parser("review-source")
    review_source.add_argument("source_id")
    review_source.add_argument(
        "--status",
        required=True,
        choices=[item.value for item in SourceStatus],
    )

    add_note = subcommands.add_parser("add-research-note")
    add_note.add_argument("--project-id", required=True)
    add_note.add_argument("--source-id", required=True)
    add_note.add_argument(
        "--type",
        required=True,
        choices=[item.value for item in ResearchNoteType],
    )
    add_note.add_argument("--content", required=True)
    add_note.add_argument("--source-location")

    list_notes = subcommands.add_parser("list-research-notes")
    list_notes.add_argument("--project-id", required=True)

    create_claim = subcommands.add_parser("create-claim")
    create_claim.add_argument("--project-id", required=True)
    create_claim.add_argument("--text", required=True)
    create_claim.add_argument(
        "--importance", choices=[item.value for item in ClaimImportance], default="medium"
    )
    create_claim.add_argument("--confidence", type=float)

    link_claim = subcommands.add_parser("link-claim-source")
    link_claim.add_argument("--claim-id", required=True)
    link_claim.add_argument("--source-id", required=True)
    link_claim.add_argument(
        "--support-type", required=True, choices=[item.value for item in ClaimSupportType]
    )
    link_claim.add_argument("--excerpt")
    link_claim.add_argument("--source-location")
    link_claim.add_argument("--notes")

    verify_claim = subcommands.add_parser("verify-claim")
    verify_claim.add_argument("claim_id")
    verify_claim.add_argument(
        "--status",
        required=True,
        choices=[item.value for item in VerificationStatus],
    )
    verify_claim.add_argument("--override-reason")

    research_brief = subcommands.add_parser("generate-research-brief")
    research_brief.add_argument("--project-id", required=True)

    source_report = subcommands.add_parser("generate-source-report")
    source_report.add_argument("--project-id", required=True)
    source_report.add_argument("--format", choices=["markdown", "json"], default="markdown")

    evaluate_research = subcommands.add_parser("evaluate-research")
    evaluate_research.add_argument("--project-id", required=True)

    dashboard = subcommands.add_parser("dashboard")
    dashboard.add_argument("--host")
    dashboard.add_argument("--port", type=int)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "dashboard":
        settings = get_settings()
        uvicorn.run(
            "ai_media_os.web:app",
            host=args.host or settings.dashboard_host,
            port=args.port or settings.dashboard_port,
            reload=False,
        )
        return 0

    with SessionLocal() as session:
        queue = QueueService(session)
        if args.command == "create-job":
            job = queue.create_job(
                video_project_id=args.project_id,
                job_type=args.job_type,
                priority=args.priority,
                resource_class=ResourceClass(args.resource_class),
            )
            print(job.id)
            return 0
        if args.command == "list-jobs":
            for job in session.scalars(select(Job).order_by(Job.created_at.asc())):
                print(f"{job.id}\t{job.status.value}\t{job.job_type}\t{job.claimed_by or ''}")
            return 0
        if args.command == "run-worker":
            worker = JobWorker(session, handlers=research_job_handlers(), worker_id=args.worker_id)
            worker_result = worker.run_once()
            print(worker_result)
            return 0
        if args.command == "recover-stale-jobs":
            print(queue.recover_stale_jobs())
            return 0
        if args.command == "cancel-job":
            print(queue.cancel_job(args.job_id).status.value)
            return 0
        if args.command == "pause-job":
            print(queue.pause_job(args.job_id).status.value)
            return 0
        if args.command == "resume-job":
            print(queue.resume_job(args.job_id).status.value)
            return 0
        if args.command == "create-content-version":
            version = ContentVersionService(session).create_initial_version(
                video_project_id=args.project_id,
                content_type=ContentType(args.type),
                content=args.content,
                content_format=ContentFormat(args.format),
            )
            print(version.id)
            return 0
        if args.command == "list-content-versions":
            versions = ContentVersionService(session).version_history(
                args.project_id,
                ContentType(args.type),
            )
            for version in versions:
                print(f"{version.id}\tv{version.version_number}\t{version.status.value}")
            return 0
        if args.command == "request-approval":
            approval = ApprovalService(session).request_approval(
                video_project_id=args.project_id,
                approval_type=ApprovalType(args.type),
                content_version_id=args.content_version_id,
                job_id=args.job_id,
            )
            print(approval.id)
            return 0
        if args.command == "approve":
            print(
                ApprovalService(session)
                .approve(args.approval_id, feedback=args.feedback)
                .status.value
            )
            return 0
        if args.command == "reject":
            print(
                ApprovalService(session)
                .reject(args.approval_id, feedback=args.feedback)
                .status.value
            )
            return 0
        if args.command == "request-changes":
            print(
                ApprovalService(session)
                .request_changes(args.approval_id, feedback=args.feedback)
                .status.value
            )
            return 0
        if args.command == "create-prompt-version":
            prompt = PromptTemplateService(session).create_prompt_version(
                name=args.name,
                category=args.category,
                template_text=args.template_text,
            )
            print(prompt.id)
            return 0
        if args.command == "activate-prompt":
            print(
                PromptTemplateService(session).activate_prompt(args.prompt_template_id).status.value
            )
            return 0
        if args.command == "cache-put-text":
            request = CacheKeyRequest(
                operation=args.operation,
                provider=args.provider,
                model=args.model,
            )
            entry = CacheService(session).store_text(request, args.text)
            print(entry.cache_key)
            return 0
        if args.command == "cache-get":
            cache_result = CacheService(session).lookup(args.cache_key)
            print(cache_result.path if cache_result.hit else f"MISS:{cache_result.reason}")
            return 0
        if args.command == "cache-verify":
            cache_result = CacheService(session).verify_entry(args.cache_key)
            print("OK" if cache_result.hit else f"MISS:{cache_result.reason}")
            return 0
        if args.command == "cache-invalidate":
            print(CacheService(session).invalidate_entry(args.cache_key, args.reason))
            return 0
        if args.command == "import-source":
            result = SourceService(session).import_source(
                video_project_id=args.project_id,
                url=args.url,
                title=args.title,
                publisher=args.publisher,
                author=args.author,
                source_type=SourceType(args.source_type) if args.source_type else None,
                authority_tier=(
                    SourceAuthorityTier(args.authority_tier) if args.authority_tier else None
                ),
                text=args.text,
                snapshot_file=None if args.file is None else Path(args.file),
                notes=args.notes,
            )
            print(result.source.id)
            return 0
        if args.command == "list-sources":
            sources = SourceService(session).list_project_sources(args.project_id)
            for source in sources:
                print(f"{source.id}\t{source.status.value}\t{source.canonical_url}")
            return 0
        if args.command == "review-source":
            source = SourceService(session).update_source_status(
                args.source_id,
                SourceStatus(args.status),
            )
            print(source.status.value)
            return 0
        if args.command == "add-research-note":
            note = ResearchNoteService(session).create_note(
                video_project_id=args.project_id,
                source_id=args.source_id,
                note_type=ResearchNoteType(args.type),
                content=args.content,
                source_location=args.source_location,
            )
            print(note.id)
            return 0
        if args.command == "list-research-notes":
            notes = ResearchNoteService(session).list_project_notes(args.project_id)
            for note in notes:
                print(f"{note.id}\t{note.note_type.value}\t{note.source_id}\t{note.content}")
            return 0
        if args.command == "create-claim":
            claim = ClaimService(session).create_claim(
                video_project_id=args.project_id,
                claim_text=args.text,
                importance=ClaimImportance(args.importance),
                confidence=args.confidence,
            )
            print(claim.id)
            return 0
        if args.command == "link-claim-source":
            link = ClaimService(session).link_source(
                claim_id=args.claim_id,
                source_id=args.source_id,
                support_type=ClaimSupportType(args.support_type),
                quoted_excerpt=args.excerpt,
                source_location=args.source_location,
                notes=args.notes,
            )
            print(link.id)
            return 0
        if args.command == "verify-claim":
            claim = ClaimService(session).update_verification_status(
                args.claim_id,
                VerificationStatus(args.status),
                override_reason=args.override_reason,
            )
            print(claim.verification_status.value)
            return 0
        if args.command == "generate-research-brief":
            version = ResearchReportService(session).generate_research_brief(args.project_id)
            print(version.id)
            return 0
        if args.command == "generate-source-report":
            version = ResearchReportService(session).generate_source_report(
                args.project_id,
                content_format=ContentFormat(args.format),
            )
            print(version.id)
            return 0
        if args.command == "evaluate-research":
            readiness_result = ResearchReportService(session).evaluate_readiness(args.project_id)
            print(readiness_result.as_dict())
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
