"""Minimal local CLI for Milestone 2 queue operations."""

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from sqlalchemy import select

from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.assets import (
    AssetPlanningService,
    AssetReviewService,
    ImageAssetService,
    VoiceAssetService,
)
from ai_media_os.application.cache import CacheKeyRequest, CacheService
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.packaging import MetadataService, ThumbnailService
from ai_media_os.application.prompt_templates import PromptTemplateService
from ai_media_os.application.renders import (
    RenderPlanningService,
    RenderReviewService,
    VideoCompositionService,
)
from ai_media_os.application.research import (
    ClaimService,
    ResearchNoteService,
    ResearchReportService,
    SourceService,
)
from ai_media_os.application.scenes import ScenePlanService
from ai_media_os.application.scripts import ScriptGenerationService
from ai_media_os.domain.enums import (
    ApprovalType,
    AssetReviewStatus,
    ClaimImportance,
    ClaimSupportType,
    ContentFormat,
    ContentType,
    RenderStatus,
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
from ai_media_os.workers.asset_handlers import asset_job_handlers
from ai_media_os.workers.job_worker import JobWorker
from ai_media_os.workers.packaging_handlers import packaging_job_handlers
from ai_media_os.workers.render_handlers import render_job_handlers
from ai_media_os.workers.research_handlers import research_job_handlers
from ai_media_os.workers.script_scene_handlers import script_scene_job_handlers


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

    generate_script = subcommands.add_parser("generate-script")
    generate_script.add_argument("--project-id", required=True)
    generate_script.add_argument("--revision-feedback")

    fact_check = subcommands.add_parser("generate-fact-check")
    fact_check.add_argument("--project-id", required=True)
    fact_check.add_argument("--script-version-id")

    script_quality = subcommands.add_parser("evaluate-script")
    script_quality.add_argument("--project-id", required=True)
    script_quality.add_argument("--script-version-id")

    scene_plan = subcommands.add_parser("generate-scene-plan")
    scene_plan.add_argument("--project-id", required=True)
    scene_plan.add_argument("--script-version-id")

    import_scene_plan = subcommands.add_parser("import-scene-plan")
    import_scene_plan.add_argument("--project-id", required=True)
    import_scene_plan.add_argument("--script-version-id", required=True)
    import_scene_plan.add_argument("--file", required=True)

    list_scenes = subcommands.add_parser("list-scenes")
    list_scenes.add_argument("--scene-plan-version-id", required=True)

    plan_assets = subcommands.add_parser("plan-scene-assets")
    plan_assets.add_argument("--project-id", required=True)
    plan_assets.add_argument("--scene-plan-version-id")

    generate_image = subcommands.add_parser("generate-scene-image")
    generate_image.add_argument("--scene-id", required=True)
    generate_image.add_argument("--width", type=int)
    generate_image.add_argument("--height", type=int)
    generate_image.add_argument("--seed", type=int, default=1)

    import_image = subcommands.add_parser("import-scene-image")
    import_image.add_argument("--scene-id", required=True)
    import_image.add_argument("--file", required=True)

    generate_voice = subcommands.add_parser("generate-scene-voice")
    generate_voice.add_argument("--scene-id", required=True)
    generate_voice.add_argument("--voice-name")
    generate_voice.add_argument("--language")
    generate_voice.add_argument("--speaking-rate", type=float, default=1.0)
    generate_voice.add_argument("--seed", type=int, default=1)

    import_audio = subcommands.add_parser("import-scene-audio")
    import_audio.add_argument("--scene-id", required=True)
    import_audio.add_argument("--file", required=True)

    list_assets = subcommands.add_parser("list-assets")
    list_assets.add_argument("--project-id", required=True)

    review_asset = subcommands.add_parser("review-asset")
    review_asset.add_argument("asset_id")
    review_asset.add_argument(
        "--status",
        required=True,
        choices=[item.value for item in AssetReviewStatus],
    )

    verify_asset = subcommands.add_parser("verify-asset-file")
    verify_asset.add_argument("asset_id")

    plan_render = subcommands.add_parser("plan-render")
    plan_render.add_argument("--project-id", required=True)
    plan_render.add_argument("--scene-plan-version-id")
    plan_render.add_argument("--width", type=int)
    plan_render.add_argument("--height", type=int)
    plan_render.add_argument("--fps", type=int)

    compose_video = subcommands.add_parser("compose-video")
    compose_video.add_argument("--project-id", required=True)
    compose_video.add_argument("--render-id")

    verify_render = subcommands.add_parser("verify-render")
    verify_render.add_argument("--project-id")
    verify_render.add_argument("--render-id")

    list_renders = subcommands.add_parser("list-renders")
    list_renders.add_argument("--project-id", required=True)

    review_render = subcommands.add_parser("review-render")
    review_render.add_argument("render_id")
    review_render.add_argument(
        "--status",
        required=True,
        choices=[
            RenderStatus.APPROVED.value,
            RenderStatus.REJECTED.value,
            RenderStatus.CHANGES_REQUESTED.value,
        ],
    )

    generate_metadata = subcommands.add_parser("generate-metadata")
    generate_metadata.add_argument("--project-id", required=True)
    generate_metadata.add_argument("--render-id")
    generate_metadata.add_argument("--keyword-hints")
    generate_metadata.add_argument("--title-count", type=int)
    generate_metadata.add_argument("--tag-count", type=int)

    import_metadata = subcommands.add_parser("import-metadata")
    import_metadata.add_argument("--project-id", required=True)
    import_metadata.add_argument("--content")
    import_metadata.add_argument("--file")
    import_metadata.add_argument("--parent-version-id")

    revise_metadata = subcommands.add_parser("revise-metadata")
    revise_metadata.add_argument("--parent-version-id", required=True)
    revise_metadata.add_argument("--content")
    revise_metadata.add_argument("--file")

    list_metadata = subcommands.add_parser("list-metadata")
    list_metadata.add_argument("--project-id", required=True)

    review_metadata = subcommands.add_parser("review-metadata")
    review_metadata.add_argument("content_version_id")

    generate_thumbnail_concept = subcommands.add_parser("generate-thumbnail-concept")
    generate_thumbnail_concept.add_argument("--project-id", required=True)
    generate_thumbnail_concept.add_argument("--metadata-version-id")

    generate_thumbnail = subcommands.add_parser("generate-thumbnail")
    generate_thumbnail.add_argument("--project-id", required=True)
    generate_thumbnail.add_argument("--metadata-version-id")
    generate_thumbnail.add_argument("--concept-version-id")
    generate_thumbnail.add_argument("--width", type=int)
    generate_thumbnail.add_argument("--height", type=int)
    generate_thumbnail.add_argument("--seed", type=int, default=1)

    import_thumbnail = subcommands.add_parser("import-thumbnail")
    import_thumbnail.add_argument("--project-id", required=True)
    import_thumbnail.add_argument("--file", required=True)
    import_thumbnail.add_argument("--metadata-version-id")
    import_thumbnail.add_argument("--concept-version-id")

    list_thumbnails = subcommands.add_parser("list-thumbnails")
    list_thumbnails.add_argument("--project-id", required=True)

    review_thumbnail = subcommands.add_parser("review-thumbnail")
    review_thumbnail.add_argument("asset_id")
    review_thumbnail.add_argument(
        "--status",
        required=True,
        choices=[item.value for item in AssetReviewStatus],
    )

    verify_thumbnail = subcommands.add_parser("verify-thumbnail-file")
    verify_thumbnail.add_argument("asset_id")

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
            handlers = (
                research_job_handlers()
                | script_scene_job_handlers()
                | asset_job_handlers()
                | render_job_handlers()
                | packaging_job_handlers()
            )
            worker = JobWorker(session, handlers=handlers, worker_id=args.worker_id)
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
        if args.command == "generate-script":
            version = ScriptGenerationService(session).generate_script(
                args.project_id,
                revision_feedback=args.revision_feedback,
            )
            print(version.id)
            return 0
        if args.command == "generate-fact-check":
            version = ScriptGenerationService(session).generate_fact_check_report(
                args.project_id,
                script_version_id=args.script_version_id,
            )
            print(version.id)
            return 0
        if args.command == "evaluate-script":
            script_quality_result = ScriptGenerationService(session).evaluate_script_quality(
                args.project_id,
                script_version_id=args.script_version_id,
            )
            print(script_quality_result.as_dict())
            return 0
        if args.command == "generate-scene-plan":
            version = ScenePlanService(session).generate_scene_plan(
                args.project_id,
                script_version_id=args.script_version_id,
            )
            print(version.id)
            return 0
        if args.command == "import-scene-plan":
            content = Path(args.file).read_text(encoding="utf-8")
            version = ScenePlanService(session).import_scene_plan(
                args.project_id,
                script_version_id=args.script_version_id,
                content=content,
            )
            print(version.id)
            return 0
        if args.command == "list-scenes":
            scenes = ScenePlanService(session).list_scenes(args.scene_plan_version_id)
            for scene in scenes:
                print(
                    f"{scene.scene_number}\t{scene.duration_seconds}\t"
                    f"{scene.visual_type.value}\t{scene.narration[:80]}"
                )
            return 0
        if args.command == "plan-scene-assets":
            assets = AssetPlanningService(session).plan_scene_assets(
                args.project_id,
                scene_plan_version_id=args.scene_plan_version_id,
            )
            print(len(assets))
            return 0
        if args.command == "generate-scene-image":
            asset = ImageAssetService(session).generate_for_scene(
                args.scene_id,
                width=args.width,
                height=args.height,
                seed=args.seed,
            )
            print(asset.id)
            return 0
        if args.command == "import-scene-image":
            asset = ImageAssetService(session).import_manual(args.scene_id, Path(args.file))
            print(asset.id)
            return 0
        if args.command == "generate-scene-voice":
            asset = VoiceAssetService(session).generate_for_scene(
                args.scene_id,
                voice_name=args.voice_name,
                language=args.language,
                speaking_rate=args.speaking_rate,
                seed=args.seed,
            )
            print(asset.id)
            return 0
        if args.command == "import-scene-audio":
            asset = VoiceAssetService(session).import_manual(args.scene_id, Path(args.file))
            print(asset.id)
            return 0
        if args.command == "list-assets":
            assets = AssetReviewService(session).list_project_assets(args.project_id)
            for asset in assets:
                scene_number = asset.scene.scene_number if asset.scene is not None else ""
                print(
                    f"{asset.id}\t{scene_number}\t{asset.asset_role.value}\t"
                    f"{asset.generation_status.value}\t{asset.review_status.value}"
                )
            return 0
        if args.command == "review-asset":
            asset = AssetReviewService(session).review_asset(
                args.asset_id,
                AssetReviewStatus(args.status),
            )
            print(asset.review_status.value)
            return 0
        if args.command == "verify-asset-file":
            verify_result = AssetReviewService(session).verify_asset_file(args.asset_id)
            print("OK" if verify_result.ok else f"FAIL:{verify_result.reason}")
            return 0
        if args.command == "plan-render":
            render = RenderPlanningService(session).plan_render(
                args.project_id,
                scene_plan_version_id=args.scene_plan_version_id,
                width=args.width,
                height=args.height,
                fps=args.fps,
            )
            print(render.id)
            return 0
        if args.command == "compose-video":
            render = VideoCompositionService(session).compose_video(
                args.project_id,
                render_id=args.render_id,
            )
            print(render.id)
            return 0
        if args.command == "verify-render":
            render_id = args.render_id
            if render_id is None and args.project_id is not None:
                renders = RenderReviewService(session).list_project_renders(args.project_id)
                render_id = renders[0].id if renders else None
            if render_id is None:
                print("FAIL:missing-render")
                return 1
            render_verify_result = RenderReviewService(session).verify_render(render_id)
            print("OK" if render_verify_result.ok else f"FAIL:{render_verify_result.reason}")
            return 0 if render_verify_result.ok else 1
        if args.command == "list-renders":
            renders = RenderReviewService(session).list_project_renders(args.project_id)
            for render in renders:
                print(
                    f"{render.id}\tv{render.version_number}\t{render.status.value}\t"
                    f"{render.output_path}\t{render.content_hash or ''}"
                )
            return 0
        if args.command == "review-render":
            render = RenderReviewService(session).review_render(
                args.render_id,
                RenderStatus(args.status),
            )
            print(render.status.value)
            return 0
        if args.command == "generate-metadata":
            version = MetadataService(session).generate_metadata(
                args.project_id,
                render_id=args.render_id,
                keyword_hints=_csv_items(args.keyword_hints),
                title_count=args.title_count,
                tag_count=args.tag_count,
            )
            print(version.id)
            return 0
        if args.command == "import-metadata":
            content = _content_arg(args.content, args.file)
            version = MetadataService(session).import_metadata(
                args.project_id,
                content,
                parent_version_id=args.parent_version_id,
            )
            print(version.id)
            return 0
        if args.command == "revise-metadata":
            content = _content_arg(args.content, args.file)
            version = MetadataService(session).revise_metadata(
                args.parent_version_id,
                content,
            )
            print(version.id)
            return 0
        if args.command == "list-metadata":
            versions = MetadataService(session).list_metadata(args.project_id)
            for version in versions:
                print(
                    f"{version.id}\tv{version.version_number}\t{version.status.value}\t"
                    f"{version.content_hash}"
                )
            return 0
        if args.command == "review-metadata":
            MetadataService(session).request_metadata_approval(args.content_version_id)
            print(args.content_version_id)
            return 0
        if args.command == "generate-thumbnail-concept":
            version = ThumbnailService(session).generate_concept(
                args.project_id,
                metadata_version_id=args.metadata_version_id,
            )
            print(version.id)
            return 0
        if args.command == "generate-thumbnail":
            asset = ThumbnailService(session).generate_thumbnail(
                args.project_id,
                metadata_version_id=args.metadata_version_id,
                concept_version_id=args.concept_version_id,
                width=args.width,
                height=args.height,
                seed=args.seed,
            )
            print(asset.id)
            return 0
        if args.command == "import-thumbnail":
            asset = ThumbnailService(session).import_thumbnail(
                args.project_id,
                Path(args.file),
                metadata_version_id=args.metadata_version_id,
                concept_version_id=args.concept_version_id,
            )
            print(asset.id)
            return 0
        if args.command == "list-thumbnails":
            thumbnails = ThumbnailService(session).list_thumbnails(args.project_id)
            for asset in thumbnails:
                print(
                    f"{asset.id}\t{asset.generation_status.value}\t"
                    f"{asset.review_status.value}\t{asset.content_hash or ''}"
                )
            return 0
        if args.command == "review-thumbnail":
            asset = ThumbnailService(session).review_thumbnail(
                args.asset_id,
                AssetReviewStatus(args.status),
            )
            print(asset.review_status.value)
            return 0
        if args.command == "verify-thumbnail-file":
            verification = ThumbnailService(session).verify_thumbnail_file(args.asset_id)
            print("OK" if verification.ok else f"FAIL:{verification.reason}")
            return 0 if verification.ok else 1
    return 1


def _content_arg(content: str | None, file_path: str | None) -> str:
    if content is not None:
        return content
    if file_path is not None:
        return Path(file_path).read_text(encoding="utf-8")
    raise ValueError("Provide --content or --file.")


def _csv_items(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
