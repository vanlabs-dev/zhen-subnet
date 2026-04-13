<div align="center">

<br>

```
███████╗██╗  ██╗███████╗███╗   ██╗
╚══███╔╝██║  ██║██╔════╝████╗  ██║
  ███╔╝ ███████║█████╗  ██╔██╗ ██║
 ███╔╝  ██╔══██║██╔══╝  ██║╚██╗██║
███████╗██║  ██║███████╗██║ ╚████║
╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝
```

**The calibration layer for digital twins on Bittensor**

*Decentralized digital twin calibration. Miners optimize simulation parameters against reality. Truth wins.*

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status: Active Development](https://img.shields.io/badge/status-active--development-blue.svg)]()

---

</div>

## Status

Active development. Core platform complete (Phases 0-5).

Zhen is a domain-agnostic calibration platform for digital twins. The first vertical is building energy simulation, with miners calibrating thermal models against BOPTEST emulator ground truth.

**Platform (domain-agnostic):**
- Scoring engine (CVRMSE, NMBE, R-squared) for any time-series calibration
- Two-model architecture: complex ground truth vs simplified calibration target
- Parallel verification with deterministic scoring
- Reference miner with Bayesian optimization

**First vertical: building energy**
- RC network thermal models
- BOPTEST emulator integration
- ASHRAE-standard accuracy metrics

Testnet live on Bittensor subnet 456. 82 tests passing.

**Testnet:**
- Subnet 456 live on Bittensor testnet
- First successful calibration round completed (CVRMSE 0.0399)
- Weights set on-chain via Yuma Consensus

## Documentation

- [Mechanism Design](docs/MECHANISM.md) - what the subnet does and why
- [Technical Architecture](docs/ARCHITECTURE.md) - how it works
- [Implementation Plan](docs/IMPLEMENTATION.md) - phased build plan

## Quick Links

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
