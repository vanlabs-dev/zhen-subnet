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

Active development. Core platform complete (Phases 0-5). Milestone 3 proven.

Zhen is a domain-agnostic calibration platform for digital twins. The first vertical is building energy simulation, with miners calibrating thermal models against BOPTEST emulator ground truth.

**Test case rotation proven:** 3 BOPTEST test cases (bestest_hydronic_heat_pump, bestest_air, bestest_hydronic) with SHA-256 deterministic rotation per round. Different building types expose different calibration challenges, preventing single-strategy dominance.

**Platform (domain-agnostic):**
- Scoring engine (CVRMSE, NMBE, R-squared) for any time-series calibration
- Two-model architecture: complex ground truth vs simplified calibration target
- Parallel verification with deterministic scoring
- Reference miner with Bayesian optimization

**First vertical: building energy**
- RC network thermal models
- BOPTEST emulator integration
- ASHRAE-standard accuracy metrics

Testnet live on Bittensor subnet 456. 77 tests passing.

**Testnet:**
- Subnet 456 live on Bittensor testnet
- Two-model architecture proven (Milestone 1 complete, 2026-04-14)
- Competitive differentiation proven (Milestone 2 complete, 2026-04-14): 4 miners, top miner captured 3x weight of weakest
- Test case rotation proven (Milestone 3 complete, 2026-04-15): 3 BOPTEST test cases, deterministic rotation
- Weights set on-chain via Yuma Consensus

## Documentation

- [Mechanism Design](docs/MECHANISM.md) - what the subnet does and why
- [Technical Architecture](docs/ARCHITECTURE.md) - how it works
- [Implementation Plan](docs/IMPLEMENTATION.md) - phased build plan

## Quick Links

- [Proving roadmap](docs/ROADMAP.md)
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

## License

MIT
