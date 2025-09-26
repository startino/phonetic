#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="simple-whisper.service"
UNIT_SRC="$(dirname "$0")/contrib/systemd/$SERVICE_NAME"
UNIT_DST="$HOME/.config/systemd/user/$SERVICE_NAME"

cmd_remove() {
  echo "Stopping and disabling $SERVICE_NAME..."
  systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
  if [ -f "$UNIT_DST" ]; then
    echo "Removing $UNIT_DST"
    rm -f "$UNIT_DST"
  fi
  systemctl --user daemon-reload
  echo "Removed."
}

cmd_status() {
  echo "Status:"
  systemctl --user --no-pager --full status "$SERVICE_NAME" | sed -n '1,25p'
  echo "--- Recent Logs ---"
  journalctl --user -u "$SERVICE_NAME" -n 60 --no-pager || true
}

cmd_upsert() {
  echo "Ensuring unit directory exists..."
  mkdir -p "$HOME/.config/systemd/user"

  if [ ! -f "$UNIT_SRC" ]; then
    echo "ERROR: Unit source not found: $UNIT_SRC" >&2
    exit 1
  fi

  echo "Installing/Updating unit at $UNIT_DST"
  cp -f "$UNIT_SRC" "$UNIT_DST"
  echo "Reloading user units..."
  systemctl --user daemon-reload
  echo "Enabling and starting $SERVICE_NAME..."
  systemctl --user enable --now "$SERVICE_NAME"
  echo "Restarting $SERVICE_NAME to pick up changes..."
  systemctl --user restart "$SERVICE_NAME"
  echo "Status:"
  systemctl --user --no-pager --full status "$SERVICE_NAME" | sed -n '1,25p'
}

case "${1:-}" in
  remove)
    cmd_remove
    ;;
  status)
    cmd_status
    ;;
  ""|upsert|restart|start)
    cmd_upsert
    ;;
  *)
    echo "Usage: $(basename "$0") [remove|status]" >&2
    exit 2
    ;;
esac


