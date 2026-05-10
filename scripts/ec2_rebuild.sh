#!/usr/bin/env bash
# Full rebuild + container recreation. Use this only when:
#   - requirements-prod.txt changed (new pip dep)
#   - Dockerfile changed (new apt dep, base image bump, etc.)
#   - First-time setup or full reset
#
# For code-only changes (Python files in backend/, shared/, models/),
# use ec2_redeploy.sh — it's ~5 minutes faster.
#
# This script is the single source of truth for the canonical
# `docker run` flag set. Future changes to mounts/env should be made here.
#
# Run on EC2:
#   /opt/resell/app/scripts/ec2_rebuild.sh
#
# Or from your Mac:
#   ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29 \
#     '/opt/resell/app/scripts/ec2_rebuild.sh'

set -euo pipefail

cd /opt/resell/app
git pull --ff-only

# The /opt/resell/checkpoints bind needs a mountpoint inside the
# /opt/resell/app/models read-only mount. The host's models/ dir doesn't
# include a checkpoints/ subdir (gitignored .pt files), so create it
# empty so Docker has somewhere to attach the inner mount.
mkdir -p /opt/resell/app/models/checkpoints

echo "Building image..."
sudo docker build -t resell-backend .

echo "Recreating container..."
sudo docker rm -f resell-backend 2>/dev/null || true
sudo docker run -d \
  --name resell-backend \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  --env-file /opt/resell/app/.env.prod \
  -v /opt/resell/app/backend:/app/backend:ro \
  -v /opt/resell/app/shared:/app/shared:ro \
  -v /opt/resell/app/models:/app/models:ro \
  -v /opt/resell/data:/app/data \
  -v /opt/resell/checkpoints:/app/models/checkpoints:ro \
  resell-backend

echo "Waiting for /health (up to 120s — first start may pull DINOv2 weights)..."
for _ in {1..60}; do
  sleep 2
  if curl -sf http://127.0.0.1:8000/health > /dev/null; then
    echo "Backend healthy."
    exit 0
  fi
done

echo "Backend did not become healthy within 120s. Last logs:"
sudo docker logs --tail 50 resell-backend
exit 1
