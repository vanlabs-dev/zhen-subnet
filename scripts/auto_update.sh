#!/bin/bash
# Usage: ./scripts/auto_update.sh <pm2_process_name>
# Run alongside your miner/validator for automatic updates.

PM2_PROCESS_NAME=$1
if [ -z "$PM2_PROCESS_NAME" ]; then
    echo "Usage: $0 <pm2_process_name>"
    exit 1
fi

cd "$(dirname "$0")/.."

while true; do
    sleep 300

    LOCAL=$(git rev-parse HEAD)
    git fetch origin main --quiet
    REMOTE=$(git rev-parse origin/main)

    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "$(date): Update detected ($LOCAL -> $REMOTE)"
        git pull --rebase --autostash

        # Reinstall dependencies
        uv sync --all-groups

        # Restart the process
        pm2 restart "$PM2_PROCESS_NAME"
        echo "$(date): Update complete, process restarted"
    fi
done
