#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
[[ $(uname -m) == aarch64 ]] || { echo 'Use a 64-bit ARM OS on the Pi 5.'; exit 1; }
docker compose version
[[ -f .env ]] || { echo 'Copy .env.example to .env and set a unique password of at least 16 characters.'; exit 1; }
docker compose config --quiet
if [[ ${1:-} == --hardware ]]; then
  if ! grep -q '^RS485_DEVICE=/dev/' .env; then echo 'Set RS485_DEVICE in .env.'; exit 1; fi
  device=$(sed -n 's/^RS485_DEVICE=//p' .env | tail -1)
  [[ -c "$device" ]] || { echo "RS485 serial device is missing: $device"; exit 1; }
  [[ -S /var/run/systemd/journal/socket ]] || { echo 'Expected systemd journal socket is unavailable.'; exit 1; }
  [[ -d /var/log/journal ]] || { echo 'Expected journal directory is unavailable; configure persistent journald first.'; exit 1; }
fi
printf '%s\n' 'Preflight passed. Hardware compatibility and wiring still require verification.'
