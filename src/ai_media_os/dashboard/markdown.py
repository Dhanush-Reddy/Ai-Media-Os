"""Small safe Markdown renderer for dashboard previews."""

import html
import re

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")


def render_safe_markdown(markdown_text: str) -> str:
    """Render a deliberately small Markdown subset with all raw HTML escaped."""

    lines: list[str] = []
    in_list = False
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            if in_list:
                lines.append("</ul>")
                in_list = False
            continue
        heading = HEADING_RE.match(line)
        if heading:
            if in_list:
                lines.append("</ul>")
                in_list = False
            level = len(heading.group(1))
            lines.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        if line.startswith("- "):
            if not in_list:
                lines.append("<ul>")
                in_list = True
            lines.append(f"<li>{_inline(line[2:])}</li>")
            continue
        if in_list:
            lines.append("</ul>")
            in_list = False
        lines.append(f"<p>{_inline(line)}</p>")
    if in_list:
        lines.append("</ul>")
    return "\n".join(lines)


def _inline(value: str) -> str:
    escaped = html.escape(value)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped
