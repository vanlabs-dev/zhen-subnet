<div align="center">

<img src="assets/logo.png" alt="Zhen" width="400">

**The calibration layer for digital twins on Bittensor**

*Decentralized digital twin calibration. Miners optimize simulation parameters against reality. Truth wins.*

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status: Testnet](https://img.shields.io/badge/status-testnet-blue.svg)]()

---

</div>

## Status

Testnet live on Bittensor subnet 456. Comprehensive unit + integration test suite.

**Milestones proven:**
- Two-model architecture (Milestone 1, 2026-04-14)
- Competitive differentiation with 4 miners (Milestone 2, 2026-04-14)
- Test case rotation across BOPTEST cases (Milestone 3, 2026-04-15; active rotation trimmed to 2 cases pending RC model cooling support, see [docs/ROADMAP.md](docs/ROADMAP.md))

**Infrastructure hardened:** weight processing, health endpoint, SQLite-backed score persistence, graceful shutdown, webhook alerting, anti-gaming verification. Mechanism hardening is still in progress; see the [Roadmap](docs/ROADMAP.md) for open audit findings.

## How It Works

Zhen uses a two-model architecture. Validators run a complex emulator (BOPTEST/EnergyPlus) to generate ground truth data, then challenge miners to calibrate a simplified RC network model against that data. Miners use Bayesian optimization to find parameters that minimize the gap between the simplified model and reality. Validators score submissions on held-out test data using ASHRAE metrics (CVRMSE, NMBE, R-squared) and set weights on-chain via Yuma Consensus.

The platform is domain-agnostic. The first vertical is building energy simulation. The active manifest rotates between two BOPTEST cases (bestest_hydronic_heat_pump, bestest_hydronic) selected deterministically per round via SHA-256 hashing. A third case (bestest_air) is staged in the registry and returns when the RC model gains cooling support (see [docs/ROADMAP.md](docs/ROADMAP.md)).

## Quick Links

- [Roadmap: target markets, three-phase plan, open findings](docs/ROADMAP.md)
- [Mining guide](docs/MINE.md)
- [Scoring formula](docs/SCORING.md)
- [Validator setup](docs/VALIDATE.md)
- [Subnet rules](docs/RULES.md)

## Development

Requires Python 3.10+, uv, Docker.

```bash
git clone https://github.com/vanlabs-dev/zhen-subnet.git
cd zhen-subnet
uv sync --all-groups
uv run pytest
```

## Docker Deployment

```bash
# Miner
docker compose --profile miner up -d

# Validator
docker compose --profile validator up -d
```

See [docs/MINE.md](docs/MINE.md) and [docs/VALIDATE.md](docs/VALIDATE.md) for full setup guides.

## Validator weight version coordination

All Zhen validators must use the same `WEIGHT_VERSION_KEY` from
`protocol/__init__.py`. This value is NOT the subnet registration key
and is NOT the internal spec version. It is a coordination constant
used by Bittensor's Yuma consensus to aggregate validator weight
vectors correctly.

Current value: `1000`. If this ever changes, all validators must
update within the same epoch to avoid weight desynchronization.

## License

MIT
