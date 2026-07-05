"""Run the local operations dashboard."""

import uvicorn

from ai_media_os.api.app import create_app
from ai_media_os.infrastructure.settings import get_settings

app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "ai_media_os.web:app",
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
