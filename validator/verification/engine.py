"""Verification engine for miner submissions.

Runs the simplified model with each miner's calibrated parameters on the
held-out period, compares predictions against complex emulator ground truth,
and computes per-miner CVRMSE, NMBE, and R-squared metrics. Supports parallel
verification with configurable concurrency via asyncio semaphore.
"""
