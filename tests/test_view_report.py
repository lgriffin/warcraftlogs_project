"""The page report renderers: Markdown, JSON and the HTML a frontend prints to PDF."""

import json
from datetime import datetime

import pytest

from warcraftlogs_client.renderers.view_report import (
    Figure,
    Heading,
    Paragraph,
    Series,
    Table,
    ViewReport,
    coerce_cell,
    file_stem,
    render_html,
    render_json,
    render_markdown,
)

WHEN = datetime(2026, 10, 14, 19, 30)
CHART = Figure(
    key="01_healing",
    title="Healing Performance",
    series=(Series("Healing", (("2026-10-01T00:00:00", 1000.0), ("2026-10-08T00:00:00", 1500.0))),),
)
REPORT = ViewReport(
    title="Raids",
    generated_at=WHEN,
    blocks=(
        Heading("Karazhan"),
        Paragraph("Ten players\nthree bosses"),
        Table(columns=("Name", "Healing", "OH%"), rows=(("Holy|Priest", "1,234", "16.7%"),), title="Healers"),
        CHART,
        Figure(key="02_heatmap", title="Consumables"),
    ),
)


def test_markdown_has_title_headings_tables_and_linked_chart_images():
    md = render_markdown(REPORT, {"01_healing": "raids_charts/01_healing.png"})

    assert md.startswith("# Raids\n\n*Exported 2026-10-14 19:30*")
    assert "## Karazhan" in md
    assert "**Healers**\n\n| Name | Healing | OH% |\n|---|---|---|\n| Holy\\|Priest | 1,234 | 16.7% |" in md
    assert "![Healing Performance](raids_charts/01_healing.png)" in md
    assert "*Chart: Consumables*" in md  # no image was saved for it


def test_markdown_heading_levels_stay_below_the_title():
    report = ViewReport("T", WHEN, (Heading("Top", 1), Heading("Deep", 9)))

    md = render_markdown(report, {})

    assert "\n## Top\n" in md
    assert "\n###### Deep\n" in md


def test_json_keeps_rows_as_records_with_numbers_and_the_chart_data():
    doc = json.loads(render_json(REPORT, {"01_healing": "raids_charts/01_healing.png"}))

    assert doc["title"] == "Raids"
    assert doc["exported_at"] == "2026-10-14T19:30:00"
    heading, text, table, chart, bare = doc["blocks"]
    assert heading == {"type": "heading", "level": 2, "text": "Karazhan"}
    assert text == {"type": "text", "text": "Ten players\nthree bosses"}
    assert table["columns"] == ["Name", "Healing", "OH%"]
    assert table["rows"] == [{"Name": "Holy|Priest", "Healing": 1234, "OH%": "16.7%"}]
    assert chart["image"] == "raids_charts/01_healing.png"
    assert chart["series"] == [
        {
            "name": "Healing",
            "points": [{"x": "2026-10-01T00:00:00", "y": 1000.0}, {"x": "2026-10-08T00:00:00", "y": 1500.0}],
        }
    ]
    assert bare["image"] is None
    assert bare["series"] == []


def test_html_escapes_text_and_sizes_images_to_fit_the_page():
    report = ViewReport(
        "<Toads>",
        WHEN,
        (
            Heading("Bosses & trash", 3),
            Paragraph("a < b\nc"),
            Table(("A&B",), (("<i>",),)),
            CHART,
            Figure("small", "Spider"),
        ),
    )

    page = render_html(report, {"01_healing": "chart://01.png", "small": "chart://small.png"}, {"small": 280})

    assert "<h1>&lt;Toads&gt;</h1>" in page
    assert "<h3>Bosses &amp; trash</h3>" in page
    assert "<p>a &lt; b<br>c</p>" in page
    assert "<th>A&amp;B</th>" in page
    assert "<td>&lt;i&gt;</td>" in page
    assert '<img src="chart://01.png" width="560">' in page  # no screen width: the page width
    assert '<img src="chart://small.png" width="280">' in page
    assert "Exported 2026-10-14 19:30" in page


def test_html_names_a_chart_with_no_image():
    page = render_html(ViewReport("T", WHEN, (Figure("k", "Heatmap"),)), {})

    assert "<i>Chart: Heatmap</i>" in page


def test_figures_lists_only_the_charts():
    assert REPORT.figures == (CHART, REPORT.blocks[-1])


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1,234", 1234),
        ("-12", -12),
        ("987.5", 987.5),
        ("1,234,567.25", 1234567.25),
        (" 42 ", 42),
        ("16.7%", "16.7%"),
        ("12,34", "12,34"),
        ("Greater Heal (50)", "Greater Heal (50)"),
        ("", ""),
    ],
)
def test_coerce_cell_reads_numbers_and_keeps_everything_else(text, value):
    assert coerce_cell(text) == value


@pytest.mark.parametrize(
    ("title", "stem"),
    [("Raids", "raids"), ("Karazhan — Full Clear (10)", "karazhan_full_clear_10"), ("***", "report")],
)
def test_file_stem(title, stem):
    assert file_stem(title) == stem


def test_file_stem_is_capped():
    assert len(file_stem("a" * 200)) == 80
