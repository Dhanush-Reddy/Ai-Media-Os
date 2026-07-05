"""Minimal local CLI for Milestone 2 queue operations."""

import argparse
from collections.abc import Sequence

from sqlalchemy import select

from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.cache import CacheKeyRequest, CacheService
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.prompt_templates import PromptTemplateService
from ai_media_os.domain.enums import ApprovalType, ContentFormat, ContentType, ResourceClass
from ai_media_os.infrastructure.database.models import Job
from ai_media_os.infrastructure.database.session import SessionLocal
from ai_media_os.workers.job_worker import JobWorker


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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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
            worker = JobWorker(session, handlers={}, worker_id=args.worker_id)
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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
