#!/bin/bash
set -euo pipefail

MODE="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
MODE_FILE="$PROJECT_DIR/.claude/.mode"
LOG_FILE="$PROJECT_DIR/.claude/action_log.md"

if [[ "$MODE" != "autonomous" && "$MODE" != "focused" ]]; then
    echo "Usage: bash scripts/set_mode.sh [autonomous|focused]"
    echo ""
    echo "  autonomous  Broad permissions, no logging. Claude works uninterrupted."
    echo "  focused     Action log written to .claude/action_log.md each tool use."
    exit 1
fi

echo "$MODE" > "$MODE_FILE"

if [[ "$MODE" == "focused" ]]; then
    {
        echo "# Claude Action Log"
        echo ""
        echo "Session started: $(date '+%Y-%m-%d %H:%M:%S')"
        echo ""
    } > "$LOG_FILE"
    echo "Mode: focused — action log reset at $LOG_FILE"
    echo "Note: restart Claude Code for hook changes to take effect if session is active."
else
    echo "Mode: autonomous — no action logging."
fi
