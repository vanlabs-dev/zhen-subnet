"""Validator entry point and Bittensor neuron lifecycle management."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import logging
import os
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_fixed

if importlib.util.find_spec("bittensor"):
    import bittensor as bt
else:
    bt = None

import protocol
from protocol.synapse import CalibrationSynapse
from validator.alerts import WebhookAlerter
from validator.health import HealthServer
from validator.network.challenge_sender import ChallengeSender
from validator.network.result_receiver import ResponseParser
from validator.registry.manifest import ManifestLoader
from validator.round import split_generator, test_case_selector
from validator.round.orchestrator import RoundOrchestrator
from validator.scoring.engine import ScoringEngine
from validator.scoring.window_ema import compute_window_ema
from validator.scoring_db import ScoringDB
from validator.utils.logging import setup_logging
from validator.verification.engine import VerificationEngine
from validator.weights.setter import WeightSetter

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "registry" / "manifest.json"
DEFAULT_NETUID = int(os.environ.get("ZHEN_NETUID", "456"))
DEFAULT_NETWORK = os.environ.get("ZHEN_NETWORK", "test")
BLOCK_TIME_SECONDS = 12
CHALLENGE_TIMEOUT_SECONDS = 600  # 10 minutes, sufficient for n_calls=500
CHAIN_READ_TIMEOUT_SECONDS: float = 30.0
METAGRAPH_SYNC_TIMEOUT_SECONDS: float = 60.0

WEIGHT_COMMIT_WATCHDOG_SECONDS: float = 180.0
"""If a weight commit has been in flight longer than this, the watchdog
concludes it has hung inside the SDK and exits the process via os._exit(1).
Set above WEIGHT_TIMEOUT_SECONDS (120s in WeightSetter) so this is a true
backstop, not a duplicate of the setter's own timeout."""

SHUTDOWN_GRACE_SECONDS: float = 5.0
"""Time between first Ctrl-C (graceful) and second Ctrl-C (force-exit).
If the validator hasn't shut down naturally in this window, the next
SIGINT bypasses asyncio entirely via os._exit(0)."""

DEFAULT_CHALLENGE_INTERVAL_SECONDS = 900
DEFAULT_WEIGHT_CHECK_INTERVAL_SECONDS = 60
DEFAULT_CLEANUP_INTERVAL_SECONDS = 86400
DEFAULT_CLEANUP_RETENTION_HOURS = 168


class ZhenValidator:
    """Zhen subnet validator. Runs calibration rounds and sets weights.

    Operates in local mode (RC model as ground truth) for testnet, or
    BOPTEST mode for production ground truth generation. Three concurrent
    asyncio loops decouple challenge cadence, weight commit cadence
    (block-gated), and DB cleanup.

    Chain-call invariant: all calls to ``self.subtensor.*`` and
    ``self.metagraph.sync()`` after ``__init__`` MUST go through
    ``self._chain_op()``. Direct chain calls are forbidden outside
    ``__init__`` and ``_chain_op`` itself. This invariant exists because
    the shared substrate websocket connection raises ``ConcurrencyError``
    when two threads call ``recv()`` concurrently; ``_chain_op``
    serializes access via ``self._subtensor_lock``. It is also the
    migration seam for a future ``AsyncSubtensor`` switch.
    """

    def __init__(
        self,
        netuid: int = DEFAULT_NETUID,
        network: str = DEFAULT_NETWORK,
        wallet_name: str = "zhen-validator",
        wallet_hotkey: str = "default",
        local_mode: bool = True,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
        boptest_url: str = "http://localhost:8000",
        health_port: int = 8080,
        challenge_interval_seconds: float = DEFAULT_CHALLENGE_INTERVAL_SECONDS,
        weight_check_interval_seconds: float = DEFAULT_WEIGHT_CHECK_INTERVAL_SECONDS,
        cleanup_interval_seconds: float = DEFAULT_CLEANUP_INTERVAL_SECONDS,
        cleanup_retention_hours: int = DEFAULT_CLEANUP_RETENTION_HOURS,
    ) -> None:
        """Initialize the validator neuron.

        Args:
            netuid: Subnet UID on the chain.
            network: Network name (test, finney, or ws:// URL).
            wallet_name: Bittensor wallet name.
            wallet_hotkey: Bittensor wallet hotkey name.
            local_mode: Use RC model as ground truth (no BOPTEST needed).
            manifest_path: Path to manifest.json.
            boptest_url: BOPTEST service URL for non-local ground truth.
            health_port: Port for the HTTP health check endpoint.
            challenge_interval_seconds: Seconds between challenge rounds.
            weight_check_interval_seconds: Polling cadence for block-gated weight commits.
            cleanup_interval_seconds: Seconds between DB cleanup runs.
            cleanup_retention_hours: Hours of history the DB retains.
        """
        self.netuid = netuid
        self.network = network
        self.local_mode = local_mode
        self.boptest_url = boptest_url
        self.challenge_interval_seconds = challenge_interval_seconds
        self.weight_check_interval_seconds = weight_check_interval_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.cleanup_retention_hours = cleanup_retention_hours

        # Refuse local mode on mainnet (RC defaults as ground truth are trivially gameable)
        if self.local_mode and self.network in ("finney", "main"):
            raise ValueError(
                "Local mode is not allowed on mainnet. Use --no-local-mode with a running BOPTEST service."
            )

        # Load manifest
        loader = ManifestLoader()
        self.manifest = loader.load(manifest_path)

        # Core components
        boptest = None if local_mode else boptest_url
        self.orchestrator = RoundOrchestrator(manifest_path=manifest_path, boptest_url=boptest)
        self.scoring_engine = ScoringEngine()
        self.scoring_db = ScoringDB()
        self.ema_alpha = 0.3
        self.scoring_window_hours = 72
        self.verification_engine = VerificationEngine()
        self.response_parser = ResponseParser()
        self.health = HealthServer(port=health_port)
        self.alerter = WebhookAlerter(webhook_url=os.environ.get("ZHEN_ALERT_WEBHOOK"))
        self.round_count = self.scoring_db.get_round_count()
        if self.round_count > 0:
            logger.info(f"Resuming from round_count={self.round_count} (persisted)")
        self._shutdown: asyncio.Event = asyncio.Event()
        self._subtensor_lock: asyncio.Lock = asyncio.Lock()
        self._last_gated_log_time: float = 0.0
        self._weight_commit_started_at: float | None = None
        """time.monotonic() when a weight commit entered the setter, or None
        if no commit is currently in flight. Watched by _weight_commit_watchdog."""
        self._first_shutdown_at: float | None = None
        """time.monotonic() when the first SIGINT/SIGTERM arrived, or None.
        A second signal arriving more than SHUTDOWN_GRACE_SECONDS later forces
        os._exit(0)."""

        # Bittensor components
        self.wallet: Any = None
        self.subtensor: Any = None
        self.dendrite: Any = None
        self.metagraph: Any = None
        self.challenge_sender: ChallengeSender | None = None
        self.weight_setter: WeightSetter | None = None
        self.my_uid: int | None = None

        if bt is not None:
            self._init_bittensor(wallet_name, wallet_hotkey)

    def _init_bittensor(self, wallet_name: str, wallet_hotkey: str) -> None:
        """Initialize Bittensor SDK v10 components."""
        logger.info(f"Connecting to {self.network} (netuid={self.netuid})")

        self.wallet = bt.Wallet(name=wallet_name, hotkey=wallet_hotkey)
        self.subtensor = bt.Subtensor(network=self.network)
        self.dendrite = bt.Dendrite(wallet=self.wallet)
        # Sync context during init; _chain_op unavailable until the event loop runs.
        # This call is sequential with nothing else, so no race concern.
        self.metagraph = self.subtensor.metagraph(netuid=self.netuid)
        self.challenge_sender = ChallengeSender(self.wallet, self.dendrite)
        self.weight_setter = WeightSetter(
            self.subtensor,
            self.wallet,
            self.netuid,
            metagraph=self.metagraph,
            chain_op=self._chain_op,
        )

        # Find our UID in the metagraph
        my_hotkey = self.wallet.hotkey.ss58_address
        for neuron in self.metagraph.neurons:
            if neuron.hotkey == my_hotkey:
                self.my_uid = neuron.uid
                break

        logger.info(f"Wallet: {wallet_name}/{wallet_hotkey}")
        logger.info(f"Hotkey: {my_hotkey}")
        logger.info(f"My UID: {self.my_uid}")
        logger.info(f"Neurons in metagraph: {len(self.metagraph.neurons)}")

    def _summarize_signal(self, data: dict[str, list[float]]) -> str:
        """Produce a one-line summary of training data signal characteristics.

        For each output variable, reports mean, std, and fraction of zero
        (or near-zero) samples. A high zero-fraction on the energy output
        indicates the test period has no HVAC signal (summer for a
        heating-only test case), which is known to produce dead-zone
        CVRMSE scores under the current RC model.
        """
        import math

        segments = []
        for name, values in data.items():
            if not values:
                segments.append(f"{name}: empty")
                continue
            n = len(values)
            mean = sum(values) / n
            variance = sum((v - mean) ** 2 for v in values) / n
            std = math.sqrt(variance)
            zero_fraction = sum(1 for v in values if abs(v) < 1e-6) / n
            segments.append(f"{name} mean={mean:.3f} std={std:.3f} zero_frac={zero_fraction:.2f}")
        return "; ".join(segments)

    def _format_params_for_log(self, params: dict[str, float]) -> str:
        """Format a miner's calibrated params as JSON for a single log line."""
        rounded = {k: round(float(v), 4) for k, v in params.items()}
        return json.dumps(rounded)

    def _get_miner_axons(self) -> tuple[list[Any], list[int]]:
        """Get axon info for all miners (excluding self).

        Returns:
            Tuple of (axon_list, uid_list) for miners to query.
        """
        if self.metagraph is None:
            return [], []

        axons = []
        uids = []
        my_hotkey = self.wallet.hotkey.ss58_address if self.wallet else None

        for neuron in self.metagraph.neurons:
            # Skip ourselves
            if neuron.hotkey == my_hotkey:
                continue
            # Skip neurons without a serving axon
            if neuron.axon_info.ip == "0.0.0.0" or neuron.axon_info.port == 0:
                continue
            axons.append(neuron.axon_info)
            uids.append(neuron.uid)

        return axons, uids

    async def _wait_for_boptest(self) -> bool:
        """Poll BOPTEST /testcases endpoint until the service is ready.

        Retries every 10 seconds for up to 10 minutes. Handles the
        MinIO bucket race condition where the web container crashes
        on first startup and needs a restart.

        Returns:
            True if the service responded, False if all retries exhausted.
        """
        import httpx

        max_retries = 60
        retry_interval = 10
        url = f"{self.boptest_url}/testcases"

        logger.info(f"Waiting for BOPTEST service at {self.boptest_url}...")
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url)
                if resp.status_code < 400:
                    data = resp.json()
                    n_cases = len(data) if isinstance(data, list) else 0
                    logger.info(f"BOPTEST service ready ({n_cases} test cases available)")
                    return True
            except Exception:
                pass

            if attempt < max_retries:
                logger.info(f"  BOPTEST not ready (attempt {attempt}/{max_retries}), retrying in {retry_interval}s...")
                await asyncio.sleep(retry_interval)

        logger.error("BOPTEST service did not respond after 10 minutes. Continuing without warmup.")
        return False

    async def _warmup_boptest(self) -> None:
        """Pre-warm all BOPTEST test cases by selecting and stopping each one.

        First polls the service until it is ready, then selects and stops
        each test case to force FMU compilation. Retries each test case
        once on failure (the worker might be busy finishing a previous compile).
        """
        from validator.emulator.boptest_client import BOPTESTClient

        if not await self._wait_for_boptest():
            return

        client = BOPTESTClient(self.boptest_url)
        try:
            test_cases = self.manifest.get("test_cases", [])
            logger.info(f"Pre-warming {len(test_cases)} BOPTEST test cases...")

            for tc in test_cases:
                tc_id = tc["id"]
                for attempt in range(1, 3):
                    start = time.monotonic()
                    try:
                        testid = await client.select_testcase(tc_id)
                        await client.stop(testid)
                        elapsed = time.monotonic() - start
                        logger.info(f"  Warmed {tc_id} in {elapsed:.1f}s")
                        break
                    except Exception as e:
                        elapsed = time.monotonic() - start
                        if attempt == 1:
                            logger.warning(f"  {tc_id} failed ({elapsed:.1f}s): {e}. Retrying...")
                            await asyncio.sleep(5)
                        else:
                            logger.warning(f"  {tc_id} failed on retry ({elapsed:.1f}s): {e}. Skipping.")

            logger.info("BOPTEST warmup complete")
        finally:
            await client.close()

    async def _run_challenge_round(self) -> None:
        """Run a single calibration round and persist per-miner scores.

        Does not set weights; that is the weight loop's job. The only
        external side effect beyond logging is the ScoringDB insert at
        the end.
        """
        round_id = f"round-{self.round_count}"
        self.round_count += 1
        # Persist before running the round so a crash mid-round still advances
        # the counter on next boot. Losing one round of attempted work is
        # strictly better than replaying the same deterministic round_id.
        self.scoring_db.set_round_count(self.round_count)
        logger.info(f"=== {round_id} starting ===")

        # 1. Sync metagraph
        if self.metagraph is not None:
            logger.info("Syncing metagraph...")
            try:
                await self._chain_op(
                    self.metagraph.sync,
                    timeout=METAGRAPH_SYNC_TIMEOUT_SECONDS,
                )
            except Exception as e:
                logger.warning(f"Metagraph sync failed, using stale data: {e}")
            logger.info(f"Metagraph: {len(self.metagraph.neurons)} neurons")

        # 2. Select test case and compute split
        test_case = test_case_selector.select(round_id, self.manifest)
        train_period, test_period = split_generator.compute(round_id, test_case["id"])
        logger.info(f"Test case: {test_case['id']}")
        logger.info(f"Train period: hours {train_period[0]}-{train_period[1]}")
        logger.info(f"Test period: hours {test_period[0]}-{test_period[1]}")

        # 3. Generate ground truth
        if self.local_mode:
            logger.info("Generating ground truth (local mode: RC model)...")
        else:
            logger.info(f"Generating ground truth (BOPTEST: {self.boptest_url})...")
        held_out_data = await self.orchestrator.generate_ground_truth(
            test_case, test_period, local_mode=self.local_mode
        )
        training_data = await self.orchestrator.generate_ground_truth(
            test_case, train_period, local_mode=self.local_mode
        )
        logger.info(f"Training signal: {self._summarize_signal(training_data)}")

        # 4. Build test case config
        config = self.orchestrator.load_test_case_config(test_case["id"])

        # 5. Build CalibrationSynapse
        synapse = CalibrationSynapse(
            test_case_id=test_case["id"],
            manifest_version=self.manifest["version"],
            training_data=training_data,
            parameter_names=list(config["parameter_names"]),
            parameter_bounds=config["parameter_bounds"],
            simulation_budget=config.get("simulation_budget", 1000),
            round_id=round_id,
            train_start_hour=train_period[0],
            train_end_hour=train_period[1],
        )

        # 6. Send to miners
        submissions: dict[int, dict[str, Any]] = {}
        axons, uids = self._get_miner_axons()

        if not axons:
            logger.warning("No miners available to query")
            return

        logger.info(f"Sending challenge to {len(axons)} miners (timeout={CHALLENGE_TIMEOUT_SECONDS}s)")
        timeout = float(CHALLENGE_TIMEOUT_SECONDS)

        if self.challenge_sender is not None:
            responses = await self.challenge_sender.send_challenge(axons, synapse, timeout)
            submissions = self.response_parser.parse_responses(responses, uids)

        logger.info(f"Received {len(submissions)} valid submissions")

        if not submissions:
            logger.warning("No valid submissions received this round")
            return

        # 7. Build verification config and verify
        verification_config = self.orchestrator.build_verification_config(test_case)
        sim_budget = verification_config.get("simulation_budget", 1000)
        logger.info("Verifying submissions...")
        verified = await self.verification_engine.verify_all(
            submissions, verification_config, test_period, held_out_data, sim_budget=sim_budget
        )

        # 8. Compute scores
        scores = self.scoring_engine.compute(verified, sim_budget=sim_budget)
        logger.info(f"Scores: {scores}")

        # Log per-metric breakdown for each miner
        for uid, v in verified.items():
            if v.reason:
                logger.info(f"  UID {uid}: REJECTED ({v.reason})")
            else:
                ceiling_flag = " (CEILING EXCEEDED, component score=0)" if v.cvrmse_ceiling_exceeded else ""
                logger.info(
                    f"  UID {uid}: CVRMSE={v.cvrmse:.4f}{ceiling_flag}, NMBE={v.nmbe:.4f}, "
                    f"R2={v.r_squared:.4f}, sims={v.simulations_used}, "
                    f"composite={scores.get(uid, 0.0):.4f}"
                )
                logger.info(f"  UID {uid} params: {self._format_params_for_log(v.calibrated_params)}")

        # 9. Persist per-miner scores
        await self.scoring_db.insert_round_scores(
            round_id=round_id,
            test_case=test_case["id"],
            train_period=train_period,
            test_period=test_period,
            verified=verified,
            composites=scores,
        )

        logger.info(f"=== {round_id} complete (persisted) ===")

    async def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep until duration elapses or shutdown is signalled.

        Ensures a long sleep cannot delay graceful shutdown by more than
        the sleep length. Returns immediately if shutdown is already set.
        """
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._shutdown.wait(), timeout=seconds)

    async def _chain_op(
        self,
        op: Callable[..., Any],
        *args: Any,
        timeout: float = CHAIN_READ_TIMEOUT_SECONDS,
        **kwargs: Any,
    ) -> Any:
        """Single entry point for every blocking chain RPC.

        Serializes access to the shared substrate websocket connection
        (required because ``websockets.sync`` raises ``ConcurrencyError``
        if two threads call ``recv()`` on the same connection), runs the
        blocking SDK call in a thread via :func:`asyncio.to_thread`, and
        wraps the whole thing in :func:`asyncio.wait_for` so a wedged
        websocket becomes a catchable :class:`asyncio.TimeoutError`
        instead of a silent hang.

        This is also the migration seam for ``AsyncSubtensor``. When we
        eventually migrate (blocked pending Async-Substrate-Interface
        2.0 stabilization), this method's body becomes ``return await
        asyncio.wait_for(op(*args, **kwargs), timeout=timeout)`` and the
        lock disappears. No call-site changes required.

        Args:
            op: Bound method on ``self.subtensor`` or ``self.metagraph``.
                Must be synchronous.
            *args: Positional args for the op.
            timeout: Seconds before :class:`asyncio.TimeoutError`.
                Default suited for light reads; pass
                ``METAGRAPH_SYNC_TIMEOUT_SECONDS`` for
                ``metagraph.sync()`` or weight-setting calls.
            **kwargs: Keyword args for the op.

        Returns:
            Whatever ``op`` returns.

        Raises:
            asyncio.TimeoutError: If the op does not complete within
                ``timeout``.
        """
        async with self._subtensor_lock:
            return await asyncio.wait_for(
                asyncio.to_thread(op, *args, **kwargs),
                timeout=timeout,
            )

    async def _blocks_until_weight_eligible(self) -> int:
        """Return number of blocks remaining until we may set weights.

        Zero means eligible now. Reads ``weights_rate_limit`` and
        ``blocks_since_last_update`` directly from chain via
        :meth:`_chain_op`, with tenacity retry for transient RPC
        failures. The lock is taken per call by ``_chain_op``; two
        sequential reads from the same coroutine take-and-release the
        lock twice. Fairness over strict transactional reads: the
        arithmetic is still coherent because both values were fresh at
        the moment of their own read.
        """
        async for attempt in AsyncRetrying(
            wait=wait_fixed(10),
            stop=stop_after_attempt(3),
            retry=retry_if_exception_type((ConnectionError, asyncio.TimeoutError, OSError)),
            reraise=True,
        ):
            with attempt:
                rate_limit = await self._chain_op(
                    self.subtensor.weights_rate_limit,
                    netuid=self.netuid,
                    timeout=CHAIN_READ_TIMEOUT_SECONDS,
                )
                blocks_since = await self._chain_op(
                    self.subtensor.blocks_since_last_update,
                    netuid=self.netuid,
                    uid=self.my_uid,
                    timeout=CHAIN_READ_TIMEOUT_SECONDS,
                )
                return max(0, int(rate_limit) - int(blocks_since))
        return 0

    async def _compute_and_commit_weights(self) -> bool:
        """Read 72h window from DB, compute EMA, commit to chain.

        Returns True on successful commit (including fallback path).
        Does not perform block-gating; that is the caller's job.
        Preserves the chain-copy fallback on weight-set failure.
        """
        window_rows = await self.scoring_db.get_scores_in_window(hours=self.scoring_window_hours)
        if not window_rows:
            logger.info("No scores in window; skipping weight commit")
            return False

        weights = compute_window_ema(window_rows, alpha=self.ema_alpha)
        if not weights:
            logger.warning("compute_window_ema returned empty; skipping")
            return False

        num_rounds = len({r.round_id for r in window_rows})
        logger.info(
            f"Committing weights (window={self.scoring_window_hours}h, "
            f"rounds={num_rounds}, miners={len(weights)}): {weights}"
        )

        if self.weight_setter is None:
            logger.warning("No weight_setter configured; skipping commit")
            return False

        self._weight_commit_started_at = time.monotonic()
        try:
            success = await self.weight_setter.set_weights(weights)
        finally:
            self._weight_commit_started_at = None
        if success:
            logger.info("Weights set on chain successfully")
            self._last_gated_log_time = 0.0
            return True

        logger.warning("Weight set failed; attempting chain fallback")
        fallback = await self.weight_setter.copy_weights_from_chain()
        if fallback:
            self._weight_commit_started_at = time.monotonic()
            try:
                fallback_success = await self.weight_setter.set_weights(fallback)
            finally:
                self._weight_commit_started_at = None
            if fallback_success:
                logger.info("Fallback weights committed")
                return True

        await self.alerter.send("weights_failed", "Failed to set weights on chain")
        return False

    async def _challenge_loop(self) -> None:
        """Run calibration rounds at the configured interval until shutdown."""
        logger.info(f"Challenge loop started (interval={self.challenge_interval_seconds}s)")
        while not self._shutdown.is_set():
            try:
                await self._run_challenge_round()
            except Exception:
                logger.exception("Challenge round failed; continuing")
            await self._interruptible_sleep(self.challenge_interval_seconds)
        logger.info("Challenge loop exiting")

    async def _weight_loop(self) -> None:
        """Poll block-rate-limit and commit weights when eligible."""
        logger.info(f"Weight loop started (check_interval={self.weight_check_interval_seconds}s)")

        try:
            remaining_at_start = await self._blocks_until_weight_eligible()
            rate_limit = await self._chain_op(
                self.subtensor.weights_rate_limit,
                netuid=self.netuid,
                timeout=CHAIN_READ_TIMEOUT_SECONDS,
            )
            logger.info(
                f"Weight loop gate state: rate_limit={rate_limit} blocks "
                f"(~{int(rate_limit) * BLOCK_TIME_SECONDS}s), "
                f"remaining={remaining_at_start} blocks"
            )
        except Exception:
            logger.exception("Failed to read initial gate state; continuing")

        while not self._shutdown.is_set():
            try:
                remaining = await self._blocks_until_weight_eligible()
                if remaining > 0:
                    sleep_s = min(
                        remaining * BLOCK_TIME_SECONDS,
                        self.weight_check_interval_seconds,
                    )
                    now = time.monotonic()
                    if now - self._last_gated_log_time >= 300.0 or self._last_gated_log_time == 0.0:
                        logger.info(
                            f"Weights not yet eligible ({remaining} blocks remaining, "
                            f"~{remaining * BLOCK_TIME_SECONDS}s); next check in {sleep_s}s"
                        )
                        self._last_gated_log_time = now
                    await self._interruptible_sleep(sleep_s)
                    continue

                await self._compute_and_commit_weights()
            except Exception:
                logger.exception("Weight loop iteration failed; continuing")

            await self._interruptible_sleep(self.weight_check_interval_seconds)
        logger.info("Weight loop exiting")

    async def _cleanup_loop(self) -> None:
        """Prune DB rows older than the retention window, once per interval."""
        logger.info(
            f"Cleanup loop started (interval={self.cleanup_interval_seconds}s, "
            f"retention={self.cleanup_retention_hours}h)"
        )
        while not self._shutdown.is_set():
            try:
                deleted = await self.scoring_db.cleanup_older_than(hours=self.cleanup_retention_hours)
                if deleted:
                    logger.info(f"Cleanup: deleted {deleted} rows older than {self.cleanup_retention_hours}h")
            except Exception:
                logger.exception("Cleanup failed; continuing")
            await self._interruptible_sleep(self.cleanup_interval_seconds)
        logger.info("Cleanup loop exiting")

    async def _weight_commit_watchdog(self) -> None:
        """Detect hung weight commits and exit the process.

        The sync Bittensor SDK's ``set_weights`` can wedge indefinitely
        inside its ``wait_for_inclusion``/``wait_for_finalization`` loop
        when substrate subscription threads deadlock. ``asyncio.wait_for``
        cannot cancel the thread, so the weight loop becomes permanently
        stuck holding the subtensor lock. This watchdog polls every 10
        seconds; if a commit has been in flight longer than
        ``WEIGHT_COMMIT_WATCHDOG_SECONDS``, it logs loudly and calls
        ``os._exit(1)``.

        ``os._exit`` (not ``sys.exit``) bypasses asyncio's finalization
        which would itself hang on the stuck gather(). The process dies;
        a supervisor (systemd, docker, tmux-with-wrapper, or a human)
        restarts it.
        """
        logger.info(f"Weight-commit watchdog started (threshold={WEIGHT_COMMIT_WATCHDOG_SECONDS}s)")
        while not self._shutdown.is_set():
            await self._interruptible_sleep(10.0)
            started = self._weight_commit_started_at
            if started is None:
                continue
            elapsed = time.monotonic() - started
            if elapsed > WEIGHT_COMMIT_WATCHDOG_SECONDS:
                logger.error(
                    f"WEIGHT COMMIT HUNG: in flight for {elapsed:.0f}s "
                    f"(threshold {WEIGHT_COMMIT_WATCHDOG_SECONDS}s). "
                    f"Substrate subscription thread likely deadlocked. "
                    f"Exiting via os._exit(1) for restart. "
                    f"If running under systemd/docker/shell-wrapper, the "
                    f"process will auto-restart; otherwise manual restart "
                    f"required."
                )
                for handler in logging.getLogger().handlers:
                    with contextlib.suppress(Exception):
                        handler.flush()
                os._exit(1)
        logger.info("Weight-commit watchdog exiting")

    def _handle_shutdown_signal(self, sig: signal.Signals) -> None:
        """Signal handler: graceful shutdown on first signal, force-exit on second.

        First SIGINT/SIGTERM sets ``_shutdown`` and records the timestamp.
        Repeated signals within ``SHUTDOWN_GRACE_SECONDS`` are ignored
        (graceful shutdown is still in progress). A signal arriving after
        the grace window expires force-exits via ``os._exit(0)`` so
        operators can always quit even when a chain thread is wedged.
        """
        now = time.monotonic()
        if self._first_shutdown_at is None:
            logger.warning(f"Received signal {sig.name}; initiating shutdown")
            self._first_shutdown_at = now
            self._shutdown.set()
            return

        elapsed = now - self._first_shutdown_at
        if elapsed < SHUTDOWN_GRACE_SECONDS:
            logger.warning(
                f"Received {sig.name} again ({elapsed:.1f}s into shutdown); "
                f"still trying to exit gracefully. Send again after "
                f"{SHUTDOWN_GRACE_SECONDS}s to force."
            )
            return

        logger.error(
            f"Received {sig.name} {elapsed:.1f}s after first signal. "
            f"Graceful shutdown is stuck (likely a wedged chain thread). "
            f"Force-exiting via os._exit(0)."
        )
        for handler in logging.getLogger().handlers:
            with contextlib.suppress(Exception):
                handler.flush()
        os._exit(0)

    async def start(self) -> None:
        """One-time startup: warmup, health server, alerter ping.

        Kept separate from :meth:`run` so tests and orchestration code can
        drive the loops directly without repeating signal-handler wiring.
        """
        logger.info(
            f"Starting ZhenValidator (netuid={self.netuid}, "
            f"challenge_interval={self.challenge_interval_seconds}s, "
            f"weight_check_interval={self.weight_check_interval_seconds}s)"
        )
        logger.info(f"Local mode: {self.local_mode}")
        if not self.local_mode:
            logger.info(f"BOPTEST URL: {self.boptest_url}")
            await self._warmup_boptest()
        logger.info(f"Manifest version: {self.manifest['version']}")
        logger.info(f"Spec version: {protocol.__spec_version__}")
        logger.info(f"ScoringDB ready (path={self.scoring_db.db_path}, window={self.scoring_window_hours}h)")

        await self.health.start()

        await self.alerter.send(
            "startup",
            "Validator started",
            {
                "netuid": self.netuid,
                "network": self.network,
                "manifest_version": self.manifest["version"],
                "test_cases": len(self.manifest.get("test_cases", [])),
            },
        )

    async def run(self) -> None:
        """Start validator and run all loops until shutdown signal."""
        await self.start()

        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self._handle_shutdown_signal, sig)
        except NotImplementedError:
            # Windows: asyncio cannot install signal handlers; rely on KeyboardInterrupt
            pass

        logger.info("Starting async loops")
        tasks = [
            asyncio.create_task(self._challenge_loop(), name="challenge_loop"),
            asyncio.create_task(self._weight_loop(), name="weight_loop"),
            asyncio.create_task(self._cleanup_loop(), name="cleanup_loop"),
            asyncio.create_task(self._weight_commit_watchdog(), name="weight_commit_watchdog"),
        ]

        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            logger.info("Stopping loops")
            self._shutdown.set()
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            try:
                self.scoring_db.close()
            except Exception:
                logger.exception("Error closing scoring DB")

            logger.info("Validator shut down cleanly")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Zhen Subnet Validator")
    parser.add_argument("--netuid", type=int, default=DEFAULT_NETUID, help="Subnet UID")
    parser.add_argument("--network", type=str, default=DEFAULT_NETWORK, help="Network (test, finney, or ws:// URL)")
    parser.add_argument("--wallet-name", type=str, default="zhen-validator", help="Wallet name")
    parser.add_argument("--wallet-hotkey", type=str, default="default", help="Wallet hotkey")
    parser.add_argument("--local-mode", action="store_true", default=True, help="Use RC model as ground truth")
    parser.add_argument("--no-local-mode", action="store_false", dest="local_mode", help="Use BOPTEST for ground truth")
    parser.add_argument("--boptest-url", type=str, default="http://localhost:8000", help="BOPTEST service URL")
    parser.add_argument("--health-port", type=int, default=8080, help="Health check HTTP port")
    parser.add_argument(
        "--challenge-interval-seconds",
        type=int,
        default=DEFAULT_CHALLENGE_INTERVAL_SECONDS,
        help="Seconds between challenge rounds (default: 900 = 15min)",
    )
    parser.add_argument(
        "--weight-check-interval-seconds",
        type=int,
        default=DEFAULT_WEIGHT_CHECK_INTERVAL_SECONDS,
        help="Seconds between weight-eligibility checks (default: 60)",
    )
    parser.add_argument(
        "--cleanup-interval-seconds",
        type=int,
        default=DEFAULT_CLEANUP_INTERVAL_SECONDS,
        help="Seconds between cleanup runs (default: 86400 = 24h)",
    )
    parser.add_argument(
        "--cleanup-retention-hours",
        type=int,
        default=DEFAULT_CLEANUP_RETENTION_HOURS,
        help="Hours of history to keep in DB (default: 168 = 7 days)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    setup_logging("validator", args.log_level)
    validator = ZhenValidator(
        netuid=args.netuid,
        network=args.network,
        wallet_name=args.wallet_name,
        wallet_hotkey=args.wallet_hotkey,
        local_mode=args.local_mode,
        boptest_url=args.boptest_url,
        health_port=args.health_port,
        challenge_interval_seconds=args.challenge_interval_seconds,
        weight_check_interval_seconds=args.weight_check_interval_seconds,
        cleanup_interval_seconds=args.cleanup_interval_seconds,
        cleanup_retention_hours=args.cleanup_retention_hours,
    )
    asyncio.run(validator.run())
