"""Send CalibrationSynapse challenges to miners via Bittensor Dendrite.

Broadcasts the calibration challenge to all active miners and collects
responses within the tempo timeout window.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Any

if importlib.util.find_spec("bittensor"):
    import bittensor as bt
else:
    bt = None

from protocol.synapse import CalibrationSynapse

logger = logging.getLogger(__name__)


class ChallengeSender:
    """Sends calibration challenges to miners via Bittensor Dendrite."""

    def __init__(self, wallet: Any, dendrite: Any) -> None:
        """Initialize the challenge sender.

        Args:
            wallet: Bittensor wallet instance.
            dendrite: Bittensor dendrite instance for network communication.
        """
        self.wallet = wallet
        self.dendrite = dendrite

    async def send_challenge(
        self,
        miners: list[Any],
        synapse: CalibrationSynapse,
        timeout: float = 600.0,
    ) -> list[CalibrationSynapse]:
        """Send a calibration challenge to all miners and collect responses.

        Args:
            miners: List of miner axon info objects from the metagraph.
            synapse: CalibrationSynapse with challenge fields filled.
            timeout: Maximum seconds to wait for responses.

        Returns:
            List of CalibrationSynapse responses with miner-filled result fields.
            Failed/timed-out responses will have None result fields.
        """
        if not miners:
            logger.warning("No miners to send challenge to")
            return []

        try:
            responses = await self.dendrite(
                axons=miners,
                synapse=synapse,
                timeout=timeout,
                deserialize=False,
            )
            return list(responses)
        except Exception as e:
            logger.error(f"Failed to send challenge: {e}")
            return []
