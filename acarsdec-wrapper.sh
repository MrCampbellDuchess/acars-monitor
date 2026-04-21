#!/bin/bash
# Wrapper for acarsdec that uses a date-stamped log file
LOG_DIR="/home/pi/acars_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/acars_$(date +%F).txt"

exec /usr/local/bin/acarsdec \
  --output full:file \
  --output "full:file:path=${LOG_FILE}" \
  -g 40 \
  --rtlsdr 0 \
  131.550 130.025 129.125 131.475
