#!/usr/bin/env bash
# Code-only redeploy: git pull + docker restart. Use this when you've
# changed Python files in backend/, shared/, or models/ (everything except
# requirements-prod.txt + Dockerfile + apt deps).
#
# The container bind-mounts the host's /opt/resell/app/{backend,shared,models}
# directories, so a git pull immediately changes what the running uvicorn
# process imports. docker restart re-runs the import + lifespan startup so
# the changes take effect.
#
# Run on EC2:
#   /opt/resell/app/scripts/ec2_redeploy.sh
#
# Or from your Mac:
#   ssh -i ~/Downloads/Resell_Copilot.pem ubuntu@13.49.21.29 \
#     '/opt/resell/app/scripts/ec2_redeploy.sh'
#
# When deps change, use ec2_rebuild.sh instead.

set -euo pipefail

cd /opt/resell/app
git pull --ff-only
sudo docker restart resell-backend

echo "Waiting for /health..."
for _ in {1..20}; do
  sleep 1
  if curl -sf http://127.0.0.1:8000/health > /dev/null; then
    echo "Backend healthy."
    exit 0
  fi
done

echo "Backend did not become healthy within 20s. Last logs:"
sudo docker logs --tail 30 resell-backend
exit 1
