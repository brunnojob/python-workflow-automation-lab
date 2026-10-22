# Python Workflow Automation Lab

> Educational project for studying process automation, RPA boundaries and API integration. Run experiments only against resources you own or are authorized to inspect. This project does not automate social engagement or create accounts.

A dependency-free Python laboratory for resumable public repository collection, isolated task handoffs and GitHub repository health checks. A static GitHub Pages interface demonstrates the workflow without a login, token or backend.

## Advanced collector

The `collect` command builds a public repository catalog for an explicitly allowed secondary account through `GET /users/{owner}/repos`. It uses API pagination rather than HTML scraping. It exports repository names, descriptions, languages, licenses, archive/fork flags, default branches and push timestamps. It does not harvest personal profiles, email addresses or followers.

```sh
python -m lab collect secondary-a --allow-owner secondary-a --demo --per-page 1 --max-pages 1 --output reports/demo
python -m lab collect secondary-a --allow-owner secondary-a --demo --per-page 1 --max-pages 5 --output reports/demo
```

The first command collects one fixture page. The second resumes and completes the three-record fixture dataset. Both use zero network requests. Demo databases receive a `.demo` suffix to keep fixtures separate from live data.

Live collection for your authorized public secondary account:

```sh
python -m lab collect SECONDARY_ACCOUNT --allow-owner SECONDARY_ACCOUNT --per-page 30 --max-pages 5 --output reports/catalog
python -m lab export SECONDARY_ACCOUNT --allow-owner SECONDARY_ACCOUNT --output reports/catalog
```

Run the same `collect` command to resume an incomplete catalog. A completed catalog makes zero new requests until `--refresh` is supplied. Use the original `--per-page` when resuming. `--refresh` clears that owner's previous catalog and starts a fresh scan, reusing ETags. To preserve an older snapshot, export or copy it before refreshing. On failure the database retains completed pages; `export` can recover a partial report without network access.

| Feature | Behavior |
| --- | --- |
| Pagination | Follows `rel="next"` from the API Link header, validating HTTPS, host, owner, endpoint and query; canonical numeric owner paths must match the owner ID validated from repository metadata |
| Scope | Explicit owner allowlist; main account blocked; public repositories only; no authentication |
| Checkpoint | Local SQLite transaction commits page records, cache and next URL together |
| Cache | Persistent ETag/body cache; 304 responses reuse a previously validated page |
| Limits | Serial GET requests; configurable interval of 1–60 seconds; 1–20 pages per invocation; 1–100 records per page |
| API cooldown | HTTP 403/429 stops immediately and persists a cooldown; successful responses with zero remaining quota also pause subsequent calls |
| Export | JSON and UTF-8 CSV with formula-leading text escaped in CSV; each output file is atomically replaced |
| Deduplication | One catalog record per owner/repository; output sorted by repository name |
| Errors | No automatic retry; page checkpoint stays at the last successfully committed response |

The SQLite file is local storage, not a hosted GitHub database. Do not share one database between concurrent collectors. GitHub pagination is not a point-in-time snapshot: repositories added, renamed or removed during a scan may change page boundaries; refresh when you need a new catalog. Cooldowns are local to that database, and other processes sharing your IP still consume GitHub's quota. Pages shows the interface and sample report; Python collection runs on your machine.

## Technologies

Python 3.11+, `urllib.request`, `sqlite3`, `csv`, `json`, `argparse`, `dataclasses`, `unittest`, HTML, CSS, vanilla JavaScript, GitHub REST API, GitHub Actions and GitHub Pages. No Selenium, Playwright, PyAutoGUI or external Python packages are required.

## Architecture

| Component | Responsibility |
| --- | --- |
| `lab/core.py` | Owner validation, main-account exclusion, anonymous GET requests, request budget, ETag cache, response validation and local simulation |
| `lab/collector.py` | Paginated public metadata collection, transactional SQLite state, durable ETag cache, cooldowns, deduplication and JSON/CSV export |
| `lab/__main__.py` | CLI arguments, JSON output, file export and nonzero error exits |
| `tests/test_lab.py` | Isolation, transport behavior, conditional requests, rate limits and offline task handoff |
| `tests/test_collector.py` | Resumption, restart recovery, export safety, pagination scope, partial failures, persistent caching and cooldowns |
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

Twenty-six offline tests cover isolation, path injection, GET-only access, ETags, named/numeric pagination, checkpoint recovery, persistent cooldowns, export safety, response validation and simulation. CI repeats these checks across its declared operating-system and Python matrix. A passing offline suite does not establish a live secondary-account interaction.

## References

- [GitHub REST API best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- [REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [Configure GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)

## License

MIT. See [LICENSE](LICENSE).
