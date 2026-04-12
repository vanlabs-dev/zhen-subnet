# Zhen Subnet - Agent Definitions

Zhen is a decentralized digital twin calibration platform on Bittensor. First vertical: building energy.

| Agent | Scope | Model | Purpose |
|-------|-------|-------|---------|
| validator-agent | validator/ | sonnet | Emulator management, round orchestration, verification, scoring, weight setting |
| miner-agent | miner/ | sonnet | Reference miner, calibration algorithms, simulator interaction |
| protocol-agent | protocol/, scoring/ | sonnet | CalibrationSynapse definition, shared scoring logic, EMA tracker |
| simulation-agent | simulation/ | sonnet | ZhenSimulator interface, RC network backend, simulation determinism |
| infra-agent | registry/, .github/, docker-compose.yml | sonnet | Docker images, CI/CD, manifest management, deployment |
| docs-agent | docs/, README.md, llms.txt | sonnet | Documentation creation and maintenance |

Agent definitions are in `.claude/agents/*.md`
