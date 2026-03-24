"""Ollama helper: auto-detect local models and ensure the server is running."""
import json
import shutil
import subprocess
import time
import urllib.request
import urllib.error
from typing import List, Tuple, Optional

OLLAMA_API = "http://localhost:11434"


def _format_size(size_bytes: int) -> str:
    """Format byte count to human-readable string."""
    gb = size_bytes / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.1f}GB"
    return f"{size_bytes / (1024 ** 2):.0f}MB"


def is_ollama_installed() -> bool:
    """Check if the ollama binary is available on PATH."""
    return shutil.which("ollama") is not None


def is_ollama_running() -> bool:
    """Check if the Ollama server is responding."""
    try:
        req = urllib.request.Request(f"{OLLAMA_API}/api/tags", method="GET")
        urllib.request.urlopen(req, timeout=3)
        return True
    except (urllib.error.URLError, OSError):
        return False


def start_ollama() -> bool:
    """Start the Ollama server in the background.

    Returns True if server started successfully, False otherwise.
    """
    if is_ollama_running():
        return True

    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False

    # Wait up to 10 seconds for the server to start
    for _ in range(20):
        time.sleep(0.5)
        if is_ollama_running():
            return True

    return False


def ensure_ollama() -> Tuple[bool, str]:
    """Ensure Ollama is installed and running.

    Returns (success, message) tuple.
    """
    if not is_ollama_installed():
        return False, "Ollama is not installed. Install from https://ollama.com"

    if is_ollama_running():
        return True, "Ollama is running"

    started = start_ollama()
    if started:
        return True, "Ollama started automatically"
    return False, "Failed to start Ollama server"


def list_models() -> List[dict]:
    """Fetch the list of locally available Ollama models.

    Returns list of dicts with keys: name, size, parameter_size, family
    """
    try:
        req = urllib.request.Request(f"{OLLAMA_API}/api/tags", method="GET")
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []

    models = []
    for m in data.get("models", []):
        details = m.get("details", {})
        models.append({
            "name": m.get("name", ""),
            "size": m.get("size", 0),
            "parameter_size": details.get("parameter_size", ""),
            "family": details.get("family", ""),
        })
    return models


def get_model_choices() -> List[Tuple[str, str]]:
    """Return (display_label, model_name) tuples for all installed Ollama models.

    Falls back to a manual entry option if no models are found.
    """
    models = list_models()
    if not models:
        return [("No models found — type a model name", "")]

    choices = []
    for m in models:
        size_str = _format_size(m["size"])
        param_str = m["parameter_size"]
        label = f"{m['name']} ({param_str}, {size_str})"
        choices.append((label, m["name"]))

    return choices
