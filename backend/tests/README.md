# Backend Test Suite

This directory contains tests for Agentic Alpha backend, including:
- Strategy registry and logic
- API endpoints
- Database integration
- Event bus and services

## Running Tests

From project root:

```powershell
pytest
```

Or to run only strategy tests:

```powershell
pytest -m strategy
```

## Adding Tests
- Place new test files here, named `test_*.py`
- Use `pytest.mark.strategy` for strategy tests
- Use `pytest.mark.integration` for integration tests

---

See `pytest.ini` for configuration.
