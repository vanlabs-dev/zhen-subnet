#!/bin/bash
cd "$(dirname "$0")/.."
WALLET_NAME=${1:-zhen-miner}
AXON_PORT=${2:-8091}
pm2 start "uv run python -m miner.main --netuid 456 --network test --wallet-name $WALLET_NAME --axon-port $AXON_PORT" --name zhen-miner
pm2 start scripts/auto_update.sh --name zhen-auto-update -- zhen-miner
