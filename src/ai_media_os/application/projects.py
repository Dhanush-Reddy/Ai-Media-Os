"""Channel and video-project catalog operations."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_media_os.application.transactions import write_transaction
from ai_media_os.infrastructure.database.models import Channel, VideoProject

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ProjectCatalogError(RuntimeError):
    """Raised when a channel or project cannot be created."""


class ProjectCatalogService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_channel(
        self,
        *,
        name: str,
        slug: str,
        niche: str,
        language: str = "en",
    ) -> Channel:
        normalized_slug = slug.strip().lower()
        if not name.strip() or not niche.strip():
            raise ProjectCatalogError("Channel name and niche are required.")
        if not SLUG_PATTERN.fullmatch(normalized_slug):
            raise ProjectCatalogError(
                "Channel slug must use lowercase letters, numbers, and hyphens."
            )
        with write_transaction(self.session):
            existing = self.session.scalar(select(Channel).where(Channel.slug == normalized_slug))
            if existing is not None:
                raise ProjectCatalogError(f"Channel slug already exists: {normalized_slug}")
            channel = Channel(
                name=name.strip(),
                slug=normalized_slug,
                niche=niche.strip(),
                language=language.strip() or "en",
            )
            self.session.add(channel)
            self.session.flush()
            return channel

    def list_channels(self) -> list[Channel]:
        return list(self.session.scalars(select(Channel).order_by(Channel.created_at, Channel.id)))

    def create_project(
        self,
        *,
        channel_id: str,
        working_title: str,
        topic: str,
        description: str | None = None,
        target_duration_seconds: int | None = None,
    ) -> VideoProject:
        if self.session.get(Channel, channel_id) is None:
            raise ProjectCatalogError(f"Channel not found: {channel_id}")
        if not working_title.strip() or not topic.strip():
            raise ProjectCatalogError("Project working title and topic are required.")
        if target_duration_seconds is not None and target_duration_seconds <= 0:
            raise ProjectCatalogError("Target duration must be greater than zero.")
        with write_transaction(self.session):
            project = VideoProject(
                channel_id=channel_id,
                working_title=working_title.strip(),
                topic=topic.strip(),
                description=description.strip() if description else None,
                target_duration_seconds=target_duration_seconds,
            )
            self.session.add(project)
            self.session.flush()
            return project

    def list_projects(self, channel_id: str | None = None) -> list[VideoProject]:
        statement = select(VideoProject)
        if channel_id is not None:
            statement = statement.where(VideoProject.channel_id == channel_id)
        return list(
            self.session.scalars(statement.order_by(VideoProject.created_at, VideoProject.id))
        )
