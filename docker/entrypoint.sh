#!/bin/sh
set -eu

DISPLAY_VALUE="${DISPLAY:-:99}"
VNC_RESOLUTION_VALUE="${VNC_RESOLUTION:-1365x900x24}"
VNC_PORT_VALUE="${VNC_PORT:-5900}"
NOVNC_PORT_VALUE="${NOVNC_PORT:-6080}"

export DISPLAY="$DISPLAY_VALUE"

start_xvfb() {
  Xvfb "$DISPLAY_VALUE" -screen 0 "$VNC_RESOLUTION_VALUE" -ac +extension GLX +render -noreset &
}

start_window_manager() {
  fluxbox >/tmp/fluxbox.log 2>&1 &
}

start_vnc() {
  if [ -n "${VNC_PASSWORD:-}" ]; then
    x11vnc -display "$DISPLAY_VALUE" -forever -shared -rfbport "$VNC_PORT_VALUE" -passwd "$VNC_PASSWORD" >/tmp/x11vnc.log 2>&1 &
  else
    x11vnc -display "$DISPLAY_VALUE" -forever -shared -rfbport "$VNC_PORT_VALUE" -nopw >/tmp/x11vnc.log 2>&1 &
  fi
}

start_novnc() {
  websockify --web=/usr/share/novnc/ "$NOVNC_PORT_VALUE" "127.0.0.1:$VNC_PORT_VALUE" >/tmp/novnc.log 2>&1 &
}

start_xvfb
sleep 0.5
start_window_manager
start_vnc
start_novnc

exec "$@"
