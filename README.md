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
- Test case rotation across BOPTEST cases (Milestone 3, 2026-04-15)
- Phase 1 complete: year-round single-zone cooling, rank-based scoring, testnet validated (2026-04-19)

**Infrastructure hardened:** weight processing, health endpoint, SQLite-backed score persistence, graceful shutdown, webhook alerting, anti-gaming verification. See the [Roadmap](docs/ROADMAP.md) for Phase 2 plans and open audit findings.

## How It Works

Zhen uses a two-model architecture. Validators run a complex emulator (BOPTEST/EnergyPlus) to generate ground truth data, then challenge miners to calibrate a simplified RC network model against that data. Miners use Bayesian optimization to find parameters that minimize the gap between the simplified model and reality. Validators score submissions on held-out test data using ASHRAE metrics (CVRMSE, NMBE, R-squared) and set weights on-chain via Yuma Consensus.

The platform is domain-agnostic. The first vertical is building energy simulation. The active test case is bestest_air (Denver, CO, USA climate; four-pipe fan coil unit; 7 calibratable parameters; 3 scoring outputs). Phase 2a aligns outputs with ASHRAE Guideline 14 for small calibration consultancies and M&V practitioners (primary near-term customer); Phase 2b expands to multi-zone commercial buildings for the Commercial HVAC MPC growth market.

BOPTEST test cases are benchmark fixtures, not deployment constraints. Zhen calibrates building simulation models globally. The test case locations (Denver, Brussels, Chicago) are the simulator locations, not where Zhen can deploy. Clients anywhere can use Zhen by providing their own weather data, building description, and measured operational data.

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
