"""Round lifecycle management.

Runs one calibration round per tempo: selects a test case, computes the
train/test split, runs the complex emulator, sends challenges to miners,
verifies submissions, computes scores, and sets weights.
"""
