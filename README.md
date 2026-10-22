# Python Workflow Automation Lab

> Educational project for studying process automation, RPA boundaries and API integration. Run experiments only against resources you own or are authorized to inspect. This project does not automate social engagement or create accounts.

A dependency-free Python laboratory for isolated task handoffs and public GitHub repository health checks. A static GitHub Pages interface demonstrates the same workflow without a login, token or backend.

## Technologies

Python 3.11+, `urllib.request`, `json`, `argparse`, `dataclasses`, `unittest`, HTML, CSS, vanilla JavaScript, GitHub REST API, GitHub Actions and GitHub Pages. No Selenium, Playwright, PyAutoGUI or external Python packages are required.

## Architecture

| Component | Responsibility |
| --- | --- |
| `lab/core.py` | Owner validation, main-account exclusion, anonymous GET requests, request budget, ETag cache, response validation and local simulation |
| `lab/__main__.py` | CLI arguments, JSON output, file export and nonzero error exits |
| `tests/test_lab.py` | Isolation, transport behavior, conditional requests, rate limits and offline task handoff |
| `docs/` | Static interactive simulation and public API audit |
| `.github/workflows/ci.yml` | Offline tests on Linux and Windows with Python 3.11 and 3.13 |

The two secondary actors are local fixtures. They exchange task states in memory, with no GitHub authentication or network activity. They do not represent actual secondary accounts. Live mode inspects one explicitly allowed public repository. `brunnojob` is always excluded as a runtime target, even if included in the allowlist. It is only the publishing account for this repository.

There is no screen-coordinate controller or Windows window manipulation. API integration avoids fragile GUI selectors and shared browser sessions. The CLI runs on Windows, Linux and macOS. The Pages demo cannot run Python; it uses its own anonymous JavaScript GET client.

The clients implement no stars, follows, comments, issues, PR creation or account creation. They never consume credentials from files, environment variables or browser sessions. The CLI blocks redirects and validates repository identity. These application checks are not an operating-system security sandbox.

## Run

From the repository directory:

```sh
python -m lab simulate
python -m lab simulate --output simulation.json
python -m unittest discover -s tests -v
```

Inspect a public study repository by replacing both placeholders with your authorized secondary account and repository:

```sh
python -m lab audit SECONDARY_ACCOUNT/STUDY_REPOSITORY --allow-owner SECONDARY_ACCOUNT
```

On Windows, use `py` instead of `python` if needed. No installation or token is required.

## API behavior

Requests are serial and bounded. Python defaults to ten requests per client instance; the browser limits each page session to ten. A 15-second timeout bounds each request. ETags enable conditional requests within the current process or browser session. HTTP 403/429 stops immediately, without retries or account rotation. Python reports `Retry-After` and `X-RateLimit-Reset` when present. Rate limits still apply to anonymous clients.

Network, malformed JSON and file-output errors produce an explicit CLI error with exit code 1. Redirects are rejected rather than following a renamed repository outside the selected target. The health check reports description, license, issue availability and archived status; it is not a security audit.

## Pages

The static interface is in `docs/`. Select **Settings → Pages → Deploy from a branch → main → /docs**. Local preview:

```sh
python -m http.server 8000 --directory docs
```

Open `http://localhost:8000`. The simulation works offline after the assets load. The public audit needs access to `api.github.com` and is affected by network, browser and GitHub limits. No tokens belong in Pages files.

## Verification

Ten offline tests cover the main-account deny rule before transport, explicit owner scope, path injection, anonymous GET-only access, ETag/304 handling, rate-limit termination, request budgets, response identity, redirects and two-actor simulation. CI repeats these checks across its declared operating-system and Python matrix. A passing offline suite does not establish a live secondary-account interaction.

## References

- [GitHub REST API best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- [REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [Configure GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)

## License

MIT. See [LICENSE](LICENSE).
