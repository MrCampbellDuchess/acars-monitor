#!/bin/bash
# Install acars-monitor onto a Raspberry Pi running Raspberry Pi OS (64-bit).
# Must be run from the repo root. Requires acarsdec already built and installed
# at /usr/local/bin/acarsdec — see README for build instructions.

set -e

INSTALL_USER="${SUDO_USER:-pi}"

echo "==> Installing Python dependencies"
pip3 install flask psutil

echo "==> Creating log directory"
mkdir -p /home/"$INSTALL_USER"/acars_logs

echo "==> Installing scripts to /usr/local/bin"
install -m 755 acars-web.py        /usr/local/bin/acars-web.py
install -m 755 acarsdec-wrapper.sh /usr/local/bin/acarsdec-wrapper.sh
install -m 755 acars-stats.sh      /usr/local/bin/acars-stats.sh

echo "==> Installing systemd units"
install -m 644 systemd/acarsdec.service         /etc/systemd/system/
install -m 644 systemd/acars-web.service        /etc/systemd/system/
install -m 644 systemd/acars-stats.service      /etc/systemd/system/
install -m 644 systemd/acars-stats.timer        /etc/systemd/system/
install -m 644 systemd/acarsdec-restart.service /etc/systemd/system/
install -m 644 systemd/acarsdec-restart.timer   /etc/systemd/system/

echo "==> Reloading systemd and enabling services"
systemctl daemon-reload
systemctl enable --now acarsdec.service
systemctl enable --now acars-web.service
systemctl enable --now acars-stats.timer
systemctl enable --now acarsdec-restart.timer

echo ""
echo "Done. Dashboard is at http://$(hostname -I | awk '{print $1}'):8080"
