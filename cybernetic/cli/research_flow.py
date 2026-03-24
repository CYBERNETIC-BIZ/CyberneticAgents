"""Research flow UI with Rich panels and live agent tracking."""
from typing import Optional
import datetime
import sys
import select as _select
import questionary
import typer
from pathlib import Path
from functools import wraps
from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live
from rich.columns import Columns
from rich.markdown import Markdown
from rich.layout import Layout
from rich.text import Text
from rich.table import Table
from collections import deque
import time
from rich.tree import Tree
from rich import box
from rich.align import Align
from rich.rule import Rule

from cybernetic.config import DEFAULT_CONFIG
from cybernetic.cli.models import AnalystType
from cybernetic.cli.utils import (
    ask,
    QMARK,
    get_ticker,
    get_analysis_date,
    select_analysts,
    select_research_depth,
    select_llm_provider,
    select_shallow_thinking_agent,
    select_deep_thinking_agent,
    ask_gemini_thinking_config,
    ask_openai_reasoning_effort,
    display_agent_config,
    TEMP_LABELS,
)

console = Console()


class MessageBuffer:
    # Fixed teams that always run (not user-selectable)
    FIXED_AGENTS = {
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    # Analyst name mapping
    ANALYST_MAPPING = {
        "market": "Market Analyst",
        "social": "Social Analyst",
        "news": "News Analyst",
        "fundamentals": "Fundamentals Analyst",
    }

    # Report section mapping: section -> (analyst_key for filtering, finalizing_agent)
    REPORT_SECTIONS = {
        "market_report": ("market", "Market Analyst"),
        "sentiment_report": ("social", "Social Analyst"),
        "news_report": ("news", "News Analyst"),
        "fundamentals_report": ("fundamentals", "Fundamentals Analyst"),
        "investment_plan": (None, "Research Manager"),
        "trader_investment_plan": (None, "Trader"),
        "final_trade_decision": (None, "Portfolio Manager"),
    }

    def __init__(self, max_length=100):
        self.messages = deque(maxlen=max_length)
        self.tool_calls = deque(maxlen=max_length)
        self.current_report = None
        self.final_report = None
        self.agent_status = {}
        self.current_agent = None
        self.report_sections = {}
        self.selected_analysts = []
        self._last_message_id = None

    def init_for_analysis(self, selected_analysts):
        """Initialize agent status and report sections based on selected analysts."""
        self.selected_analysts = [a.lower() for a in selected_analysts]

        self.agent_status = {}

        for analyst_key in self.selected_analysts:
            if analyst_key in self.ANALYST_MAPPING:
                self.agent_status[self.ANALYST_MAPPING[analyst_key]] = "pending"

        for team_agents in self.FIXED_AGENTS.values():
            for agent in team_agents:
                self.agent_status[agent] = "pending"

        self.report_sections = {}
        for section, (analyst_key, _) in self.REPORT_SECTIONS.items():
            if analyst_key is None or analyst_key in self.selected_analysts:
                self.report_sections[section] = None

        self.current_report = None
        self.final_report = None
        self.current_agent = None
        self.messages.clear()
        self.tool_calls.clear()
        self._last_message_id = None

    def get_completed_reports_count(self):
        """Count reports that are finalized."""
        count = 0
        for section in self.report_sections:
            if section not in self.REPORT_SECTIONS:
                continue
            _, finalizing_agent = self.REPORT_SECTIONS[section]
            has_content = self.report_sections.get(section) is not None
            agent_done = self.agent_status.get(finalizing_agent) == "completed"
            if has_content and agent_done:
                count += 1
        return count

    def add_message(self, message_type, content):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.messages.append((timestamp, message_type, content))

    def add_tool_call(self, tool_name, args):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.tool_calls.append((timestamp, tool_name, args))

    def update_agent_status(self, agent, status):
        if agent in self.agent_status:
            self.agent_status[agent] = status
            self.current_agent = agent

    def update_report_section(self, section_name, content):
        if section_name in self.report_sections:
            self.report_sections[section_name] = content
            self._update_current_report()

    def _update_current_report(self):
        latest_section = None
        latest_content = None

        for section, content in self.report_sections.items():
            if content is not None:
                latest_section = section
                latest_content = content

        if latest_section and latest_content:
            section_titles = {
                "market_report": "Market Analysis",
                "sentiment_report": "Social Sentiment",
                "news_report": "News Analysis",
                "fundamentals_report": "Fundamentals Analysis",
                "investment_plan": "Research Team Decision",
                "trader_investment_plan": "Trading Team Plan",
                "final_trade_decision": "Portfolio Management Decision",
            }
            self.current_report = (
                f"### {section_titles[latest_section]}\n{latest_content}"
            )

        self._update_final_report()

    def _update_final_report(self):
        report_parts = []

        analyst_sections = ["market_report", "sentiment_report", "news_report", "fundamentals_report"]
        if any(self.report_sections.get(section) for section in analyst_sections):
            report_parts.append("## Analyst Team Reports")
            if self.report_sections.get("market_report"):
                report_parts.append(
                    f"### Market Analysis\n{self.report_sections['market_report']}"
                )
            if self.report_sections.get("sentiment_report"):
                report_parts.append(
                    f"### Social Sentiment\n{self.report_sections['sentiment_report']}"
                )
            if self.report_sections.get("news_report"):
                report_parts.append(
                    f"### News Analysis\n{self.report_sections['news_report']}"
                )
            if self.report_sections.get("fundamentals_report"):
                report_parts.append(
                    f"### Fundamentals Analysis\n{self.report_sections['fundamentals_report']}"
                )

        if self.report_sections.get("investment_plan"):
            report_parts.append("## Research Team Decision")
            report_parts.append(f"{self.report_sections['investment_plan']}")

        if self.report_sections.get("trader_investment_plan"):
            report_parts.append("## Trading Team Plan")
            report_parts.append(f"{self.report_sections['trader_investment_plan']}")

        if self.report_sections.get("final_trade_decision"):
            report_parts.append("## Portfolio Management Decision")
            report_parts.append(f"{self.report_sections['final_trade_decision']}")

        self.final_report = "\n\n".join(report_parts) if report_parts else None


message_buffer = MessageBuffer()


def create_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3),
    )
    layout["main"].split_row(
        Layout(name="left", ratio=2), Layout(name="analysis", ratio=3)
    )
    layout["left"].split_column(
        Layout(name="progress", ratio=3), Layout(name="messages", ratio=2)
    )
    return layout


def format_tokens(n):
    """Format token count for display."""
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def update_display(layout, spinner_text=None, stats_handler=None, start_time=None):
    from cybernetic.cli.theme import t

    # Header with CyberneticAgents branding
    layout["header"].update(
        Panel(
            f"[{t('primary_bold')}]CYBERNETIC.BIZ[/{t('primary_bold')}] - "
            f"[{t('banner_subtitle')}]Building Unique Intelligence[/{t('banner_subtitle')}]",
            border_style=t("border_header"),
            padding=(0, 2),
            expand=True,
        )
    )

    # Progress panel showing agent status
    progress_table = Table(
        show_header=True,
        header_style=f"bold {t('accent')}",
        show_footer=False,
        box=box.SIMPLE_HEAD,
        title=None,
        padding=(0, 2),
        expand=True,
    )
    progress_table.add_column("Team", style=t("team_style"), justify="center", width=20)
    progress_table.add_column("Agent", style=t("agent_style"), justify="center", width=20)
    progress_table.add_column("Status", style=t("status_pending"), justify="center", width=20)

    all_teams = {
        "Analyst Team": [
            "Market Analyst",
            "Social Analyst",
            "News Analyst",
            "Fundamentals Analyst",
        ],
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    teams = {}
    for team, agents in all_teams.items():
        active_agents = [a for a in agents if a in message_buffer.agent_status]
        if active_agents:
            teams[team] = active_agents

    status_colors = {
        "pending": t("status_pending"),
        "completed": t("status_completed"),
        "error": t("status_error"),
    }
    ip_color = t("status_in_progress")

    for team, agents in teams.items():
        first_agent = agents[0]
        status = message_buffer.agent_status.get(first_agent, "pending")
        if status == "in_progress":
            spinner = Spinner(
                "dots", text=f"[{ip_color}]in_progress[/{ip_color}]", style=f"bold {t('secondary')}"
            )
            status_cell = spinner
        else:
            sc = status_colors.get(status, "white")
            status_cell = f"[{sc}]{status}[/{sc}]"
        progress_table.add_row(team, first_agent, status_cell)

        for agent in agents[1:]:
            status = message_buffer.agent_status.get(agent, "pending")
            if status == "in_progress":
                spinner = Spinner(
                    "dots", text=f"[{ip_color}]in_progress[/{ip_color}]", style=f"bold {t('secondary')}"
                )
                status_cell = spinner
            else:
                sc = status_colors.get(status, "white")
                status_cell = f"[{sc}]{status}[/{sc}]"
            progress_table.add_row("", agent, status_cell)

        progress_table.add_row("─" * 20, "─" * 20, "─" * 20, style="dim")

    layout["progress"].update(
        Panel(progress_table, title="Progress", border_style=t("border_progress"), padding=(1, 2))
    )

    # Messages panel
    messages_table = Table(
        show_header=True,
        header_style=f"bold {t('accent')}",
        show_footer=False,
        expand=True,
        box=box.MINIMAL,
        show_lines=True,
        padding=(0, 1),
    )
    messages_table.add_column("Time", style=t("time_style"), width=8, justify="center")
    messages_table.add_column("Type", style=t("type_style"), width=10, justify="center")
    messages_table.add_column("Content", style="white", no_wrap=False, ratio=1)

    all_messages = []

    for timestamp, tool_name, args in message_buffer.tool_calls:
        formatted_args = format_tool_args(args)
        all_messages.append((timestamp, "Tool", f"{tool_name}: {formatted_args}"))

    for timestamp, msg_type, content in message_buffer.messages:
        content_str = str(content) if content else ""
        if len(content_str) > 200:
            content_str = content_str[:197] + "..."
        all_messages.append((timestamp, msg_type, content_str))

    all_messages.sort(key=lambda x: x[0], reverse=True)

    max_messages = 12
    recent_messages = all_messages[:max_messages]

    for timestamp, msg_type, content in recent_messages:
        wrapped_content = Text(content, overflow="fold")
        messages_table.add_row(timestamp, msg_type, wrapped_content)

    layout["messages"].update(
        Panel(
            messages_table,
            title="Messages & Tools",
            border_style=t("border_messages"),
            padding=(1, 2),
        )
    )

    # Analysis panel
    if message_buffer.current_report:
        layout["analysis"].update(
            Panel(
                Markdown(message_buffer.current_report),
                title="Current Report",
                border_style=t("border_report"),
                padding=(1, 2),
            )
        )
    else:
        layout["analysis"].update(
            Panel(
                "[italic]Waiting for analysis report...[/italic]",
                title="Current Report",
                border_style=t("border_report"),
                padding=(1, 2),
            )
        )

    # Footer with statistics
    agents_completed = sum(
        1 for status in message_buffer.agent_status.values() if status == "completed"
    )
    agents_total = len(message_buffer.agent_status)

    reports_completed = message_buffer.get_completed_reports_count()
    reports_total = len(message_buffer.report_sections)

    stats_parts = [f"Agents: {agents_completed}/{agents_total}"]

    if stats_handler:
        stats = stats_handler.get_stats()
        stats_parts.append(f"LLM: {stats['llm_calls']}")
        stats_parts.append(f"Tools: {stats['tool_calls']}")

        if stats["tokens_in"] > 0 or stats["tokens_out"] > 0:
            tokens_str = f"Tokens: {format_tokens(stats['tokens_in'])}\u2191 {format_tokens(stats['tokens_out'])}\u2193"
        else:
            tokens_str = "Tokens: --"
        stats_parts.append(tokens_str)

    stats_parts.append(f"Reports: {reports_completed}/{reports_total}")

    if start_time:
        elapsed = time.time() - start_time
        elapsed_str = f"\u23f1 {int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        stats_parts.append(elapsed_str)

    stats_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
    stats_table.add_column("Stats", justify="center")
    stats_table.add_row(" | ".join(stats_parts))

    layout["footer"].update(Panel(stats_table, border_style=t("border_footer")))


def create_question_box(title, prompt, default=None):
    """Create a Rich panel box for a question step."""
    box_content = f"[bold]{title}[/bold]\n"
    box_content += f"[dim]{prompt}[/dim]"
    if default:
        box_content += f"\n[dim]Default: {default}[/dim]"
    return Panel(box_content, border_style="blue", padding=(1, 2))


def get_user_selections():
    """Get all user selections before starting the analysis display.

    Uses step-based navigation: ESC goes back to the previous step,
    ESC on step 1 returns None (back to main menu).
    """
    # Display CyberneticAgents banner
    art_path = Path(__file__).parent.parent.parent / "docs" / "ascii-text-art.txt"
    term_width = console.size.width
    # Reserve space for panel border + padding (2 border + 2*2 padding = 6)
    inner_width = max(term_width - 6, 20)

    # Determine if the full ASCII art fits; if not, use a compact fallback
    use_full_art = False
    if art_path.exists() and inner_width >= 40:
        raw_lines = art_path.read_text().splitlines()
        while raw_lines and not raw_lines[-1].strip():
            raw_lines.pop()
        art_max_width = max((len(line) for line in raw_lines), default=0)
        if art_max_width <= inner_width:
            welcome_ascii = "\n".join(raw_lines)
            use_full_art = True

    if not use_full_art:
        # Compact single-line fallback that fits any terminal
        welcome_ascii = "C Y B E R N E T I C\n        A G E N T S"

    from rich.console import Group
    from cybernetic.cli.theme import t
    welcome_box = Panel(
        Group(
            Align.center(Text(welcome_ascii, style=t("banner_style"))),
            Text(),
            Align.center(Text("CyberneticAgents: Building Unique Intelligence", style=t("welcome_title"))),
            Text(),
            Align.center(Text("Workflow Steps:", style="bold")),
            Align.center(Text(
                "I. Analyst Team -> II. Research Team -> III. Trader\n"
                "-> IV. Risk Management -> V. Portfolio Management",
                style=t("welcome_workflow"),
            )),
            Text(),
        ),
        border_style=t("border_welcome"),
        padding=(1, 2),
        title="Cybernetic.biz",
        subtitle="Self-Regulating Systems and Feedback Loops",
    )
    console.print(Align.center(welcome_box))
    console.print()

    selections = {}
    step = 1

    while True:
        if step == 1:
            console.print(
                create_question_box(
                    "Step 1: Ticker Symbol", "Enter the ticker symbol to analyze (ESC to go back)", "SPY"
                )
            )
            result = get_ticker()
            if result is None:
                return None  # ESC on first step = back to main menu
            selections["ticker"] = result
            step = 2

        elif step == 2:
            default_date = datetime.datetime.now().strftime("%Y-%m-%d")
            console.print(
                create_question_box(
                    "Step 2: Analysis Date",
                    "Enter the analysis date (ESC to go back)",
                    default_date,
                )
            )
            result = get_analysis_date()
            if result is None:
                step = 1
                continue
            selections["analysis_date"] = result
            step = 3

        elif step == 3:
            console.print(
                create_question_box(
                    "Step 3: Analysts Team", "Select your LLM analyst agents for the analysis"
                )
            )
            result = select_analysts()
            if result is None:
                step = 2
                continue
            selections["analysts"] = result
            console.print(
                f"[green]Selected analysts:[/green] {', '.join(analyst.value for analyst in result)}"
            )
            step = 4

        elif step == 4:
            console.print(
                create_question_box(
                    "Step 4: Research Depth", "Select your research depth level"
                )
            )
            result = select_research_depth()
            if result is None:
                step = 3
                continue
            selections["research_depth"] = result
            step = 5

        elif step == 5:
            console.print(
                create_question_box(
                    "Step 5: LLM Provider", "Select which service to use"
                )
            )
            result = select_llm_provider()
            if result is None:
                step = 4
                continue
            selections["llm_provider"], selections["backend_url"] = result
            step = 6

        elif step == 6:
            console.print(
                create_question_box(
                    "Step 6: Thinking Agents", "Select your thinking agents for analysis"
                )
            )
            result = select_shallow_thinking_agent(selections["llm_provider"])
            if result is None:
                step = 5
                continue
            selections["shallow_thinker"] = result
            step = 7

        elif step == 7:
            result = select_deep_thinking_agent(selections["llm_provider"])
            if result is None:
                step = 6
                continue
            selections["deep_thinker"] = result
            step = 8

        elif step == 8:
            provider_lower = selections["llm_provider"].lower()
            if provider_lower == "google":
                console.print(
                    create_question_box(
                        "Step 7: Thinking Mode",
                        "Configure Gemini thinking mode"
                    )
                )
                result = ask_gemini_thinking_config()
                if result is None:
                    step = 7
                    continue
                selections["google_thinking_level"] = result
            elif provider_lower == "openai":
                console.print(
                    create_question_box(
                        "Step 7: Reasoning Effort",
                        "Configure OpenAI reasoning effort level"
                    )
                )
                result = ask_openai_reasoning_effort()
                if result is None:
                    step = 7
                    continue
                selections["openai_reasoning_effort"] = result
            break

    return {
        "ticker": selections["ticker"],
        "analysis_date": selections["analysis_date"],
        "analysts": selections["analysts"],
        "research_depth": selections["research_depth"],
        "llm_provider": selections["llm_provider"].lower(),
        "backend_url": selections["backend_url"],
        "shallow_thinker": selections["shallow_thinker"],
        "deep_thinker": selections["deep_thinker"],
        "google_thinking_level": selections.get("google_thinking_level"),
        "openai_reasoning_effort": selections.get("openai_reasoning_effort"),
    }


def save_report_to_disk(final_state, ticker: str, save_path: Path):
    """Save complete analysis report to disk with organized subfolders."""
    save_path.mkdir(parents=True, exist_ok=True)
    sections = []

    # 1. Analysts
    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    if final_state.get("market_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "market.md").write_text(final_state["market_report"])
        analyst_parts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "sentiment.md").write_text(final_state["sentiment_report"])
        analyst_parts.append(("Social Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "news.md").write_text(final_state["news_report"])
        analyst_parts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "fundamentals.md").write_text(final_state["fundamentals_report"])
        analyst_parts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    # 2. Research
    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        debate = final_state["investment_debate_state"]
        research_parts = []
        if debate.get("bull_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bull.md").write_text(debate["bull_history"])
            research_parts.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bear.md").write_text(debate["bear_history"])
            research_parts.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "manager.md").write_text(debate["judge_decision"])
            research_parts.append(("Research Manager", debate["judge_decision"]))
        if research_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
            sections.append(f"## II. Research Team Decision\n\n{content}")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        (trading_dir / "trader.md").write_text(final_state["trader_investment_plan"])
        sections.append(f"## III. Trading Team Plan\n\n### Trader\n{final_state['trader_investment_plan']}")

    # 4. Risk Management
    if final_state.get("risk_debate_state"):
        risk_dir = save_path / "4_risk"
        risk = final_state["risk_debate_state"]
        risk_parts = []
        if risk.get("aggressive_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "aggressive.md").write_text(risk["aggressive_history"])
            risk_parts.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "conservative.md").write_text(risk["conservative_history"])
            risk_parts.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "neutral.md").write_text(risk["neutral_history"])
            risk_parts.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
            sections.append(f"## IV. Risk Management Team Decision\n\n{content}")

        # 5. Portfolio Manager
        if risk.get("judge_decision"):
            portfolio_dir = save_path / "5_portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            (portfolio_dir / "decision.md").write_text(risk["judge_decision"])
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{risk['judge_decision']}")

    # Write consolidated report
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    (save_path / "complete_report.md").write_text(header + "\n\n".join(sections))
    return save_path / "complete_report.md"


def display_complete_report(final_state):
    """Display the complete analysis report sequentially."""
    console.print()
    console.print(Rule("Complete Analysis Report", style="bold green"))

    # I. Analyst Team Reports
    analysts = []
    if final_state.get("market_report"):
        analysts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts.append(("Social Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analysts:
        console.print(Panel("[bold]I. Analyst Team Reports[/bold]", border_style="cyan"))
        for title, content in analysts:
            console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

    # II. Research Team Reports
    if final_state.get("investment_debate_state"):
        debate = final_state["investment_debate_state"]
        research = []
        if debate.get("bull_history"):
            research.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research.append(("Research Manager", debate["judge_decision"]))
        if research:
            console.print(Panel("[bold]II. Research Team Decision[/bold]", border_style="magenta"))
            for title, content in research:
                console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

    # III. Trading Team
    if final_state.get("trader_investment_plan"):
        console.print(Panel("[bold]III. Trading Team Plan[/bold]", border_style="yellow"))
        console.print(Panel(Markdown(final_state["trader_investment_plan"]), title="Trader", border_style="blue", padding=(1, 2)))

    # IV. Risk Management Team
    if final_state.get("risk_debate_state"):
        risk = final_state["risk_debate_state"]
        risk_reports = []
        if risk.get("aggressive_history"):
            risk_reports.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_reports.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_reports.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_reports:
            console.print(Panel("[bold]IV. Risk Management Team Decision[/bold]", border_style="red"))
            for title, content in risk_reports:
                console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

        # V. Portfolio Manager Decision
        if risk.get("judge_decision"):
            console.print(Panel("[bold]V. Portfolio Manager Decision[/bold]", border_style="green"))
            console.print(Panel(Markdown(risk["judge_decision"]), title="Portfolio Manager", border_style="blue", padding=(1, 2)))


def update_research_team_status(status):
    """Update status for research team members (not Trader)."""
    research_team = ["Bull Researcher", "Bear Researcher", "Research Manager"]
    for agent in research_team:
        message_buffer.update_agent_status(agent, status)


# Ordered list of analysts for status transitions
ANALYST_ORDER = ["market", "social", "news", "fundamentals"]
ANALYST_AGENT_NAMES = {
    "market": "Market Analyst",
    "social": "Social Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}
ANALYST_REPORT_MAP = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}


def update_analyst_statuses(message_buffer, chunk):
    """Update all analyst statuses based on current report state."""
    selected = message_buffer.selected_analysts
    found_active = False

    for analyst_key in ANALYST_ORDER:
        if analyst_key not in selected:
            continue

        agent_name = ANALYST_AGENT_NAMES[analyst_key]
        report_key = ANALYST_REPORT_MAP[analyst_key]
        has_report = bool(chunk.get(report_key))

        if has_report:
            message_buffer.update_agent_status(agent_name, "completed")
            message_buffer.update_report_section(report_key, chunk[report_key])
        elif not found_active:
            message_buffer.update_agent_status(agent_name, "in_progress")
            found_active = True
        else:
            message_buffer.update_agent_status(agent_name, "pending")

    if not found_active and selected:
        if message_buffer.agent_status.get("Bull Researcher") == "pending":
            message_buffer.update_agent_status("Bull Researcher", "in_progress")


def extract_content_string(content):
    """Extract string content from various message formats."""
    import ast

    def is_empty(val):
        if val is None or val == '':
            return True
        if isinstance(val, str):
            s = val.strip()
            if not s:
                return True
            try:
                return not bool(ast.literal_eval(s))
            except (ValueError, SyntaxError):
                return False
        return not bool(val)

    if is_empty(content):
        return None

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, dict):
        text = content.get('text', '')
        return text.strip() if not is_empty(text) else None

    if isinstance(content, list):
        text_parts = [
            item.get('text', '').strip() if isinstance(item, dict) and item.get('type') == 'text'
            else (item.strip() if isinstance(item, str) else '')
            for item in content
        ]
        result = ' '.join(t for t in text_parts if t and not is_empty(t))
        return result if result else None

    return str(content).strip() if not is_empty(content) else None


def classify_message_type(message):
    """Classify LangChain message into display type and extract content."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    content = extract_content_string(getattr(message, 'content', None))

    if isinstance(message, HumanMessage):
        if content and content.strip() == "Continue":
            return ("Control", content)
        return ("User", content)

    if isinstance(message, ToolMessage):
        return ("Data", content)

    if isinstance(message, AIMessage):
        return ("Agent", content)

    return ("System", content)


def format_tool_args(args, max_length=80) -> str:
    """Format tool arguments for terminal display."""
    result = str(args)
    if len(result) > max_length:
        return result[:max_length - 3] + "..."
    return result


def _setup_esc_listener():
    """Set terminal to cbreak mode for non-blocking ESC detection during analysis."""
    import tty
    import termios
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())
    return old_settings


def _restore_terminal(old_settings):
    """Restore terminal settings after ESC listener."""
    import termios
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def _check_esc():
    """Non-blocking check if ESC was pressed. Returns True if ESC detected."""
    try:
        if _select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                # Drain any remaining escape sequence chars (arrow keys send multi-byte)
                while _select.select([sys.stdin], [], [], 0.01)[0]:
                    sys.stdin.read(1)
                return True
    except Exception:
        pass
    return False


def _flush_stdin() -> None:
    """Discard any buffered keystrokes so they don't leak into the next prompt."""
    import sys
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except (ImportError, termios.error):
        pass


def run_analysis():
    """Run the full research analysis flow."""
    _flush_stdin()

    # First get all user selections
    selections = get_user_selections()

    if selections is None:
        return  # User pressed ESC on first step, back to menu

    # Heavy imports deferred until after the user has made all selections
    from cybernetic.research.graph import CyberneticAgentsGraph
    from cybernetic.cli.stats_handler import StatsCallbackHandler

    # Create config with selected research depth
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = selections["research_depth"]
    config["max_risk_discuss_rounds"] = selections["research_depth"]
    config["quick_think_llm"] = selections["shallow_thinker"]
    config["deep_think_llm"] = selections["deep_thinker"]
    config["backend_url"] = selections["backend_url"]
    config["llm_provider"] = selections["llm_provider"].lower()
    config["google_thinking_level"] = selections.get("google_thinking_level")
    config["openai_reasoning_effort"] = selections.get("openai_reasoning_effort")

    # Create stats callback handler for tracking LLM/tool calls
    stats_handler = StatsCallbackHandler()

    # Normalize analyst selection to predefined order
    selected_set = {analyst.value for analyst in selections["analysts"]}
    selected_analyst_keys = [a for a in ANALYST_ORDER if a in selected_set]

    # Initialize the graph with callbacks bound to LLMs
    graph = CyberneticAgentsGraph(
        selected_analyst_keys,
        config=config,
        debug=True,
        callbacks=[stats_handler],
    )

    # Initialize message buffer with selected analysts
    message_buffer.init_for_analysis(selected_analyst_keys)

    # Track start time for elapsed display
    start_time = time.time()

    # Create result directory
    results_dir = Path(config["results_dir"]) / selections["ticker"] / selections["analysis_date"]
    results_dir.mkdir(parents=True, exist_ok=True)
    report_dir = results_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_file = results_dir / "message_tool.log"
    log_file.touch(exist_ok=True)

    def save_message_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, message_type, content = obj.messages[-1]
            content = content.replace("\n", " ")
            with open(log_file, "a") as f:
                f.write(f"{timestamp} [{message_type}] {content}\n")
        return wrapper

    def save_tool_call_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, tool_name, args = obj.tool_calls[-1]
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            with open(log_file, "a") as f:
                f.write(f"{timestamp} [Tool Call] {tool_name}({args_str})\n")
        return wrapper

    def save_report_section_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(section_name, content):
            func(section_name, content)
            if section_name in obj.report_sections and obj.report_sections[section_name] is not None:
                content = obj.report_sections[section_name]
                if content:
                    file_name = f"{section_name}.md"
                    with open(report_dir / file_name, "w") as f:
                        f.write(content)
        return wrapper

    message_buffer.add_message = save_message_decorator(message_buffer, "add_message")
    message_buffer.add_tool_call = save_tool_call_decorator(message_buffer, "add_tool_call")
    message_buffer.update_report_section = save_report_section_decorator(message_buffer, "update_report_section")

    # Now start the display layout
    layout = create_layout()

    # Set up ESC detection for quit-during-analysis
    analysis_cancelled = False
    old_terminal = None
    try:
        old_terminal = _setup_esc_listener()
    except Exception:
        pass  # If terminal setup fails (e.g. non-tty), skip ESC detection

    try:
        with Live(layout, refresh_per_second=4) as live:
            # Initial display
            update_display(layout, stats_handler=stats_handler, start_time=start_time)

            message_buffer.add_message("System", f"Selected ticker: {selections['ticker']}")
            message_buffer.add_message(
                "System", f"Analysis date: {selections['analysis_date']}"
            )
            message_buffer.add_message(
                "System",
                f"Selected analysts: {', '.join(analyst.value for analyst in selections['analysts'])}",
            )
            update_display(layout, stats_handler=stats_handler, start_time=start_time)

            first_analyst = f"{selections['analysts'][0].value.capitalize()} Analyst"
            message_buffer.update_agent_status(first_analyst, "in_progress")
            update_display(layout, stats_handler=stats_handler, start_time=start_time)

            spinner_text = (
                f"Analyzing {selections['ticker']} on {selections['analysis_date']}..."
            )
            update_display(layout, spinner_text, stats_handler=stats_handler, start_time=start_time)

            # Initialize state and get graph args with callbacks
            init_agent_state = graph.propagator.create_initial_state(
                selections["ticker"], selections["analysis_date"]
            )
            args = graph.propagator.get_graph_args(callbacks=[stats_handler])

            # Stream the analysis
            trace = []
            for chunk in graph.graph.stream(init_agent_state, **args):
                # Check for ESC during analysis
                if old_terminal is not None and _check_esc():
                    live.stop()
                    _restore_terminal(old_terminal)
                    confirm = ask(questionary.confirm(
                        "Analysis in progress. Quit? (progress will be lost)",
                        qmark=QMARK,
                        default=False,
                    ))
                    if confirm:
                        console.print("[yellow]Analysis cancelled.[/yellow]")
                        analysis_cancelled = True
                        break
                    # Resume analysis display
                    old_terminal = _setup_esc_listener()
                    live.start()

                if len(chunk["messages"]) > 0:
                    last_message = chunk["messages"][-1]
                    msg_id = getattr(last_message, "id", None)

                    if msg_id != message_buffer._last_message_id:
                        message_buffer._last_message_id = msg_id

                        msg_type, content = classify_message_type(last_message)
                        if content and content.strip():
                            message_buffer.add_message(msg_type, content)

                        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                            for tool_call in last_message.tool_calls:
                                if isinstance(tool_call, dict):
                                    message_buffer.add_tool_call(
                                        tool_call["name"], tool_call["args"]
                                    )
                                else:
                                    message_buffer.add_tool_call(tool_call.name, tool_call.args)

                update_analyst_statuses(message_buffer, chunk)

                # Research Team - Handle Investment Debate State
                if chunk.get("investment_debate_state"):
                    debate_state = chunk["investment_debate_state"]
                    bull_hist = debate_state.get("bull_history", "").strip()
                    bear_hist = debate_state.get("bear_history", "").strip()
                    judge = debate_state.get("judge_decision", "").strip()

                    if bull_hist or bear_hist:
                        update_research_team_status("in_progress")
                    if bull_hist:
                        message_buffer.update_report_section(
                            "investment_plan", f"### Bull Researcher Analysis\n{bull_hist}"
                        )
                    if bear_hist:
                        message_buffer.update_report_section(
                            "investment_plan", f"### Bear Researcher Analysis\n{bear_hist}"
                        )
                    if judge:
                        message_buffer.update_report_section(
                            "investment_plan", f"### Research Manager Decision\n{judge}"
                        )
                        update_research_team_status("completed")
                        message_buffer.update_agent_status("Trader", "in_progress")

                # Trading Team
                if chunk.get("trader_investment_plan"):
                    message_buffer.update_report_section(
                        "trader_investment_plan", chunk["trader_investment_plan"]
                    )
                    if message_buffer.agent_status.get("Trader") != "completed":
                        message_buffer.update_agent_status("Trader", "completed")
                        message_buffer.update_agent_status("Aggressive Analyst", "in_progress")

                # Risk Management Team - Handle Risk Debate State
                if chunk.get("risk_debate_state"):
                    risk_state = chunk["risk_debate_state"]
                    agg_hist = risk_state.get("aggressive_history", "").strip()
                    con_hist = risk_state.get("conservative_history", "").strip()
                    neu_hist = risk_state.get("neutral_history", "").strip()
                    judge = risk_state.get("judge_decision", "").strip()

                    if agg_hist:
                        if message_buffer.agent_status.get("Aggressive Analyst") != "completed":
                            message_buffer.update_agent_status("Aggressive Analyst", "in_progress")
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Aggressive Analyst Analysis\n{agg_hist}"
                        )
                    if con_hist:
                        if message_buffer.agent_status.get("Conservative Analyst") != "completed":
                            message_buffer.update_agent_status("Conservative Analyst", "in_progress")
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Conservative Analyst Analysis\n{con_hist}"
                        )
                    if neu_hist:
                        if message_buffer.agent_status.get("Neutral Analyst") != "completed":
                            message_buffer.update_agent_status("Neutral Analyst", "in_progress")
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Neutral Analyst Analysis\n{neu_hist}"
                        )
                    if judge:
                        if message_buffer.agent_status.get("Portfolio Manager") != "completed":
                            message_buffer.update_agent_status("Portfolio Manager", "in_progress")
                            message_buffer.update_report_section(
                                "final_trade_decision", f"### Portfolio Manager Decision\n{judge}"
                            )
                            message_buffer.update_agent_status("Aggressive Analyst", "completed")
                            message_buffer.update_agent_status("Conservative Analyst", "completed")
                            message_buffer.update_agent_status("Neutral Analyst", "completed")
                            message_buffer.update_agent_status("Portfolio Manager", "completed")

                update_display(layout, stats_handler=stats_handler, start_time=start_time)

                trace.append(chunk)

            if analysis_cancelled or not trace:
                return

            # Get final state and decision
            final_state = trace[-1]
            decision = graph.process_signal(final_state["final_trade_decision"])

            for agent in message_buffer.agent_status:
                message_buffer.update_agent_status(agent, "completed")

            message_buffer.add_message(
                "System", f"Completed analysis for {selections['analysis_date']}"
            )

            for section in message_buffer.report_sections.keys():
                if section in final_state:
                    message_buffer.update_report_section(section, final_state[section])

            update_display(layout, stats_handler=stats_handler, start_time=start_time)
    finally:
        # Always restore terminal settings
        if old_terminal is not None:
            try:
                _restore_terminal(old_terminal)
            except Exception:
                pass

    # Post-analysis prompts (outside Live context for clean interaction)
    console.print("\n[bold cyan]Analysis Complete![/bold cyan]\n")

    # Prompt to save report
    save_choice = ask(questionary.confirm("Save report?", qmark=QMARK, default=True))
    if save_choice is None:
        return  # ESC → back to menu
    if save_choice:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = Path.cwd() / "reports" / f"{selections['ticker']}_{timestamp}"
        save_path_str = ask(questionary.text(
            "Save path (press Enter for default):",
            qmark=QMARK,
            default=str(default_path),
        ))
        if save_path_str is None:
            return  # ESC → back to menu
        save_path = Path(save_path_str.strip())
        try:
            report_file = save_report_to_disk(final_state, selections["ticker"], save_path)
            console.print(f"\n[green]Report saved to:[/green] {save_path.resolve()}")
            console.print(f"  [dim]Complete report:[/dim] {report_file.name}")
        except Exception as e:
            console.print(f"[red]Error saving report: {e}[/red]")

    # Prompt to display full report
    display_choice = ask(questionary.confirm("Display full report on screen?", qmark=QMARK, default=True))
    if display_choice is None:
        return  # ESC → back to menu
    if display_choice:
        display_complete_report(final_state)

    # Agent generation flow
    from cybernetic.agents.generator import generate_agent_from_report
    from cybernetic.agents.names import generate_funny_name

    choice = ask(questionary.select(
        "What would you like to do next?",
        qmark=QMARK,
        choices=[
            questionary.Choice("Generate Agent from this Report", value="generate"),
            questionary.Choice("New Research", value="new"),
            questionary.Choice("Back to Menu", value="menu"),
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select\n- Press ESC to go back",
    ))

    if choice is None or choice == "menu":
        return

    if choice == "generate":
        # 1. Agent name
        console.print(create_question_box("Agent Name", "Choose a name for your agent"))
        default_name = generate_funny_name()
        agent_name = ask(questionary.text("Agent name:", qmark=QMARK, default=default_name))
        if agent_name is None:
            return
        if not agent_name:
            agent_name = default_name

        # 2. Description
        console.print(create_question_box("Description", "Describe your agent's strategy"))
        description = ask(questionary.text("Description (optional):", qmark=QMARK, default=""))
        if description is None:
            return
        description = description or ""

        # 3. Analysts/Tools (pre-selected from research analysts used)
        console.print(create_question_box("Analyst Tools", "Select which analysts your agent will use"))
        research_tools = [a.value for a in selections.get("analysts", [])]
        all_tools = ["market", "social", "news", "fundamentals"]
        from cybernetic.cli.theme import t as theme
        tools = ask(questionary.checkbox(
            "Analyst tools:",
            qmark=QMARK,
            choices=[
                questionary.Choice(tool.capitalize(), value=tool, checked=(tool in research_tools))
                for tool in all_tools
            ],
            instruction="\n- Press Space to select/unselect\n- Press 'a' to toggle all\n- Press Enter when done",
            style=questionary.Style([
                ("checkbox-selected", theme("menu_checkbox")),
                ("selected", theme("menu_selected")),
                ("highlighted", "noinherit"),
                ("pointer", "noinherit"),
            ]),
        ))
        if tools is None:
            return
        tools = tools or research_tools

        # 4. Target days — LLM picks from the report, user can override
        from cybernetic.agents.generator import pick_target_days_from_report
        from cybernetic.config import get_config
        with console.status("[cyan]Determining prediction target from report...[/cyan]"):
            try:
                target_days = pick_target_days_from_report(
                    report_text=final_state.get("final_trade_decision", "")
                    or final_state.get("trader_investment_plan", ""),
                    decision=decision,
                    ticker=selections["ticker"],
                    config=get_config(),
                )
            except Exception:
                target_days = 7
        console.print(f"  [cyan]LLM selected target:[/cyan] [bold]{target_days} days[/bold]")
        override = ask(questionary.confirm("Override target days?", qmark=QMARK, default=False))
        if override is None:
            return
        if override:
            target_days = ask(questionary.select(
                "Prediction target (days):",
                qmark=QMARK,
                choices=[
                    questionary.Choice("1 day", value=1),
                    questionary.Choice("3 days", value=3),
                    questionary.Choice("5 days", value=5),
                    questionary.Choice("7 days", value=7),
                    questionary.Choice("14 days", value=14),
                    questionary.Choice("30 days", value=30),
                ],
                default=target_days,
            ))
            if target_days is None:
                return
            target_days = target_days or 7

        # 5. Personality
        console.print(create_question_box("Personality", "Give your agent a personality trait"))
        personality = ask(questionary.text("Personality trait (optional):", qmark=QMARK, default=""))
        if personality is None:
            return
        personality = personality or ""

        # 6. Analysis temperature
        console.print(create_question_box("Analysis Temperature", "How creative should the agent be?"))
        temp_choice = ask(questionary.select(
            "Analysis temperature:",
            qmark=QMARK,
            choices=[
                questionary.Choice(f"{label} ({v})", value=v) for v, label in TEMP_LABELS.items()
            ],
            default=0.7,
        ))
        if temp_choice is None:
            return
        analysis_temperature = temp_choice

        # 7. Max positions (default 1 for single-ticker research)
        console.print(create_question_box("Max Positions", "Maximum concurrent positions"))
        max_pos_str = ask(questionary.text("Max positions:", qmark=QMARK, default="1"))
        if max_pos_str is None:
            return
        max_pos_str = max_pos_str or "1"
        try:
            max_positions = max(1, min(20, int(max_pos_str)))
        except ValueError:
            max_positions = 5

        agent = generate_agent_from_report(
            final_state, decision, selections["ticker"],
            agent_name=agent_name.strip() if agent_name.strip() else None,
            description=description,
            tools=tools,
            target_days=target_days,
            max_positions=max_positions,
            personality=personality,
            analysis_temperature=analysis_temperature,
        )

        # Display agent config summary
        import json
        cfg = json.loads(agent.persona_json) if agent.persona_json else {}
        cfg.update({
            "name": agent.name,
            "ticker": agent.ticker,
            "description": agent.description or description,
            "tools": tools,
            "target_days": target_days,
            "max_positions": max_positions,
            "personality": personality,
            "analysis_temperature": analysis_temperature,
            "direction_bias": agent.direction_bias or "bullish",
        })
        console.print()
        display_agent_config(cfg)

        console.print(f"\n[green]Agent created: {agent.id}[/green]")
        console.print(f"[dim]Portfolio: ${agent.portfolio_balance:,.2f}[/dim]")

        run_now = ask(questionary.confirm("Run agent now?", qmark=QMARK, default=True))
        if run_now:
            from cybernetic.agents.runner import run_agent_once
            run_agent_once(agent.id)
    elif choice == "new":
        run_analysis()
