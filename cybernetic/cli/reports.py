"""Browse previous analysis reports and export to PDF."""
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import questionary
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule

from cybernetic.cli.utils import ask, QMARK

console = Console()

# ---------------------------------------------------------------------------
# Section manifest: maps on-disk files to display names and UI grouping
# ---------------------------------------------------------------------------

SECTION_MANIFEST = [
    # (subdir, filename, display_name, group_key, group_title, border_style)
    ("1_analysts", "market.md", "Market Analyst", "analysts", "I. Analyst Team Reports", "cyan"),
    ("1_analysts", "sentiment.md", "Social Analyst", "analysts", "I. Analyst Team Reports", "cyan"),
    ("1_analysts", "news.md", "News Analyst", "analysts", "I. Analyst Team Reports", "cyan"),
    ("1_analysts", "fundamentals.md", "Fundamentals Analyst", "analysts", "I. Analyst Team Reports", "cyan"),
    ("2_research", "bull.md", "Bull Researcher", "research", "II. Research Team Decision", "magenta"),
    ("2_research", "bear.md", "Bear Researcher", "research", "II. Research Team Decision", "magenta"),
    ("2_research", "manager.md", "Research Manager", "research", "II. Research Team Decision", "magenta"),
    ("3_trading", "trader.md", "Trader", "trading", "III. Trading Team Plan", "yellow"),
    ("4_risk", "aggressive.md", "Aggressive Analyst", "risk", "IV. Risk Management Team Decision", "red"),
    ("4_risk", "conservative.md", "Conservative Analyst", "risk", "IV. Risk Management Team Decision", "red"),
    ("4_risk", "neutral.md", "Neutral Analyst", "risk", "IV. Risk Management Team Decision", "red"),
    ("5_portfolio", "decision.md", "Portfolio Manager", "portfolio", "V. Portfolio Manager Decision", "green"),
]


@dataclass
class ReportInfo:
    path: Path
    ticker: str
    timestamp: datetime
    display_name: str


@dataclass
class SectionInfo:
    path: Path
    display_name: str
    group: str
    group_title: str
    border_style: str


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

_DIR_RE = re.compile(r"^(.+)_(\d{8})_(\d{6})$")


def parse_report_dir(dir_path: Path) -> Optional[ReportInfo]:
    """Parse a report folder name into ReportInfo, or None if invalid."""
    m = _DIR_RE.match(dir_path.name)
    if not m:
        return None
    ticker = m.group(1).strip()
    try:
        ts = datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    display = f"{ticker} - {ts.strftime('%b %d, %Y %I:%M %p')}"
    return ReportInfo(path=dir_path, ticker=ticker, timestamp=ts, display_name=display)


def discover_reports(reports_dir: Path) -> List[ReportInfo]:
    """Return all valid reports sorted newest-first."""
    if not reports_dir.is_dir():
        return []
    results: List[ReportInfo] = []
    for entry in reports_dir.iterdir():
        if not entry.is_dir():
            continue
        if not (entry / "complete_report.md").exists():
            continue
        info = parse_report_dir(entry)
        if info:
            results.append(info)
    results.sort(key=lambda r: r.timestamp, reverse=True)
    return results


def discover_sections(report_path: Path) -> List[SectionInfo]:
    """Return SectionInfo for each section file that exists on disk."""
    found: List[SectionInfo] = []
    for subdir, filename, display, group, group_title, style in SECTION_MANIFEST:
        fpath = report_path / subdir / filename
        if fpath.exists():
            found.append(SectionInfo(
                path=fpath,
                display_name=display,
                group=group,
                group_title=group_title,
                border_style=style,
            ))
    return found


# ---------------------------------------------------------------------------
# Terminal display
# ---------------------------------------------------------------------------

def display_report_terminal(report_path: Path) -> None:
    """Render a report in the terminal using Rich panels (matching research_flow style)."""
    sections = discover_sections(report_path)
    if not sections:
        console.print("[yellow]No section files found in this report.[/yellow]")
        return

    console.print()
    console.print(Rule("Complete Analysis Report", style="bold green"))

    last_group = None
    for sec in sections:
        if sec.group != last_group:
            console.print(Panel(f"[bold]{sec.group_title}[/bold]", border_style=sec.border_style))
            last_group = sec.group
        content = sec.path.read_text(encoding="utf-8", errors="replace")
        console.print(Panel(Markdown(content), title=sec.display_name, border_style="blue", padding=(1, 2)))


# ---------------------------------------------------------------------------
# PDF generation  (reportlab)
# ---------------------------------------------------------------------------

_GREEN_HEX = "#22c55e"


def _escape_xml(text: str) -> str:
    """Escape <, >, & for ReportLab Paragraph XML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _normalize_unicode(text: str) -> str:
    """Replace problematic Unicode characters with ASCII equivalents for PDF rendering."""
    return (
        text
        .replace("\u2011", "-")   # non-breaking hyphen
        .replace("\u2010", "-")   # hyphen
        .replace("\u2013", "-")   # en dash
        .replace("\u2014", " - ") # em dash
        .replace("\u2018", "'")   # left single quote
        .replace("\u2019", "'")   # right single quote
        .replace("\u201c", '"')   # left double quote
        .replace("\u201d", '"')   # right double quote
        .replace("\u2026", "...") # ellipsis
        .replace("\u00d7", "x")   # multiplication sign
    )


def _inline_format(text: str) -> str:
    """Convert markdown inline formatting to ReportLab Paragraph markup."""
    # Inline code first: protect content inside backticks from bold/italic processing
    code_spans = []
    def _save_code(m):
        code_spans.append(m.group(1))
        return f"\x00CODE{len(code_spans) - 1}\x00"
    text = re.sub(r"`(.+?)`", _save_code, text)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # Italic with *text* (not inside bold markers)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    # Italic with _text_ — only at word boundaries (avoid matching inside words like close_10_ema)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)

    # Restore code spans
    for i, code in enumerate(code_spans):
        text = text.replace(f"\x00CODE{i}\x00", f'<font face="Courier">{code}</font>')

    return text


def _md_to_flowables(md_text: str, styles: dict) -> list:
    """Convert markdown text to a list of ReportLab flowables."""
    from reportlab.platypus import Paragraph, Spacer, HRFlowable
    from reportlab.lib.colors import HexColor

    green = HexColor(_GREEN_HEX)
    md_text = _normalize_unicode(md_text)
    flowables = []

    for line in md_text.split("\n"):
        stripped = line.strip()

        # Blank line -> small spacer
        if not stripped:
            flowables.append(Spacer(1, 6))
            continue

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            flowables.append(HRFlowable(width="100%", color=green, thickness=1, spaceBefore=4, spaceAfter=4))
            continue

        # Headings
        if stripped.startswith("### "):
            text = _escape_xml(stripped[4:])
            flowables.append(Paragraph(_inline_format(text), styles["h3"]))
            continue
        if stripped.startswith("## "):
            text = _escape_xml(stripped[3:])
            flowables.append(Paragraph(_inline_format(text), styles["h2"]))
            continue
        if stripped.startswith("# "):
            text = _escape_xml(stripped[2:])
            flowables.append(Paragraph(_inline_format(text), styles["h1"]))
            continue

        # Bullets
        if stripped.startswith("- ") or stripped.startswith("* "):
            text = _escape_xml(stripped[2:])
            flowables.append(Paragraph(f"&bull; {_inline_format(text)}", styles["bullet"]))
            continue

        # Numbered lists  (e.g. "1. item")
        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m:
            text = _escape_xml(m.group(2))
            flowables.append(Paragraph(f"{m.group(1)}. {_inline_format(text)}", styles["bullet"]))
            continue

        # Regular paragraph
        text = _escape_xml(stripped)
        flowables.append(Paragraph(_inline_format(text), styles["body"]))

    return flowables


def build_pdf(output_path: Path, title: str, sections: List[SectionInfo]) -> None:
    """Build a PDF from the given sections and save to output_path."""
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, PageBreak
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER

    green = HexColor(_GREEN_HEX)
    dark = HexColor("#1a1a2e")

    styles = {
        "title": ParagraphStyle(
            "OTitle", fontSize=24, leading=30, textColor=green,
            alignment=TA_CENTER, spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "OSubtitle", fontSize=12, leading=16, textColor=HexColor("#888888"),
            alignment=TA_CENTER, spaceAfter=20,
        ),
        "h1": ParagraphStyle(
            "OH1", fontSize=18, leading=22, textColor=green,
            spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold",
        ),
        "h2": ParagraphStyle(
            "OH2", fontSize=14, leading=18, textColor=green,
            spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold",
        ),
        "h3": ParagraphStyle(
            "OH3", fontSize=12, leading=16,
            spaceBefore=8, spaceAfter=4, fontName="Helvetica-Bold",
        ),
        "body": ParagraphStyle(
            "OBody", fontSize=10, leading=14, spaceAfter=4,
        ),
        "bullet": ParagraphStyle(
            "OBullet", fontSize=10, leading=14, leftIndent=18,
            spaceAfter=3,
        ),
        "section_header": ParagraphStyle(
            "OSectionHeader", fontSize=16, leading=20, textColor=green,
            spaceBefore=16, spaceAfter=4, fontName="Helvetica-Bold",
        ),
    }

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    story: list = []

    # Title page
    story.append(Spacer(1, 2 * inch))
    story.append(Paragraph("CYBERNETIC.BIZ", styles["title"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(title, styles["h2"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f"Generated {datetime.now().strftime('%b %d, %Y %I:%M %p')}",
        styles["subtitle"],
    ))
    story.append(PageBreak())

    # Sections
    last_group = None
    for sec in sections:
        if sec.group != last_group:
            story.append(Paragraph(sec.group_title, styles["section_header"]))
            story.append(HRFlowable(width="100%", color=green, thickness=1, spaceAfter=8))
            last_group = sec.group

        story.append(Paragraph(sec.display_name, styles["h2"]))
        story.append(Spacer(1, 4))

        content = sec.path.read_text(encoding="utf-8", errors="replace")
        story.extend(_md_to_flowables(content, styles))
        story.append(Spacer(1, 12))

    doc.build(story)


# ---------------------------------------------------------------------------
# Interactive flows
# ---------------------------------------------------------------------------

def _menu_style():
    from cybernetic.cli.theme import t
    return questionary.Style([
        ("selected", t("menu_selected")),
        ("highlighted", t("menu_highlighted")),
        ("pointer", t("menu_pointer")),
        ("checkbox-selected", t("menu_checkbox")),
    ])


def select_sections_for_export(report_path: Path) -> Optional[List[SectionInfo]]:
    """Let user pick sections via checkbox. Returns None on cancel."""
    all_sections = discover_sections(report_path)
    if not all_sections:
        console.print("[yellow]No sections found.[/yellow]")
        return None

    choices = [
        questionary.Choice(sec.display_name, value=sec.display_name, checked=True)
        for sec in all_sections
    ]

    selected_names = ask(questionary.checkbox(
        "Select sections to export:",
        qmark=QMARK,
        choices=choices,
        instruction="\n- Press Space to select/unselect\n- Press 'a' to toggle all\n- Press Enter when done",
        validate=lambda x: len(x) > 0 or "Select at least one section.",
        style=_menu_style(),
    ))

    if not selected_names:
        return None

    name_set = set(selected_names)
    return [sec for sec in all_sections if sec.display_name in name_set]


def export_pdf_flow(report_info: ReportInfo) -> None:
    """PDF export sub-menu: complete or select sections."""
    choice = ask(questionary.select(
        "Export options:",
        qmark=QMARK,
        choices=[
            questionary.Choice("Complete Report", value="complete"),
            questionary.Choice("Select Sections", value="select"),
            questionary.Choice("Back", value="back"),
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=_menu_style(),
    ))

    if choice is None or choice == "back":
        return

    if choice == "complete":
        sections = discover_sections(report_info.path)
        if not sections:
            console.print("[yellow]No sections found.[/yellow]")
            return
        pdf_name = f"{report_info.ticker}_complete_report.pdf"
    else:
        sections = select_sections_for_export(report_info.path)
        if not sections:
            return
        pdf_name = f"{report_info.ticker}_selected_sections.pdf"

    pdf_path = report_info.path / pdf_name
    title = f"{report_info.ticker} Analysis Report"

    try:
        build_pdf(pdf_path, title, sections)
        console.print(f"[green]PDF saved to:[/green] {pdf_path}")
    except Exception as e:
        console.print(f"[red]Error creating PDF: {e}[/red]")
        return

    open_it = ask(questionary.confirm(
        "Open PDF now?",
        qmark=QMARK,
        default=True,
        style=_menu_style(),
    ))
    if open_it:
        try:
            subprocess.run(["xdg-open", str(pdf_path)], check=False)
        except Exception:
            console.print("[yellow]Could not open PDF viewer.[/yellow]")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _flush_stdin() -> None:
    """Discard any buffered keystrokes so they don't leak into the next prompt."""
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except (ImportError, termios.error):
        pass


def browse_reports() -> None:
    """Main entry point: browse, view, and export previous reports."""
    _flush_stdin()

    reports_dir = Path("./reports")
    reports = discover_reports(reports_dir)

    if not reports:
        console.print("[yellow]No reports found in ./reports/[/yellow]")
        return

    # Build aligned choice labels: pad tickers so dates line up
    max_ticker = max(len(r.ticker) for r in reports)
    report_labels = {}
    for r in reports:
        n_sections = len(discover_sections(r.path))
        label = (
            f"{r.ticker.upper():<{max_ticker}}  "
            f"\u2502 {r.timestamp.strftime('%b %d, %Y')}  "
            f"{r.timestamp.strftime('%I:%M %p')}  "
            f"\u2502 {n_sections} sections"
        )
        report_labels[label] = r

    while True:
        # Select a report
        choices = [
            questionary.Choice(label, value=label)
            for label in report_labels
        ] + [questionary.Choice("Back", value="back")]

        selected_name = ask(questionary.select(
            "Select a report:",
            qmark=QMARK,
            choices=choices,
            instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
            style=_menu_style(),
        ))

        if selected_name is None or selected_name == "back":
            return

        selected = report_labels[selected_name]

        # Action sub-menu for the selected report
        while True:
            action = ask(questionary.select(
                f"{selected.display_name}:",
                qmark=QMARK,
                choices=[
                    questionary.Choice("View in Terminal", value="view"),
                    questionary.Choice("Export as PDF", value="pdf"),
                    questionary.Choice("Back", value="back"),
                ],
                instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
                style=_menu_style(),
            ))

            if action is None or action == "back":
                break

            if action == "view":
                display_report_terminal(selected.path)
            elif action == "pdf":
                export_pdf_flow(selected)
