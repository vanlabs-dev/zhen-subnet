"""Standalone local eval harness (zhen-eval).

Allows miners to test their calibration locally before submitting. Starts
a local BOPTEST emulator container, generates ground truth, runs the
simplified model with provided parameters, and outputs the identical JSON
score breakdown a validator would produce.
"""
