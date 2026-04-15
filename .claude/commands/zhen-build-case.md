Build and validate a new test case

NOTE: The eval harness is not yet implemented. To validate a test case manually:

```
uv run pytest tests/unit/test_manifest.py tests/unit/test_rc_network.py -v
```

This runs manifest validation and RC model physics checks against available test cases.
