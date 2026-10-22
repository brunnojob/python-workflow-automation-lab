import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class LabError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Policy:
    owners: tuple[str, ...]

    def validate(self, repository):
        parts = repository.split("/")
        if len(parts) != 2:
            raise LabError("Use owner/repository.")
        owner, name = parts
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner):
            raise LabError("Invalid owner.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name) or name in {".", ".."}:
            raise LabError("Invalid repository name.")
        if owner.lower() == "brunnojob":
            raise LabError("The main account is excluded from automation targets.")
        if owner.lower() not in {value.lower() for value in self.owners}:
            raise LabError("Owner is outside the explicit allowlist.")
        return f"{owner}/{name}"


class GitHubReader:
    def __init__(self, policy, transport=None, budget=10):
        if not 1 <= budget <= 20:
            raise LabError("Request budget must be between 1 and 20.")
        self.policy = policy
        self.transport = transport or build_opener(NoRedirect()).open
        self.remaining = budget
        self.cache = {}

    def repository(self, target):
        target = self.policy.validate(target)
        if self.remaining == 0:
            raise LabError("Local request budget exhausted.")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "python-workflow-automation-lab/1.0",
        }
        cached = self.cache.get(target)
        if cached and cached[0]:
            headers["If-None-Match"] = cached[0]
        request = Request(f"https://api.github.com/repos/{target}", headers=headers, method="GET")
        self.remaining -= 1
        try:
            with self.transport(request, timeout=15) as response:
                if response.status != 200:
                    raise LabError(f"Unexpected HTTP status: {response.status}.")
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise LabError("Response exceeded size limit.")
                data = json.loads(raw)
                if not isinstance(data, dict) or str(data.get("full_name", "")).lower() != target.lower():
                    raise LabError("Repository identity mismatch.")
                self.cache[target] = (response.headers.get("ETag"), data)
                return audit(data)
        except HTTPError as exc:
            if exc.code == 304 and cached:
                return audit(cached[1])
            if exc.code in {403, 429}:
                retry = exc.headers.get("Retry-After", "unspecified")
                reset = exc.headers.get("X-RateLimit-Reset", "unspecified")
                raise LabError(f"API refused the request; stopped without retry. Retry-After={retry}; reset={reset}.") from None
            raise LabError(f"GitHub returned HTTP {exc.code}; no retry performed.") from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise LabError(f"Request failed ({type(exc).__name__}); no retry performed.") from None


def audit(data):
    checks = {
        "description": bool(data.get("description")),
        "license": bool(data.get("license")),
        "issues_enabled": bool(data.get("has_issues")),
        "active": not bool(data.get("archived")),
    }
    return {"repository": data["full_name"], "checks": checks, "passed": sum(checks.values()), "total": len(checks)}


def simulate():
    events = []
    task = {"id": "LAB-001", "status": "pending"}
    for actor, status in (("secondary-a", "queued"), ("secondary-b", "validated"), ("secondary-a", "completed")):
        task["status"] = status
        events.append({"sequence": len(events) + 1, "actor": actor, "task": task["id"], "status": status})
    return {"mode": "offline", "network_requests": 0, "events": events, "final_status": task["status"]}
