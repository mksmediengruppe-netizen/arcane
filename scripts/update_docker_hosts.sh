#!/bin/bash
# /root/arcane/scripts/update_docker_hosts.sh
# Auto-update /etc/hosts and .env with current Docker container IPs
# Called by systemd on boot after docker.service

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a /var/log/arcane-dns-fix.log; }

log "=== ARCANE DNS Fix started ==="

# Wait for containers to be running (up to 60 seconds)
for i in $(seq 1 30); do
    if docker ps --format "{{.Names}}" 2>/dev/null | grep -q "postgres-1"; then
        log "Containers are running"
        break
    fi
    log "Waiting for containers... ($i/30)"
    sleep 2
done

# Get IPs
PG_IP=$(docker inspect ai-dev-team-platform-postgres-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null | head -1)
REDIS_IP=$(docker inspect ai-dev-team-platform-redis-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null | head -1)
MINIO_IP=$(docker inspect ai-dev-team-platform-minio-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null | head -1)
QDRANT_IP=$(docker inspect qdrant --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null | head -1)

log "IPs: PG=$PG_IP REDIS=$REDIS_IP MINIO=$MINIO_IP QDRANT=$QDRANT_IP"

# Update /etc/hosts
sed -i '/# ARCANE Docker/d' /etc/hosts
sed -i '/ai-dev-team-platform/d' /etc/hosts
sed -i '/^[0-9.]* qdrant$/d' /etc/hosts
printf "\n# ARCANE Docker services (updated %s)\n%s ai-dev-team-platform-postgres-1\n%s ai-dev-team-platform-redis-1\n%s ai-dev-team-platform-minio-1\n%s qdrant\n" \
    "$(date)" "$PG_IP" "$REDIS_IP" "$MINIO_IP" "$QDRANT_IP" >> /etc/hosts
log "Updated /etc/hosts"

# Update .env
cd /root/arcane
PG_PASS=$(grep POSTGRES_PASSWORD .env | cut -d= -f2)
PG_DB=$(grep POSTGRES_DB .env | cut -d= -f2)
PG_USER=$(grep POSTGRES_USER .env | cut -d= -f2)

sed -i "s|POSTGRES_HOST=.*|POSTGRES_HOST=ai-dev-team-platform-postgres-1|g" .env
sed -i "s|REDIS_HOST=.*|REDIS_HOST=ai-dev-team-platform-redis-1|g" .env
sed -i "s|QDRANT_HOST=.*|QDRANT_HOST=qdrant|g" .env
sed -i "s|QDRANT_URL=.*|QDRANT_URL=http://qdrant:6333|g" .env
sed -i "s|MINIO_ENDPOINT=.*|MINIO_ENDPOINT=ai-dev-team-platform-minio-1:9000|g" .env
sed -i "s|DATABASE_URL=.*|DATABASE_URL=postgresql://${PG_USER}:${PG_PASS}@ai-dev-team-platform-postgres-1:5432/${PG_DB}|g" .env
sed -i "s|MEMORY_DB_URL=.*|MEMORY_DB_URL=postgresql://${PG_USER}:${PG_PASS}@ai-dev-team-platform-postgres-1:5432/${PG_DB}|g" .env
log "Updated .env"

# Wait for services to be ready
sleep 5

# Restart ARCANE
systemctl restart arcane
log "ARCANE restarted"

# Check health after 10 seconds
sleep 10
STATUS=$(curl -s http://localhost:8900/api/health | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'])" 2>/dev/null)
log "ARCANE health: $STATUS"
