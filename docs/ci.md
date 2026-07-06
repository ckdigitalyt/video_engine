# CI — video_engine

## Workflow

The project uses **GitHub Actions** for continuous integration.  
The workflow is defined in `.github/workflows/python-ci.yml`.

## Trigger Conditions

The workflow runs automatically on:

| Event | Branches |
|-------|----------|
| `push` | `main` |
| `pull_request` | `main` (to `main`) |

## Environment

| Setting | Value |
|---------|-------|
| Runner | `ubuntu-latest` |
| Python | 3.12 |
| Dependencies | `requirements.txt` (pip freeze) |

## Steps

1. **Checkout** — `actions/checkout@v4`
2. **Setup Python** — `actions/setup-python@v5` with Python 3.12
3. **Install dependencies** — `pip install -r requirements.txt` inside a fresh virtual environment
4. **Run tests** — `pytest` (all 163 tests)
5. **Coverage** — `pytest --cov=src --cov=renderer --cov-report=term-missing`

The workflow fails if any test fails.

## API Keys

All external APIs are mocked in the test suite via `conftest.py`.  
The workflow provides fallback dummy values for `DEEPSEEK_API_KEY`,
`GEMINI_API_KEY`, and `PEXELS_API_KEY` so provider imports do not fail.
Real API keys should be stored as [GitHub repository secrets](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions)
and are used only by end-to-end pipeline runs, not CI.

## Running Locally

```bash
source venv/bin/activate
pytest
```

This is identical to what the CI runner executes.

## Future Extensions

Planned additions to the CI pipeline:

| Step | Purpose |
|------|---------|
| **Linting** | `ruff check src/` — catch Python style errors |
| **Type checking** | `mypy src/` — verify type annotations |
| **Security scan** | `bandit -r src/` — detect common vulnerabilities |
| **Dependency audit** | `pip-audit` — flag known CVEs |
| **Docker build** | Verify the Docker image builds and smoke-tests |

These are intentionally excluded from the initial workflow to keep
CI fast and focused on test correctness.

## Troubleshooting

**Tests fail with `ModuleNotFoundError: No module named 'src'`**  
→ Ensure `pytest.ini` contains `pythonpath = .`. This was fixed in commit `4fced5c`.

**Tests fail with `FileNotFoundError: .../kokoro-v0_19.onnx`**  
→ This is expected in CI. The Kokoro provider is lazy-loaded and only
   triggered by `generate_voice()`, which is never called in tests.
   All Kokoro tests mock the ONNX engine entirely.
