# Thumbnail And Metadata Foundation

Milestone 8 packages a rendered local video into reviewable YouTube metadata and a thumbnail candidate.

## Responsibilities

- `VideoMetadataDocument` validates title ideas, description, tags, hashtags, chapters, source version IDs, and local-path leakage.
- `ThumbnailConceptDocument` validates the thumbnail concept, selected on-image text, and prompt-safe design notes.
- `MetadataService` reads the approved script, approved scene plan, optional rendered output, and scene narration to create immutable metadata content versions.
- `ThumbnailService` reads a metadata version, creates an immutable thumbnail concept version, creates or imports thumbnail assets, verifies file hashes, and records review status.
- `FakeMetadataGenerationProvider` and `FakeThumbnailImageProvider` provide deterministic local outputs for tests and demos without paid APIs.
- Dashboard metadata and thumbnail pages expose reviewable output without exposing local filesystem paths.

## Local Output

Fake thumbnail generation writes a real PNG file to:

```text
data/projects/{project_id}/thumbnails/thumbnail_vNNN.png
```

The file is stored as an `AssetType.THUMBNAIL` with `AssetRole.THUMBNAIL`, content hash, dimensions, provider metadata, and review status.

Metadata is stored as `ContentType.METADATA` JSON. Thumbnail concepts are stored as `ContentType.THUMBNAIL_CONCEPT` JSON.

## Queue Flow

Packaging jobs are intentionally small:

- `GENERATE_VIDEO_METADATA`
- `REVISE_VIDEO_METADATA`
- `IMPORT_VIDEO_METADATA`
- `GENERATE_THUMBNAIL_CONCEPT`
- `GENERATE_FAKE_THUMBNAIL`
- `IMPORT_THUMBNAIL`
- `REVIEW_METADATA`
- `REVIEW_THUMBNAIL`
- `VERIFY_THUMBNAIL_FILE`

Generation jobs complete normally and create pending approval/review records separately. They do not park their own running job in `WAITING_FOR_APPROVAL`.

## Non-Goals

Milestone 8 does not add YouTube upload, publishing automation, real image generation, real LLM metadata generation, content safety, analytics, Telegram approval, Shorts automation, or final channel branding systems.
