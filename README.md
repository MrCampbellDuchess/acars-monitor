# acars-monitor

A Raspberry Pi ACARS receiver and web dashboard. Decodes VHF ACARS messages from commercial aircraft using a cheap RTL-SDR dongle and displays them in a real-time browser dashboard with live position tracking on an OpenStreetMap map.

## Features

- **Live message waterfall** — decoded ACARS messages with flight ID, registration, label, signal level, and error indicators
- **Position map** — aircraft plotted on an interactive map using ADS-C position reports; tracks persist for 24 hours
- **Bearing arrows** — heading indicator on each aircraft marker when true heading is included in the message
- **Aircraft table** — every aircraft heard today, sortable by last seen or message count
- **System bar** — live CPU, load average, and RAM usage
- **Audio ping** — soft tone on each new message
- **Log download** — one-click download of today's raw ACARS log

## Hardware

- Raspberry Pi (tested on Pi 4 and Pi 5, 64-bit OS)
- RTL-SDR dongle (RTL2832U-based, e.g. RTL-SDR Blog V3)
- Antenna suitable for 129–132 MHz VHF (a simple quarter-wave vertical works well)

## Dependencies

### System packages

```bash
sudo apt install python3-pip cmake pkg-config librtlsdr-dev libusb-1.0-0-dev
```

### Python packages

```bash
pip3 install flask psutil
```

### acarsdec

This project uses [acarsdec](https://github.com/TLeconte/acarsdec) as the decoder. Build and install it first:

```bash
# Install libacars for ARINC-622 message decoding (ADS-C position reports etc.)
git clone https://github.com/szpajder/libacars.git
cd libacars && mkdir build && cd build
cmake .. && make && sudo make install && sudo ldconfig
cd ../..

# Build acarsdec
git clone https://github.com/TLeconte/acarsdec.git
cd acarsdec && mkdir build && cd build
cmake .. -Drtl=ON -Dacars=ON && make && sudo make install
```

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/acars-monitor.git
cd acars-monitor
sudo bash install.sh
```

The installer copies scripts to `/usr/local/bin`, installs the six systemd units, and starts everything immediately. The dashboard will be available at `http://<pi-ip>:8080`.

## Configuration

All user-facing settings live in `config.py` (installed to `~/acars_config.py`). Edit it before running `install.sh`, or edit `~/acars_config.py` on the Pi at any time and restart the services.

```python
LOG_DIR       = "/home/pi/acars_logs"   # where logs and CSVs are stored
PORT          = 8080                    # web dashboard port
MAP_CENTER    = [54.45, -122.7]         # initial map view [lat, lon]
MAP_ZOOM      = 7                       # initial zoom level
TRACK_MAX_AGE = 86400                   # seconds to keep tracks (86400 = 24 h)
FREQUENCIES   = ["131.550", "130.025", "129.125", "131.475"]  # MHz
```

After editing `~/acars_config.py`:

```bash
sudo systemctl restart acars-web
```

### Frequencies

Set `FREQUENCIES` in `config.py`. The defaults cover North American ACARS. European operators typically use `["131.725", "129.125", "130.025", "131.550"]`.

You must also update `acarsdec-wrapper.sh` to pass the same frequencies to the decoder — they are listed at the end of the `exec` line.

### RTL-SDR gain and device

Edit `acarsdec-wrapper.sh`:

```bash
-g 40          # gain in dB — adjust for your antenna/location
--rtlsdr 0     # device index if you have multiple dongles
```

## Service management

```bash
# Status
sudo systemctl status acarsdec acars-web acars-stats.timer

# Restart
sudo systemctl restart acarsdec acars-web

# Logs
journalctl -u acarsdec -f
journalctl -u acars-web -f
```

## File layout

```
acars-monitor/
├── config.py               User configuration (installed to ~/acars_config.py)
├── acars-web.py            Flask dashboard (serves port 8080)
├── acarsdec-wrapper.sh     Starts acarsdec with date-stamped log file
├── acars-stats.sh          Hourly stats aggregator (run every 5 min)
├── install.sh              Installer script
├── systemd/
│   ├── acarsdec.service        Decoder service
│   ├── acars-web.service       Dashboard service
│   ├── acars-stats.service     Stats oneshot
│   ├── acars-stats.timer       Runs stats every 5 minutes
│   ├── acarsdec-restart.service  Midnight log-rotation restart
│   └── acarsdec-restart.timer    Triggers restart at 00:00
└── acars_logs/             (runtime — gitignored)
    ├── acars_YYYY-MM-DD.txt    Daily raw message log
    ├── acars_stats.csv         Hourly statistics
    ├── acars_stats_current.csv Current-hour snapshot
    └── acars_aircraft.csv      Aircraft registry
```

## API endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard HTML |
| `GET /api/messages?offset=N` | New messages since byte offset |
| `GET /api/positions` | Aircraft tracks with position fixes (last 24 h) |
| `GET /api/aircraft` | All aircraft seen today |
| `GET /api/stats` | Hourly message and error counts |
| `GET /api/system` | CPU, load, RAM |
| `GET /download/messages` | Today's raw log as a text file |

## How position tracking works

Position data comes from ADS-C messages (ACARS label `B6`) decoded by libacars. Each message body contains latitude, longitude, altitude, and optionally true heading. The dashboard extracts all fixes for each (registration, flight) pair from today's log, sorts them by timestamp, and draws them as a dashed polyline on the map. Tracks older than 24 hours are dropped. The most recent fix carries a direction arrow if a heading was reported.

## License

MIT
