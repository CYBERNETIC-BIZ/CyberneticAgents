"""Theme system for CyberneticAgents CLI."""
import json
from pathlib import Path
from typing import Dict


# VSCode Dark+ terminal ANSI palette (hex values):
# Green=#0DBC79  BrightGreen=#23D18B  Cyan=#11A8CD  BrightCyan=#29B8DB
# Blue=#2472C8   BrightBlue=#3B8EEA   Magenta=#BC3FBC  BrightMagenta=#D670D6
# Yellow=#E5E510 BrightYellow=#F5F543  Red=#CD3131  BrightRed=#F14C4C

THEMES: Dict[str, Dict[str, str]] = {
    "terminal": {
        "name": "Neon Pulse",
        "description": "Vivid ANSI colors for standalone terminals",
        # Rich styles
        "primary": "green",
        "primary_bold": "bold green",
        "secondary": "cyan",
        "accent": "magenta",
        "highlight": "yellow",
        "error": "red",
        "success": "green",
        "banner_style": "bold green",
        "banner_subtitle": "dim",
        # Panel borders
        "border_header": "green",
        "border_progress": "cyan",
        "border_messages": "blue",
        "border_report": "green",
        "border_footer": "grey50",
        "border_config": "bright_green",
        "border_welcome": "green",
        # Dashboard text
        "team_style": "cyan",
        "agent_style": "green",
        "status_pending": "yellow",
        "status_completed": "green",
        "status_error": "red",
        "status_in_progress": "blue",
        "time_style": "cyan",
        "type_style": "green",
        # Welcome box
        "welcome_title": "bold bright_white",
        "welcome_workflow": "white",
        # Questionary (ANSI names for prompt_toolkit)
        "menu_selected": "fg:ansibrightgreen noinherit",
        "menu_highlighted": "fg:ansibrightgreen noinherit",
        "menu_pointer": "fg:ansibrightgreen noinherit",
        "menu_separator": "fg:ansibrightmagenta",
        "menu_qmark": "fg:ansibrightgreen bold",
        "menu_question": "fg:ansibrightgreen bold",
        "menu_checkbox": "fg:ansibrightgreen",
        "menu_text": "fg:ansibrightgreen",
        "menu_accent": "fg:ansiyellow noinherit",
        "menu_accent2": "fg:ansimagenta noinherit",
        "menu_confirm": "fg:ansired",
    },
    "vscode": {
        "name": "Deep Space",
        "description": "True-color palette for VSCode and modern terminals",
        # Rich styles — hex colors from VSCode Dark+ ANSI palette
        "primary": "#0DBC79",
        "primary_bold": "bold #23D18B",
        "secondary": "#11A8CD",
        "accent": "#D670D6",
        "highlight": "#E5E510",
        "error": "#CD3131",
        "success": "#23D18B",
        "banner_style": "bold #23D18B",
        "banner_subtitle": "#E5E5E5",
        # Panel borders
        "border_header": "#0DBC79",
        "border_progress": "#11A8CD",
        "border_messages": "#2472C8",
        "border_report": "#0DBC79",
        "border_footer": "#666666",
        "border_config": "#23D18B",
        "border_welcome": "#0DBC79",
        # Dashboard text
        "team_style": "#11A8CD",
        "agent_style": "#0DBC79",
        "status_pending": "#E5E510",
        "status_completed": "#23D18B",
        "status_error": "#F14C4C",
        "status_in_progress": "#3B8EEA",
        "time_style": "#29B8DB",
        "type_style": "#23D18B",
        # Welcome box
        "welcome_title": "bold #E5E5E5",
        "welcome_workflow": "#E5E5E5",
        # Questionary (hex colors matching dashboard exactly)
        "menu_selected": "fg:#23D18B noinherit",
        "menu_highlighted": "fg:#23D18B noinherit",
        "menu_pointer": "fg:#23D18B noinherit",
        "menu_separator": "fg:#D670D6",
        "menu_qmark": "fg:#23D18B bold",
        "menu_question": "fg:#23D18B bold",
        "menu_checkbox": "fg:#29B8DB",
        "menu_text": "fg:#29B8DB",
        "menu_accent": "fg:#F5F543 noinherit",
        "menu_accent2": "fg:#D670D6 noinherit",
        "menu_confirm": "fg:#F14C4C",
    },
}

_PREFS_DIR = Path.home() / ".cybernetic"
_PREFS_PATH = _PREFS_DIR / "preferences.json"
_LEGACY_PREFS_PATH = Path.home() / ".oraculo" / "preferences.json"
_current_theme: str | None = None


def _migrate_legacy_prefs() -> None:
    """Auto-migrate ~/.oraculo/preferences.json → ~/.cybernetic/preferences.json."""
    if not _PREFS_PATH.exists() and _LEGACY_PREFS_PATH.exists():
        _PREFS_DIR.mkdir(parents=True, exist_ok=True)
        _LEGACY_PREFS_PATH.rename(_PREFS_PATH)


def load_prefs() -> dict:
    """Load user preferences from ~/.cybernetic/preferences.json."""
    _migrate_legacy_prefs()
    if _PREFS_PATH.exists():
        try:
            return json.loads(_PREFS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


# Keep private alias for internal use
_load_prefs = load_prefs


def save_prefs(prefs: dict):
    """Save user preferences to ~/.cybernetic/preferences.json."""
    _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PREFS_PATH.write_text(json.dumps(prefs, indent=2))


def get_theme_name() -> str:
    """Get the current theme name."""
    global _current_theme
    if _current_theme is None:
        prefs = _load_prefs()
        _current_theme = prefs.get("theme", "vscode")
    return _current_theme


def set_theme(name: str):
    """Set and persist the theme."""
    global _current_theme
    if name not in THEMES:
        raise ValueError(f"Unknown theme: {name}")
    _current_theme = name
    prefs = _load_prefs()
    prefs["theme"] = name
    save_prefs(prefs)


def t(key: str) -> str:
    """Get a theme value by key. Shorthand for quick access."""
    theme = THEMES[get_theme_name()]
    return theme.get(key, "white")
