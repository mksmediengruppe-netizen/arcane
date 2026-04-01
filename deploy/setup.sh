#!/bin/bash
# ARCANE Setup Script
# Domain: arcaneai.ru
# Server: 2.56.240.170

set -e

echo "============================================"
echo "  ARCANE Setup — arcaneai.ru"
echo "  Autonomous Runtime for Code, Automation,"
echo "  Networking & Engineering"
echo "============================================"

ARCANE_DIR="/root/arcane"
cd "$ARCANE_DIR"

# 1. System dependencies
echo "[1/8] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    python3.11 python3.11-venv python3-pip \
    nodejs npm \
    nginx certbot python3-certbot-nginx \
    postgresql postgresql-contrib \
    redis-server \
    sshpass rsync git curl wget \
    build-essential libffi-dev libssl-dev \
    > /dev/null 2>&1

npm install -g pm2 pnpm > /dev/null 2>&1

echo "  Done: System dependencies"

# 2. Python virtual environment
echo "[2/8] Setting up Python environment..."
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1

# Install Playwright
pip install playwright > /dev/null 2>&1
playwright install chromium --with-deps > /dev/null 2>&1

echo "  Done: Python environment"

# 2.5. Backup existing database before any changes
echo "[BACKUP] Creating database backup before setup..."
BACKUP_DIR="/root/arcane/backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
if command -v pg_dump &> /dev/null && sudo -u postgres psql -lqt 2>/dev/null | grep -qw arcane; then
    sudo -u postgres pg_dump arcane > "$BACKUP_DIR/arcane_pre_setup_${TIMESTAMP}.sql" 2>/dev/null && \
        echo "  Done: Database backup saved to $BACKUP_DIR/arcane_pre_setup_${TIMESTAMP}.sql" || \
        echo "  SKIP: pg_dump failed (database may not exist yet)"
    # Keep only last 5 backups
    ls -t "$BACKUP_DIR"/arcane_pre_setup_*.sql 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null
else
    echo "  SKIP: No existing database to backup"
fi

# 3. PostgreSQL setup
echo "[3/8] Configuring PostgreSQL..."
sudo -u postgres psql -c "CREATE USER arcane WITH PASSWORD 'arcane_secret';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE arcane OWNER arcane;" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE arcane TO arcane;" 2>/dev/null || true
systemctl enable postgresql
systemctl start postgresql
echo "  Done: PostgreSQL"

# 4. Redis setup
echo "[4/8] Configuring Redis..."
systemctl enable redis-server
systemctl start redis-server
echo "  Done: Redis"

# 5. Create .env if not exists
echo "[5/8] Checking configuration..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  WARNING: Created .env from example. Edit /root/arcane/.env with your API keys!"
else
    echo "  Done: .env exists"
fi

# 6. Create workspace directories
echo "[6/8] Creating workspace..."
mkdir -p /root/workspace/{screenshots,uploads,projects,sandbox}
mkdir -p /var/log/arcane
echo "  Done: Workspace"

# 7. Systemd service
echo "[7/8] Installing systemd service..."
cp deploy/arcane.service /etc/systemd/system/arcane.service
systemctl daemon-reload
systemctl enable arcane
echo "  Done: Systemd service"

# 8. Nginx + SSL
echo "[8/8] Configuring Nginx for arcaneai.ru..."
cp deploy/nginx.conf /etc/nginx/sites-available/arcane
ln -sf /etc/nginx/sites-available/arcane /etc/nginx/sites-enabled/arcane
rm -f /etc/nginx/sites-enabled/default

# Test nginx config (without SSL first — certs may not exist yet)
# Create a temporary HTTP-only config for certbot
cat > /etc/nginx/sites-available/arcane-temp << 'EOF'
server {
    listen 80;
    server_name arcaneai.ru www.arcaneai.ru;
    root /root/arcane/frontend/dist;
    location / { try_files $uri $uri/ /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:8900; }
}
EOF
ln -sf /etc/nginx/sites-available/arcane-temp /etc/nginx/sites-enabled/arcane
nginx -t && systemctl reload nginx

# Get SSL certificate
certbot --nginx -d arcaneai.ru -d www.arcaneai.ru --non-interactive --agree-tos --email admin@arcaneai.ru 2>/dev/null || echo "  SSL: Run manually — certbot --nginx -d arcaneai.ru"

# Now apply full config with SSL
cp deploy/nginx.conf /etc/nginx/sites-available/arcane
ln -sf /etc/nginx/sites-available/arcane /etc/nginx/sites-enabled/arcane
rm -f /etc/nginx/sites-available/arcane-temp
nginx -t && systemctl reload nginx
echo "  Done: Nginx + SSL"

echo ""
echo "============================================"
echo "  ARCANE Setup Complete!"
echo "============================================"
echo ""
echo "  Domain:  https://arcaneai.ru"
echo "  API:     https://arcaneai.ru/api/health"
echo "  Start:   systemctl start arcane"
echo "  Status:  systemctl status arcane"
echo "  Logs:    journalctl -u arcane -f"
echo ""
