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
[![Status: Pre-development](https://img.shields.io/badge/status-pre--development-orange.svg)]()

---

</div>

## Status

Pre-development. Design documents complete.

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
