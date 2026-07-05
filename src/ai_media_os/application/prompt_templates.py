"""Application service for immutable prompt-template versions."""

from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_media_os.domain.enums import PromptTemplateStatus
from ai_media_os.infrastructure.database.models import PromptTemplate
from ai_media_os.utils.hashing import hash_prompt_template


class PromptTemplateError(RuntimeError):
    """Raised when prompt-template rules are violated."""


class PromptTemplateService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_prompt_version(
        self,
        *,
        name: str,
        category: str,
        template_text: str,
        description: str | None = None,
        variables_schema: dict[str, object] | None = None,
        parent_template_id: str | None = None,
    ) -> PromptTemplate:
        parent = (
            self.session.get(PromptTemplate, parent_template_id) if parent_template_id else None
        )
        if parent is not None and parent.name != name:
            raise PromptTemplateError("Prompt parent must have the same name.")
        self.session.execute(text("BEGIN IMMEDIATE"))
        try:
            max_version = self.session.scalar(
                select(func.max(PromptTemplate.version)).where(PromptTemplate.name == name)
            )
            next_version = self._next_version(max_version)
            prompt = PromptTemplate(
                name=name,
                category=category,
                version=next_version,
                template_text=template_text,
                status=PromptTemplateStatus.DRAFT,
                content_hash=hash_prompt_template(name, next_version, template_text),
                description=description,
                variables_schema=variables_schema,
                parent_template_id=parent_template_id,
            )
            self.session.add(prompt)
            self.session.commit()
            self.session.refresh(prompt)
            return prompt
        except IntegrityError as exc:
            self.session.rollback()
            raise PromptTemplateError("Could not create a unique prompt version.") from exc

    def activate_prompt(self, prompt_template_id: str) -> PromptTemplate:
        self.session.execute(text("BEGIN IMMEDIATE"))
        try:
            prompt = self._get_prompt(prompt_template_id)
            previous = self.session.scalars(
                select(PromptTemplate).where(
                    PromptTemplate.name == prompt.name,
                    PromptTemplate.status == PromptTemplateStatus.ACTIVE,
                    PromptTemplate.id != prompt.id,
                )
            ).all()
            for item in previous:
                item.status = PromptTemplateStatus.DEPRECATED
            prompt.status = PromptTemplateStatus.ACTIVE
            self.session.commit()
            self.session.refresh(prompt)
            return prompt
        except Exception:
            self.session.rollback()
            raise

    def deprecate_prompt(self, prompt_template_id: str) -> PromptTemplate:
        prompt = self._get_prompt(prompt_template_id)
        prompt.status = PromptTemplateStatus.DEPRECATED
        self.session.commit()
        self.session.refresh(prompt)
        return prompt

    def active_prompt(self, name: str) -> PromptTemplate | None:
        return self.session.scalar(
            select(PromptTemplate).where(
                PromptTemplate.name == name,
                PromptTemplate.status == PromptTemplateStatus.ACTIVE,
            )
        )

    def prompt_history(self, name: str) -> list[PromptTemplate]:
        return list(
            self.session.scalars(
                select(PromptTemplate)
                .where(PromptTemplate.name == name)
                .order_by(PromptTemplate.created_at.asc())
            ).all()
        )

    def verify_immutable(self, original: PromptTemplate, candidate: PromptTemplate) -> None:
        for field in (
            "name",
            "category",
            "version",
            "template_text",
            "content_hash",
            "created_at",
            "parent_template_id",
        ):
            if inspect(candidate).attrs[field].history.has_changes():
                raise PromptTemplateError(f"Immutable prompt-template field changed: {field}")
            if getattr(original, field) != getattr(candidate, field):
                raise PromptTemplateError(f"Immutable prompt-template field changed: {field}")

    def _get_prompt(self, prompt_template_id: str) -> PromptTemplate:
        prompt = self.session.get(PromptTemplate, prompt_template_id)
        if prompt is None:
            raise PromptTemplateError(f"Prompt template not found: {prompt_template_id}")
        return prompt

    @staticmethod
    def _next_version(max_version: str | None) -> str:
        if max_version is None:
            return "v001"
        try:
            number = int(max_version.removeprefix("v"))
        except ValueError as exc:
            raise PromptTemplateError(f"Unsupported prompt version format: {max_version}") from exc
        return f"v{number + 1:03d}"
