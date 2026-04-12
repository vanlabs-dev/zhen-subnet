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

**Competitive Simulation Calibration on Bittensor**

*Miners calibrate building energy digital twins. Validators verify with ASHRAE metrics. Truth wins.*

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status: Active Development](https://img.shields.io/badge/status-active--development-blue.svg)]()

---

</div>

## Status

Active development. Core implementation complete (Phases 0-5).

- RC network thermal model
- ASHRAE scoring engine (CVRMSE, NMBE, R-squared)
- BOPTEST emulator integration
- Validator round orchestration with parallel verification
- Reference miner with Bayesian optimization
- Bittensor synapse protocol

73 tests passing. Testnet deployment next.

## Documentation

- [Mechanism Design](docs/MECHANISM.md) - what the subnet does and why
- [Technical Architecture](docs/ARCHITECTURE.md) - how it works
- [Implementation Plan](docs/IMPLEMENTATION.md) - phased build plan

## Quick Links

- Mining guide: coming soon (docs/MINE.md)
- Scoring formula: coming soon (docs/SCORING.md)
- Validator setup: coming soon (docs/VALIDATE.md)

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
