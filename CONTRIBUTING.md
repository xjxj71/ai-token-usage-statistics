# Contributing to AI Token Usage Statistics

Thank you for your interest in contributing!

## Development Setup

1. Clone the repository
2. Create a Python virtual environment: `python -m venv .venv`
3. Install dependencies: `pip install -e ".[dev]"`
4. Install frontend dependencies: `cd frontend && npm install`

## Running Tests

```bash
# Backend tests
pytest

# Linting
ruff check backend/ tests/
```

## Submitting Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Run tests and lint
5. Commit with a clear message
6. Push and create a Pull Request

## Adding a New Agent Collector

1. Create a new file in `backend/collectors/`
2. Implement the `BaseCollector` interface
3. Add the collector to `COLLECTORS` list in `registry.py`
4. Update documentation

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
