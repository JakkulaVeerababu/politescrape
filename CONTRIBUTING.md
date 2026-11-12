# Contributing to politescrape

Thank you for helping. Bug reports, ideas, documentation fixes and code are all welcome.

## Reporting a problem

Open an issue with the address you were scraping (if it is public), the command or code you ran, what you expected and what happened. The output of `politescrape --version` and your Python version help too.

For security problems, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Setting up

```bash
git clone https://github.com/JakkulaVeerababu/politescrape
cd politescrape
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

## Checks

Run these before opening a pull request. CI runs the same ones.

```bash
ruff format .
ruff check .
mypy
pytest --cov
```

## Writing tests

- Tests must never use the network. `tests/conftest.py` provides a `FakeSite` that serves canned responses and a `FakeClock` that records pauses, so you can test delays and retries without waiting.
- Use short, made-up HTML in tests. Do not copy pages from real sites.
- Name tests after the behaviour they check, for example `test_redirect_loops_end_in_an_error`.

## Pull requests

- Keep each pull request to one change, and explain why it is needed.
- Add or update tests for any change in behaviour.
- Add a line to `CHANGELOG.md` under "Unreleased" for anything a user would notice.
- Features that help evade bot detection, solve CAPTCHAs or get past logins will not be accepted; see the README.

## Releasing (maintainers)

1. Update the version in `src/politescrape/_version.py` and move the "Unreleased" changelog entries under the new version.
2. Tag the commit `vX.Y.Z` and push the tag. The release workflow builds the package and publishes it to PyPI through trusted publishing, which has to be set up once on PyPI for this repository.
