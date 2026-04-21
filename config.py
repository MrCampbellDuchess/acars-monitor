# acars-monitor configuration
# Installed to ~/acars_config.py by install.sh.
# Edit this file before running install.sh, or edit ~/acars_config.py after.

# Directory for daily logs and CSV files
LOG_DIR = "/home/pi/acars_logs"

# Web dashboard port
PORT = 8080

# Default map centre [latitude, longitude] and zoom level.
# The map auto-fits to received position data on first load;
# this only affects the initial empty-map view.
MAP_CENTER = [54.45, -122.7]
MAP_ZOOM = 7

# How long to keep aircraft tracks on the map (seconds).
TRACK_MAX_AGE = 86400  # 86400 = 24 hours

# ACARS VHF frequencies to monitor (MHz).
# Also update acarsdec-wrapper.sh to match.
FREQUENCIES = ["131.550", "130.025", "129.125", "131.475"]
