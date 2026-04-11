"""Deterministic hashing wrappers using hashlib.sha256.

Provides consistent hashing for test case selection, train/test split
computation, and any other operation requiring cross-validator determinism.
Never uses Python's built-in hash().
"""
