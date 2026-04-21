#!/bin/bash
# Calculates ACARS message stats and writes to CSV
# Run every 5 minutes via systemd timer

LOG_DIR="/home/pi/acars_logs"
STATS_FILE="${LOG_DIR}/acars_stats.csv"
TODAY=$(date +%F)
LOG_FILE="${LOG_DIR}/acars_${TODAY}.txt"

# Create CSV header if file doesn't exist
if [ ! -f "$STATS_FILE" ]; then
    echo "timestamp,date,hour,message_count,error_count,error_rate" > "$STATS_FILE"
fi

# Exit if no log file for today yet
if [ ! -f "$LOG_FILE" ]; then
    exit 0
fi

# Parse all message headers from today's log
# Format: [#1 (F:131.550 L:-34.2/-44.0 E:0) 06/04/2026 21:48:35.760 ----
# Extract hour and error count from each message header
NOW=$(date +"%Y-%m-%d %H:%M:%S")

# Get stats per hour from today's log
grep -oP '\(F:[^ ]+ L:[^ ]+ E:(\d+)\) \d{2}/\d{2}/\d{4} (\d{2}):\d{2}:\d{2}' "$LOG_FILE" | \
    awk -F'[E:) ]' '{
        # Extract error value and hour
        for(i=1;i<=NF;i++) {
            if($(i-1)=="E:" || (i>1 && $(i-1)~/:$/)) {}
        }
    }' > /dev/null 2>&1

# Simpler approach: extract E:value and hour directly
declare -A msg_count
declare -A err_count

while IFS= read -r line; do
    # Extract error count (E:N)
    error=$(echo "$line" | grep -oP 'E:\K\d+')
    # Extract hour from timestamp
    hour=$(echo "$line" | grep -oP '\d{2}/\d{2}/\d{4} \K\d{2}')

    if [ -n "$hour" ] && [ -n "$error" ]; then
        msg_count[$hour]=$(( ${msg_count[$hour]:-0} + 1 ))
        if [ "$error" -gt 0 ]; then
            err_count[$hour]=$(( ${err_count[$hour]:-0} + 1 ))
        fi
    fi
done < <(grep -P '^\[#\d+' "$LOG_FILE")

# Write stats for each hour that has data
# Use a temp file to track what we've already written today
WRITTEN_FILE="${LOG_DIR}/.stats_written_${TODAY}"
touch "$WRITTEN_FILE"

CURRENT_HOUR=$(date +%H)

for hour in $(echo "${!msg_count[@]}" | tr ' ' '\n' | sort); do
    msgs=${msg_count[$hour]}
    errs=${err_count[$hour]:-0}

    if [ "$msgs" -gt 0 ]; then
        rate=$(awk "BEGIN {printf \"%.2f\", ($errs / $msgs) * 100}")
    else
        rate="0.00"
    fi

    # Check if we already wrote a final entry for this completed hour
    if [ "$hour" != "$CURRENT_HOUR" ]; then
        # Completed hour - write final entry if not already written
        if ! grep -q "^${hour}$" "$WRITTEN_FILE" 2>/dev/null; then
            echo "${NOW},${TODAY},${hour},${msgs},${errs},${rate}" >> "$STATS_FILE"
            echo "$hour" >> "$WRITTEN_FILE"
        fi
    fi
done

# Always write/update the current hour snapshot to a separate file
if [ -n "${msg_count[$CURRENT_HOUR]}" ]; then
    msgs=${msg_count[$CURRENT_HOUR]}
    errs=${err_count[$CURRENT_HOUR]:-0}
    if [ "$msgs" -gt 0 ]; then
        rate=$(awk "BEGIN {printf \"%.2f\", ($errs / $msgs) * 100}")
    else
        rate="0.00"
    fi
    echo "${NOW},${TODAY},${CURRENT_HOUR},${msgs},${errs},${rate}" > "${LOG_DIR}/acars_stats_current.csv"
fi
