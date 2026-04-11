"""ASHRAE-standard metric implementations: CVRMSE, NMBE, and R-squared.

All computations use float64 arrays. Handles edge cases including zero
mean measurements, empty arrays, and non-finite values.
"""
