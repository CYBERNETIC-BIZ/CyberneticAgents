#!/usr/bin/env bash
set -e

# Always run from the script's own directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

# --- Helper: print error and exit ---
die() { echo "Error: $*" >&2; exit 1; }

# --- Skip install if already set up and working ---
if [ -x "$VENV_DIR/bin/cybernetic.biz" ]; then
    # Verify the venv's Python still works (breaks after system Python upgrades)
    if "$VENV_DIR/bin/python3" -c "import sys" 2>/dev/null; then
        echo "=== Launching CyberneticAgents... ==="
        echo
        "$VENV_DIR/bin/cybernetic.biz"
        exit 0
    else
        echo "Existing virtual environment is broken. Rebuilding..."
        rm -rf "$VENV_DIR"
    fi
fi

echo "=== CyberneticAgents Installer ==="
echo

# --- Check Python version ---
if ! command -v python3 &>/dev/null; then
    die "python3 is not installed. Please install Python 3.10+ and retry."
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")') \
    || die "Failed to detect Python version."
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    die "Python 3.10+ is required (found $PY_VERSION)."
fi

echo "Found Python $PY_VERSION"

# --- Helper: install system venv package ---
_install_venv_package() {
    echo "python3-venv is not installed. Attempting to install..."

    if ! command -v sudo &>/dev/null; then
        die "sudo is required to install python3-venv but is not available. Please install python${PY_VERSION}-venv manually."
    fi

    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y "python${PY_VERSION}-venv" \
            || die "Failed to install python${PY_VERSION}-venv. Try manually: sudo apt-get install python${PY_VERSION}-venv"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3-virtualenv \
            || die "Failed to install python3-virtualenv."
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm python-virtualenv \
            || die "Failed to install python-virtualenv."
    elif command -v brew &>/dev/null; then
        die "On macOS, venv is included with Python from Homebrew. Try: brew install python3"
    else
        die "Cannot auto-install python3-venv. Please install it for Python $PY_VERSION manually and retry."
    fi
}

# --- Clean up on failure so we don't leave a broken venv ---
cleanup() {
    if [ $? -ne 0 ] && [ -d "$VENV_DIR" ]; then
        echo "Cleaning up incomplete installation..."
        rm -rf "$VENV_DIR"
    fi
}
trap cleanup EXIT

# --- Create virtual environment ---
echo "Creating virtual environment in $VENV_DIR..."
if ! python3 -m venv "$VENV_DIR" 2>/dev/null; then
    rm -rf "$VENV_DIR"
    _install_venv_package
    python3 -m venv "$VENV_DIR" \
        || die "Failed to create virtual environment even after installing python3-venv."
fi

# Sanity check: pip must exist in the venv
[ -x "$VENV_DIR/bin/pip" ] || die "Virtual environment created but pip is missing. Try: sudo apt-get install python${PY_VERSION}-venv"

# --- Install dependencies ---
echo "Installing CyberneticAgents..."
"$VENV_DIR/bin/pip" install --upgrade pip -q \
    || die "Failed to upgrade pip. Check your network connection."
"$VENV_DIR/bin/pip" install -e . -q \
    || die "Failed to install CyberneticAgents. Check the output above for missing system packages (e.g. python${PY_VERSION}-dev, build-essential)."

echo

# --- Symlink into ~/.local/bin ---
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

if [ -x "$VENV_DIR/bin/cybernetic.biz" ]; then
    ln -sf "$SCRIPT_DIR/$VENV_DIR/bin/cybernetic.biz" "$INSTALL_DIR/cybernetic.biz"
else
    echo "Warning: cybernetic.biz entry point not found — skipping symlink."
fi

if ! echo "$PATH" | grep -q "$INSTALL_DIR"; then
    echo "NOTE: Add $INSTALL_DIR to your PATH if not already present:"
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
fi

# If we got here, install succeeded — disarm the cleanup trap
trap - EXIT

echo "=== Installation complete! Launching CyberneticAgents... ==="
echo
"$VENV_DIR/bin/cybernetic.biz"
