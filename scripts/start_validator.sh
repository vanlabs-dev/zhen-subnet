#!/bin/bash
cd "$(dirname "$0")/.."
pm2 start "uv run python -m validator.main --netuid 456 --network test --no-local-mode --boptest-url http://localhost:8000" --name zhen-validator
pm2 start scripts/auto_update.sh --name zhen-auto-update -- zhen-validator
