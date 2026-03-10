#!/usr/bin/env bash
# Na Svetlo — VPS setup script
# Run as root on a fresh Ubuntu 24.04 Hetzner server:
#   bash setup_server.sh
set -euo pipefail

APP_USER="nasvetlo"
APP_DIR="/opt/nasvetlo-mvp"
PYTHON="python3"

echo "==> Installing system packages..."
apt-get update -qq
apt-get install -y python3.11 python3.11-venv python3.11-dev git curl ufw sqlite3

echo "==> Creating app user..."
id "$APP_USER" &>/dev/null || useradd -r -m -s /bin/bash "$APP_USER"

echo "==> Copying project files..."
mkdir -p "$APP_DIR"
cp -r . "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Creating Python virtual environment..."
sudo -u "$APP_USER" bash -c "
  cd $APP_DIR
  $PYTHON -m venv .venv
  .venv/bin/pip install --upgrade pip -q
  .venv/bin/pip install -r requirements.txt -q
"

echo "==> Setting up .env..."
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo ""
  echo "  *** Edit $APP_DIR/.env and fill in your API keys, then re-run: ***"
  echo "      sudo systemctl start nasvetlo nasvetlo-web"
  echo ""
fi

echo "==> Installing systemd service: nasvetlo (pipeline daemon)..."
cat > /etc/systemd/system/nasvetlo.service <<EOF
[Unit]
Description=Na Svetlo — News Pipeline Daemon
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python -m nasvetlo.cli daemon
Restart=on-failure
RestartSec=60
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "==> Installing systemd service: nasvetlo-web (dashboard)..."
cat > /etc/systemd/system/nasvetlo-web.service <<EOF
[Unit]
Description=Na Svetlo — Web Dashboard
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python -m nasvetlo.cli serve --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "==> Configuring firewall..."
ufw allow ssh
ufw allow 80
ufw allow 443
ufw --force enable

echo "==> Enabling services..."
systemctl daemon-reload
systemctl enable nasvetlo nasvetlo-web

echo ""
echo "============================================"
echo " Setup complete!"
echo "============================================"
echo ""
echo " Next steps:"
echo "   1. Edit /opt/nasvetlo-mvp/.env with your API keys"
echo "   2. sudo systemctl start nasvetlo nasvetlo-web"
echo "   3. sudo journalctl -u nasvetlo -f   (watch pipeline logs)"
echo "   4. Dashboard runs at http://$(hostname -I | awk '{print $1}'):8000/dashboard"
echo ""
