"""Minimal local CLI for Milestone 2 queue operations."""

import argparse
from collections.abc import Sequence
from datetime import date
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
from ai_media_os.application.projects import ProjectCatalogService
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
from ai_media_os.application.safety import ContentSafetyService
from ai_media_os.application.safety_summaries import SafetySummaryService
from ai_media_os.application.scenes import ScenePlanService
from ai_media_os.application.scripts import ScriptGenerationService
from ai_media_os.domain.enums import (
    ApprovalType,
    AssetReviewStatus,
    AssetRole,
    ClaimImportance,
    ClaimSupportType,
    ContentFormat,
    ContentType,
    LicenseStatus,
    RenderStatus,
    ResearchNoteType,
    ResourceClass,
    SourceAuthorityTier,
    SourceStatus,
    SourceType,
    VerificationStatus,
)
from ai_media_os.infrastructure.database.models import Asset, Job
from ai_media_os.infrastructure.database.session import SessionLocal
from ai_media_os.infrastructure.settings import get_settings
from ai_media_os.providers.chatterbox import ChatterboxVoiceGenerationProvider
from ai_media_os.providers.comfyui import ComfyUIImageGenerationProvider
from ai_media_os.providers.image_provider_factory import build_image_provider
from ai_media_os.providers.ollama import OllamaTextGenerationProvider
from ai_media_os.providers.piper import PiperVoiceGenerationProvider
from ai_media_os.providers.text_generation import TextGenerationError, TextGenerationRequest
from ai_media_os.providers.text_provider_factory import (
    build_metadata_provider,
    build_text_provider,
    build_thumbnail_concept_provider,
)
from ai_media_os.providers.voice_provider_factory import build_voice_provider
from ai_media_os.workers.asset_handlers import asset_job_handlers
from ai_media_os.workers.job_worker import JobWorker
from ai_media_os.workers.packaging_handlers import packaging_job_handlers
from ai_media_os.workers.render_handlers import render_job_handlers
from ai_media_os.workers.research_handlers import research_job_handlers
from ai_media_os.workers.script_scene_handlers import script_scene_job_handlers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-media-os")
    subcommands = parser.add_subparsers(dest="command", required=True)

    create_channel = subcommands.add_parser("create-channel")
    create_channel.add_argument("--name", required=True)
    create_channel.add_argument("--slug", required=True)
    create_channel.add_argument("--niche", required=True)
    create_channel.add_argument("--language", default="en")

    subcommands.add_parser("list-channels")

    create_project = subcommands.add_parser("create-project")
    create_project.add_argument("--channel-id", required=True)
    create_project.add_argument("--working-title", required=True)
    create_project.add_argument("--topic", required=True)
    create_project.add_argument("--description")
    create_project.add_argument("--target-duration-seconds", type=int)

    list_projects = subcommands.add_parser("list-projects")
    list_projects.add_argument("--channel-id")

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
    generate_script.add_argument("--provider", choices=["fake", "ollama"])
    generate_script.add_argument("--model")

    fact_check = subcommands.add_parser("generate-fact-check")
    fact_check.add_argument("--project-id", required=True)
    fact_check.add_argument("--script-version-id")

    script_quality = subcommands.add_parser("evaluate-script")
    script_quality.add_argument("--project-id", required=True)
    script_quality.add_argument("--script-version-id")

    scene_plan = subcommands.add_parser("generate-scene-plan")
    scene_plan.add_argument("--project-id", required=True)
    scene_plan.add_argument("--script-version-id")
    scene_plan.add_argument("--provider", choices=["fake", "ollama"])
    scene_plan.add_argument("--model")

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
    generate_image.add_argument("--provider", choices=["fake", "comfyui"])
    generate_image.add_argument("--model")
    generate_image.add_argument("--workflow-path")
    generate_image.add_argument("--steps", type=int)
    generate_image.add_argument("--cfg", type=float)
    generate_image.add_argument("--sampler")
    generate_image.add_argument("--scheduler")
    generate_image.add_argument("--timeout-seconds", type=float)

    check_image_provider = subcommands.add_parser("check-image-provider")
    check_image_provider.add_argument("--provider", choices=["fake", "comfyui"], default="fake")
    check_image_provider.add_argument("--model")

    import_image = subcommands.add_parser("import-scene-image")
    import_image.add_argument("--scene-id", required=True)
    import_image.add_argument("--file", required=True)

    generate_voice = subcommands.add_parser("generate-scene-voice")
    generate_voice.add_argument("--scene-id", required=True)
    generate_voice.add_argument("--voice-name")
    generate_voice.add_argument("--language")
    generate_voice.add_argument("--speaking-rate", type=float, default=1.0)
    generate_voice.add_argument("--seed", type=int, default=1)
    generate_voice.add_argument("--provider", choices=["fake", "piper", "chatterbox"])
    generate_voice.add_argument("--model-path")
    generate_voice.add_argument("--reference-audio")
    generate_voice.add_argument("--exaggeration", type=float)
    generate_voice.add_argument("--cfg-weight", type=float)
    generate_voice.add_argument("--pronunciation", action="append", default=[])

    generate_narration = subcommands.add_parser("generate-scene-narration")
    generate_narration.add_argument("--scene-id", required=True)
    generate_narration.add_argument("--provider", choices=["fake", "piper", "chatterbox"])
    generate_narration.add_argument("--model-path")
    generate_narration.add_argument("--reference-audio")
    generate_narration.add_argument("--exaggeration", type=float)
    generate_narration.add_argument("--cfg-weight", type=float)
    generate_narration.add_argument("--voice")
    generate_narration.add_argument("--language")
    generate_narration.add_argument("--speaking-rate", type=float)
    generate_narration.add_argument("--seed", type=int, default=1)
    generate_narration.add_argument("--pronunciation", action="append", default=[])

    generate_project_narration = subcommands.add_parser("generate-project-narration")
    generate_project_narration.add_argument("--project-id", required=True)
    generate_project_narration.add_argument("--provider", choices=["fake", "piper", "chatterbox"])
    generate_project_narration.add_argument("--model-path")
    generate_project_narration.add_argument("--reference-audio")
    generate_project_narration.add_argument("--exaggeration", type=float)
    generate_project_narration.add_argument("--cfg-weight", type=float)
    generate_project_narration.add_argument("--voice")
    generate_project_narration.add_argument("--language")
    generate_project_narration.add_argument("--speaking-rate", type=float)
    generate_project_narration.add_argument("--seed", type=int, default=1)
    generate_project_narration.add_argument("--pronunciation", action="append", default=[])

    check_voice_provider = subcommands.add_parser("check-voice-provider")
    check_voice_provider.add_argument(
        "--provider", choices=["fake", "piper", "chatterbox"], default="fake"
    )
    check_voice_provider.add_argument("--model-path")
    check_voice_provider.add_argument("--voice")
    check_voice_provider.add_argument("--reference-audio")

    list_narration = subcommands.add_parser("list-narration-assets")
    list_narration.add_argument("--project-id", required=True)

    verify_audio = subcommands.add_parser("verify-audio-asset")
    verify_audio.add_argument("asset_id")

    preview_narration = subcommands.add_parser("preview-narration")
    preview_narration.add_argument("asset_id")

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

    record_asset_provenance = subcommands.add_parser("record-asset-provenance")
    record_asset_provenance.add_argument("asset_id")
    record_asset_provenance.add_argument("--source-url", required=True)
    record_asset_provenance.add_argument("--creator", required=True)
    record_asset_provenance.add_argument("--license-name", required=True)
    record_asset_provenance.add_argument("--license-url", required=True)
    record_asset_provenance.add_argument(
        "--license-status",
        required=True,
        choices=[item.value for item in LicenseStatus],
    )
    record_asset_provenance.add_argument(
        "--commercial-use-allowed", action=argparse.BooleanOptionalAction, required=True
    )
    record_asset_provenance.add_argument(
        "--attribution-required", action=argparse.BooleanOptionalAction, required=True
    )
    record_asset_provenance.add_argument("--model-file-hash", required=True)
    record_asset_provenance.add_argument("--config-file-hash")
    record_asset_provenance.add_argument("--model-filename")
    record_asset_provenance.add_argument("--config-filename")
    record_asset_provenance.add_argument("--model-card-url")
    record_asset_provenance.add_argument("--model-revision")
    record_asset_provenance.add_argument("--repository-license")
    record_asset_provenance.add_argument("--dataset-name")
    record_asset_provenance.add_argument("--dataset-license")
    record_asset_provenance.add_argument("--dataset-license-url")
    record_asset_provenance.add_argument("--review-date", type=date.fromisoformat)
    record_asset_provenance.add_argument(
        "--reviewer-decision",
        choices=["VERIFIED", "RESTRICTED", "BLOCKED", "NEEDS_REVIEW"],
    )
    record_asset_provenance.add_argument("--reviewer-notes")
    record_asset_provenance.add_argument("--attribution-text")

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
    generate_metadata.add_argument("--provider", choices=["fake", "ollama"])
    generate_metadata.add_argument("--model")

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
    generate_thumbnail_concept.add_argument("--provider", choices=["fake", "ollama"])
    generate_thumbnail_concept.add_argument("--model")

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

    check_asset_rights = subcommands.add_parser("check-asset-rights")
    check_asset_rights.add_argument("--project-id", required=True)

    check_claim_support = subcommands.add_parser("check-claims")
    check_claim_support.add_argument("--project-id", required=True)

    check_script_safety = subcommands.add_parser("check-script-safety")
    check_script_safety.add_argument("--project-id", required=True)

    check_metadata_safety = subcommands.add_parser("check-metadata-safety")
    check_metadata_safety.add_argument("--project-id", required=True)

    check_thumbnail_safety = subcommands.add_parser("check-thumbnail-safety")
    check_thumbnail_safety.add_argument("--project-id", required=True)

    check_reused_content = subcommands.add_parser("check-reused-content")
    check_reused_content.add_argument("--project-id", required=True)

    decide_ai_disclosure = subcommands.add_parser("decide-ai-disclosure")
    decide_ai_disclosure.add_argument("--project-id", required=True)

    run_publishing_gate = subcommands.add_parser("run-publishing-gate")
    run_publishing_gate.add_argument("--project-id", required=True)
    run_publishing_gate.add_argument("--render-id")
    run_publishing_gate.add_argument("--metadata-version-id")
    run_publishing_gate.add_argument("--thumbnail-asset-id")

    show_safety_report = subcommands.add_parser("show-safety-report")
    show_safety_report.add_argument("--project-id", required=True)

    list_safety_findings = subcommands.add_parser("list-safety-findings")
    list_safety_findings.add_argument("--project-id", required=True)

    summarize_safety = subcommands.add_parser("summarize-safety-report")
    summarize_safety.add_argument("--project-id", required=True)
    summarize_safety.add_argument("--provider", choices=["fake", "ollama"], default="fake")
    summarize_safety.add_argument("--model")

    verify_thumbnail = subcommands.add_parser("verify-thumbnail-file")
    verify_thumbnail.add_argument("asset_id")

    check_llm = subcommands.add_parser("check-llm-provider")
    check_llm.add_argument("--provider", choices=["fake", "ollama"], default="fake")
    check_llm.add_argument("--model")

    test_llm = subcommands.add_parser("test-llm-generate")
    test_llm.add_argument("--provider", choices=["fake", "ollama"], default="fake")
    test_llm.add_argument("--model")
    test_llm.add_argument("--prompt", required=True)
    test_llm.add_argument("--system-prompt")
    test_llm.add_argument("--json", action="store_true")

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

    if args.command in {"check-llm-provider", "test-llm-generate"}:
        settings = get_settings()
        try:
            provider = build_text_provider(settings, args.provider, args.model)
            if args.command == "check-llm-provider":
                if isinstance(provider, OllamaTextGenerationProvider):
                    health = provider.check_health()
                    print(health.message)
                    return 0 if health.reachable and health.model_available else 1
                print("Fake text provider is ready.")
                return 0
            llm_result = provider.generate(
                TextGenerationRequest(
                    prompt=args.prompt,
                    system_prompt=args.system_prompt,
                    provider_settings={"json_mode": args.json},
                    timeout_seconds=settings.ollama_request_timeout_seconds,
                )
            )
            print(llm_result.text)
            return 0
        except (TextGenerationError, ValueError) as exc:
            print(f"FAIL:{exc}")
            return 1

    with SessionLocal() as session:
        queue = QueueService(session)
        if args.command == "create-channel":
            channel = ProjectCatalogService(session).create_channel(
                name=args.name,
                slug=args.slug,
                niche=args.niche,
                language=args.language,
            )
            print(channel.id)
            return 0
        if args.command == "list-channels":
            for channel in ProjectCatalogService(session).list_channels():
                print(f"{channel.id}\t{channel.slug}\t{channel.name}\t{channel.status.value}")
            return 0
        if args.command == "create-project":
            project = ProjectCatalogService(session).create_project(
                channel_id=args.channel_id,
                working_title=args.working_title,
                topic=args.topic,
                description=args.description,
                target_duration_seconds=args.target_duration_seconds,
            )
            print(project.id)
            return 0
        if args.command == "list-projects":
            for project in ProjectCatalogService(session).list_projects(args.channel_id):
                print(
                    f"{project.id}\t{project.channel_id}\t{project.status.value}\t"
                    f"{project.working_title}"
                )
            return 0
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
            settings = get_settings()
            text_provider = build_text_provider(settings, args.provider, args.model)
            version = ScriptGenerationService(
                session,
                text_provider,
                timeout_seconds=settings.ollama_request_timeout_seconds,
            ).generate_script(
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
            settings = get_settings()
            text_provider = build_text_provider(settings, args.provider, args.model)
            version = ScenePlanService(
                session,
                text_provider,
                timeout_seconds=settings.ollama_request_timeout_seconds,
            ).generate_scene_plan(
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
            default_service = ImageAssetService(session)
            image_provider = build_image_provider(
                default_service.settings, args.provider, args.model
            )
            asset = ImageAssetService(
                session, default_service.settings, provider=image_provider
            ).generate_for_scene(
                args.scene_id,
                width=args.width,
                height=args.height,
                seed=args.seed,
                checkpoint=args.model,
                workflow_path=args.workflow_path,
                steps=args.steps,
                cfg=args.cfg,
                sampler=args.sampler,
                scheduler=args.scheduler,
                timeout_seconds=args.timeout_seconds,
            )
            print(asset.id)
            return 0
        if args.command == "check-image-provider":
            image_provider = build_image_provider(get_settings(), args.provider, args.model)
            if not isinstance(image_provider, ComfyUIImageGenerationProvider):
                print("READY\tfake_image\tlocal deterministic provider")
                return 0
            image_health = image_provider.check_health()
            status = (
                "READY"
                if all(
                    (
                        image_health.reachable,
                        image_health.workflow_valid,
                        image_health.model_available,
                    )
                )
                else "NOT_READY"
            )
            print(f"{status}\tcomfyui\t{image_health.message}")
            return 0 if status == "READY" else 1
        if args.command == "import-scene-image":
            asset = ImageAssetService(session).import_manual(args.scene_id, Path(args.file))
            print(asset.id)
            return 0
        if args.command in {"generate-scene-voice", "generate-scene-narration"}:
            default_voice_service = VoiceAssetService(session)
            selected_voice = getattr(args, "voice", None) or getattr(args, "voice_name", None)
            voice_provider = build_voice_provider(
                default_voice_service.settings,
                args.provider,
                args.model_path,
                selected_voice,
                args.reference_audio,
            )
            asset = VoiceAssetService(
                session, default_voice_service.settings, provider=voice_provider
            ).generate_for_scene(
                args.scene_id,
                voice_name=selected_voice,
                language=args.language,
                speaking_rate=args.speaking_rate,
                seed=args.seed,
                pronunciation_overrides=_parse_pronunciations(args.pronunciation),
                reference_audio_path=(Path(args.reference_audio) if args.reference_audio else None),
                exaggeration=args.exaggeration,
                cfg_weight=args.cfg_weight,
            )
            print(asset.id)
            return 0
        if args.command == "generate-project-narration":
            default_voice_service = VoiceAssetService(session)
            voice_provider = build_voice_provider(
                default_voice_service.settings,
                args.provider,
                args.model_path,
                args.voice,
                args.reference_audio,
            )
            assets = VoiceAssetService(
                session, default_voice_service.settings, provider=voice_provider
            ).generate_for_project(
                args.project_id,
                voice_name=args.voice,
                language=args.language,
                speaking_rate=args.speaking_rate,
                seed=args.seed,
                pronunciation_overrides=_parse_pronunciations(args.pronunciation),
                reference_audio_path=(Path(args.reference_audio) if args.reference_audio else None),
                exaggeration=args.exaggeration,
                cfg_weight=args.cfg_weight,
            )
            for asset in assets:
                print(asset.id)
            return 0
        if args.command == "check-voice-provider":
            voice_provider = build_voice_provider(
                get_settings(),
                args.provider,
                args.model_path,
                args.voice,
                args.reference_audio,
            )
            if not isinstance(
                voice_provider,
                PiperVoiceGenerationProvider | ChatterboxVoiceGenerationProvider,
            ):
                print("READY\tfake_voice\tlocal deterministic provider")
                return 0
            voice_health = voice_provider.check_health()
            print(
                f"{'READY' if voice_health.available else 'NOT_READY'}\t"
                f"{voice_provider.provider_name}\t{voice_health.message}"
            )
            return 0 if voice_health.available else 1
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
        if args.command == "list-narration-assets":
            assets = AssetReviewService(session).list_project_assets(args.project_id)
            for asset in assets:
                if asset.asset_role == AssetRole.SCENE_NARRATION:
                    print(
                        f"{asset.id}\t{asset.provider or ''}\t"
                        f"{asset.review_status.value}\t{asset.duration_seconds or 0}"
                    )
            return 0
        if args.command == "review-asset":
            asset = AssetReviewService(session).review_asset(
                args.asset_id,
                AssetReviewStatus(args.status),
            )
            print(asset.review_status.value)
            return 0
        if args.command == "record-asset-provenance":
            asset = AssetReviewService(session).record_provenance(
                args.asset_id,
                source_url=args.source_url,
                creator=args.creator,
                license_name=args.license_name,
                license_url=args.license_url,
                license_status=LicenseStatus(args.license_status),
                commercial_use_allowed=args.commercial_use_allowed,
                attribution_required=args.attribution_required,
                model_file_hash=args.model_file_hash,
                config_file_hash=args.config_file_hash,
                model_filename=args.model_filename,
                config_filename=args.config_filename,
                model_card_url=args.model_card_url,
                model_revision=args.model_revision,
                repository_license=args.repository_license,
                dataset_name=args.dataset_name,
                dataset_license=args.dataset_license,
                dataset_license_url=args.dataset_license_url,
                review_date=args.review_date,
                reviewer_decision=args.reviewer_decision,
                reviewer_notes=args.reviewer_notes,
                attribution_text=args.attribution_text,
            )
            print(f"{asset.id}\t{asset.license_status.value}")
            return 0
        if args.command == "verify-asset-file":
            verify_result = AssetReviewService(session).verify_asset_file(args.asset_id)
            print("OK" if verify_result.ok else f"FAIL:{verify_result.reason}")
            return 0
        if args.command == "verify-audio-asset":
            verify_result = AssetReviewService(session).verify_asset_file(args.asset_id)
            print("OK" if verify_result.ok else f"FAIL:{verify_result.reason}")
            return 0
        if args.command == "preview-narration":
            preview_asset = session.get(Asset, args.asset_id)
            if preview_asset is None or preview_asset.asset_role != AssetRole.SCENE_NARRATION:
                print("Narration asset not found.")
                return 1
            print(f"http://127.0.0.1:8000/assets/{preview_asset.id}/preview")
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
            settings = get_settings()
            metadata_provider = build_metadata_provider(settings, args.provider, args.model)
            version = MetadataService(session, settings, metadata_provider).generate_metadata(
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
            settings = get_settings()
            concept_provider = build_thumbnail_concept_provider(settings, args.provider, args.model)
            version = ThumbnailService(
                session, settings, concept_provider=concept_provider
            ).generate_concept(
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
        if args.command == "check-asset-rights":
            records = ContentSafetyService(session).check_asset_rights(args.project_id)
            print(len(records))
            return 0
        if args.command == "check-claims":
            findings = ContentSafetyService(session).check_claim_support(args.project_id)
            print(len(findings))
            return 0
        if args.command == "check-script-safety":
            findings = ContentSafetyService(session).check_script_safety(args.project_id)
            print(len(findings))
            return 0
        if args.command == "check-metadata-safety":
            findings = ContentSafetyService(session).check_metadata_safety(args.project_id)
            print(len(findings))
            return 0
        if args.command == "check-thumbnail-safety":
            findings = ContentSafetyService(session).check_thumbnail_safety(args.project_id)
            print(len(findings))
            return 0
        if args.command == "check-reused-content":
            findings = ContentSafetyService(session).check_reused_content(args.project_id)
            print(len(findings))
            return 0
        if args.command == "decide-ai-disclosure":
            decision = ContentSafetyService(session).decide_ai_disclosure(args.project_id)
            print(
                {
                    "required": decision.required,
                    "reasons": decision.reasons,
                    "suggested_text": decision.suggested_text,
                }
            )
            return 0
        if args.command == "run-publishing-gate":
            gate_result = ContentSafetyService(session).run_publishing_gate(
                args.project_id,
                render_id=args.render_id,
                metadata_version_id=args.metadata_version_id,
                thumbnail_asset_id=args.thumbnail_asset_id,
            )
            print(gate_result.gate.status.value)
            return 0
        if args.command == "show-safety-report":
            report = ContentSafetyService(session).latest_report(args.project_id)
            print(report.content if report is not None else "NONE")
            return 0
        if args.command == "list-safety-findings":
            findings = ContentSafetyService(session).list_findings(args.project_id)
            for finding in findings:
                print(
                    f"{finding.check_type.value}\t{finding.status.value}\t"
                    f"{finding.severity.value}\t{finding.message}"
                )
            return 0
        if args.command == "summarize-safety-report":
            settings = get_settings()
            text_provider = build_text_provider(settings, args.provider, args.model)
            summary = SafetySummaryService(
                session,
                text_provider,
                timeout_seconds=settings.ollama_request_timeout_seconds,
            ).summarize(args.project_id)
            print(summary.text)
            return 0
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


def _parse_pronunciations(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        source, separator, spoken = value.partition("=")
        if not separator or not source.strip() or not spoken.strip():
            raise ValueError("Pronunciation overrides must use TERM=SPOKEN form.")
        result[source.strip()] = spoken.strip()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
