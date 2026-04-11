"""Hard timeout enforcement for verification runs.

Enforces a 5-minute hard limit per miner verification. Submissions that
exceed the timeout receive a score of 0.0 with reason SIMULATION_TIMEOUT.
"""
