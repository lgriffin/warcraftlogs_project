"""
Report of what one screen shows, for export.

A frontend reads its current view into a :class:`ViewReport` (headings, text, tables and charts in reading order) and
these functions turn it into Markdown, JSON for further analysis, or HTML that a frontend prints to PDF. Chart images
are written by the frontend; a report only names them, and each renderer takes where each image went.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

_NUMBER = re.compile(r"[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?")


@dataclass(frozen=True)
class Heading:
    text: str
    level: int = 2


@dataclass(frozen=True)
class Paragraph:
    text: str


@dataclass(frozen=True)
class Table:
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    title: str = ""


@dataclass(frozen=True)
class Series:
    """One line, bar set or slice set of a chart: its points as (x, y), x a label, a date or a number."""

    name: str
    points: tuple[tuple[str | float, float], ...]


@dataclass(frozen=True)
class Figure:
    """A chart. ``key`` names its image file; ``series`` is its data, when the chart exposes it."""

    key: str
    title: str
    series: tuple[Series, ...] = ()


Block = Heading | Paragraph | Table | Figure


@dataclass(frozen=True)
class ViewReport:
    title: str
    generated_at: datetime
    blocks: tuple[Block, ...] = field(default_factory=tuple)

    @property
    def figures(self) -> tuple[Figure, ...]:
        return tuple(b for b in self.blocks if isinstance(b, Figure))


def file_stem(title: str) -> str:
    """A file name for a report or chart title: lower case words joined by underscores."""
    stem = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return stem[:80] or "report"


def coerce_cell(text: str) -> str | int | float:
    """A table cell as a number when it is one ("1,234" or "12.5"), else the text as shown."""
    value = text.strip()
    if not _NUMBER.fullmatch(value):
        return text
    value = value.replace(",", "")
    return float(value) if "." in value else int(value)


# ── Markdown ──


def _md_cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _md_table(table: Table) -> str:
    lines = [f"**{table.title}**", ""] if table.title else []
    lines.append("| " + " | ".join(_md_cell(c) for c in table.columns) + " |")
    lines.append("|" + "---|" * len(table.columns))
    lines.extend("| " + " | ".join(_md_cell(c) for c in row) + " |" for row in table.rows)
    return "\n".join(lines)


def _md_block(block: Block, images: Mapping[str, str]) -> str:
    if isinstance(block, Heading):
        return f"{'#' * min(max(block.level, 2), 6)} {block.text}"
    if isinstance(block, Paragraph):
        return block.text
    if isinstance(block, Table):
        return _md_table(block)
    image = images.get(block.key)
    if not image:
        return f"*Chart: {block.title}*"
    # Angle brackets let the path hold spaces and parentheses, as a file name the user picked can.
    alt = block.title.replace("[", "\\[").replace("]", "\\]")
    return f"![{alt}](<{image}>)"


def render_markdown(report: ViewReport, images: Mapping[str, str]) -> str:
    """The report as Markdown; ``images`` maps a figure's key to its image path, relative to the Markdown file."""
    parts = [f"# {report.title}", f"*Exported {report.generated_at:%Y-%m-%d %H:%M}*"]
    parts.extend(_md_block(b, images) for b in report.blocks)
    return "\n\n".join(parts) + "\n"


# ── JSON ──


def _json_block(block: Block, images: Mapping[str, str]) -> dict[str, object]:
    if isinstance(block, Heading):
        return {"type": "heading", "level": block.level, "text": block.text}
    if isinstance(block, Paragraph):
        return {"type": "text", "text": block.text}
    if isinstance(block, Table):
        return {
            "type": "table",
            "title": block.title,
            "columns": list(block.columns),
            "rows": [{c: coerce_cell(v) for c, v in zip(block.columns, row, strict=False)} for row in block.rows],
        }
    return {
        "type": "chart",
        "title": block.title,
        "image": images.get(block.key),
        "series": [{"name": s.name, "points": [{"x": x, "y": y} for x, y in s.points]} for s in block.series],
    }


def render_json(report: ViewReport, images: Mapping[str, str]) -> str:
    """The report as JSON: tables as records keyed by column, numbers as numbers, and each chart's data."""
    doc = {
        "title": report.title,
        "exported_at": report.generated_at.isoformat(timespec="seconds"),
        "blocks": [_json_block(b, images) for b in report.blocks],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


# ── HTML (printed to PDF) ──

_HTML_STYLE = (
    "body { font-family: sans-serif; font-size: 10pt; color: #1a1a1a; }"
    "h1 { font-size: 18pt; } h2 { font-size: 14pt; } h3 { font-size: 12pt; }"
    "table { border-collapse: collapse; margin: 6px 0; }"
    "th, td { border: 1px solid #999; padding: 3px 6px; }"
    "th { background-color: #e6e6e6; }"
    ".meta { color: #666; }"
)


def _html_table(table: Table) -> str:
    title = f"<p><b>{html.escape(table.title)}</b></p>" if table.title else ""
    head = "".join(f"<th>{html.escape(c)}</th>" for c in table.columns)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in table.rows)
    return f'{title}<table cellspacing="0" cellpadding="3"><tr>{head}</tr>{body}</table>'


def _html_block(block: Block, images: Mapping[str, str], widths: Mapping[str, int], image_width: int) -> str:
    if isinstance(block, Heading):
        level = min(max(block.level, 2), 6)
        return f"<h{level}>{html.escape(block.text)}</h{level}>"
    if isinstance(block, Paragraph):
        return "<p>" + html.escape(block.text).replace("\n", "<br>") + "</p>"
    if isinstance(block, Table):
        return _html_table(block)
    image = images.get(block.key)
    if not image:
        return f"<p><i>Chart: {html.escape(block.title)}</i></p>"
    width = min(widths.get(block.key, image_width), image_width)
    return f'<p><img src="{html.escape(image, quote=True)}" width="{width}"></p>'


def render_html(
    report: ViewReport,
    images: Mapping[str, str],
    widths: Mapping[str, int] | None = None,
    image_width: int = 560,
) -> str:
    """The report as one HTML page.

    ``images`` maps a figure's key to an image URL; each is drawn at its ``widths`` entry (its width on screen), at
    most ``image_width``, so a wide chart fits the page and a small one is not blown up.
    """
    body = "".join(_html_block(b, images, widths or {}, image_width) for b in report.blocks)
    return (
        f"<html><head><style>{_HTML_STYLE}</style></head><body>"
        f"<h1>{html.escape(report.title)}</h1>"
        f'<p class="meta">Exported {report.generated_at:%Y-%m-%d %H:%M}</p>'
        f"{body}</body></html>"
    )
