import csv
import io
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener

from .core import LabError, NoRedirect, Policy


FIELDS = ("repository", "description", "language", "license", "archived", "fork", "default_branch", "pushed_at")


def next_link(header):
    for part in header.split(","):
        match = re.fullmatch(r'\s*<([^>]+)>\s*;\s*rel="([^"]+)"\s*', part)
        if match and "next" in match[2].split():
            return match[1]
    return None


def spreadsheet_cell(value):
    value = "" if value is None else str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs(owner TEXT PRIMARY KEY, per_page INTEGER, next_url TEXT, complete INTEGER, owner_id INTEGER);
            CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY, etag TEXT, body TEXT, next_url TEXT);
            CREATE TABLE IF NOT EXISTS items(owner TEXT, repository TEXT, body TEXT, PRIMARY KEY(owner, repository));
            CREATE TABLE IF NOT EXISTS limits(id INTEGER PRIMARY KEY CHECK(id=1), not_before REAL);
        """)
        if "owner_id" not in {row[1] for row in self.db.execute("PRAGMA table_info(runs)")}:
            self.db.execute("ALTER TABLE runs ADD COLUMN owner_id INTEGER")
            self.db.commit()

    def close(self):
        self.db.close()

    def gate(self, timestamp):
        with self.db:
            self.db.execute("INSERT INTO limits VALUES(1,?) ON CONFLICT(id) DO UPDATE SET not_before=MAX(not_before,excluded.not_before)", (timestamp,))

    def export(self, owner, prefix):
        rows = [json.loads(row[0]) for row in self.db.execute("SELECT body FROM items WHERE owner=? ORDER BY repository", (owner,))]
        run = self.db.execute("SELECT next_url,complete FROM runs WHERE owner=?", (owner,)).fetchone()
        if run is None:
            raise LabError("No collection exists for this owner.")
        payload = {"owner": owner, "complete": bool(run[1]), "count": len(rows), "repositories": rows}
        prefix = Path(prefix)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        json_path, csv_path = Path(str(prefix) + ".json"), Path(str(prefix) + ".csv")
        temp = Path(str(json_path) + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(json_path)
        temp = Path(str(csv_path) + ".tmp")
        with temp.open("w", newline="", encoding="utf-8-sig") as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows({key: spreadsheet_cell(row[key]) for key in FIELDS} for row in rows)
        temp.replace(csv_path)
        return {"owner": owner, "complete": payload["complete"], "count": len(rows), "json": str(json_path), "csv": str(csv_path)}


class Collector:
    def __init__(self, policy, store, transport=None, interval=1.0, clock=time.time, sleep=time.sleep):
        if not 1 <= interval <= 60:
            raise LabError("Interval must be between 1 and 60 seconds.")
        self.policy, self.store = policy, store
        self.transport = transport or build_opener(NoRedirect()).open
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.last_request = None

    def validate_url(self, url, owner, per_page, owner_id=None):
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        expected = {"type": ["owner"], "sort": ["full_name"], "direction": ["asc"], "per_page": [str(per_page)]}
        page = query.pop("page", [])
        paths = {f"/users/{owner}/repos"}
        if type(owner_id) is int and owner_id > 0:
            paths.add(f"/user/{owner_id}/repos")
        if parts.scheme != "https" or parts.netloc != "api.github.com" or parts.path not in paths or parts.fragment or query != expected or len(page) != 1 or not re.fullmatch(r"[1-9][0-9]{0,5}", page[0]):
            raise LabError("Pagination URL escaped the approved endpoint.")

    def fetch(self, url):
        gate = self.store.db.execute("SELECT not_before FROM limits WHERE id=1").fetchone()
        if gate and gate[0] > self.clock():
            raise LabError(f"Persistent cooldown active until UTC epoch {gate[0]:.0f}.")
        if self.last_request is not None:
            self.sleep(max(0, self.interval - (self.clock() - self.last_request)))
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "python-workflow-automation-lab/1.1"}
        cached = self.store.db.execute("SELECT etag,body,next_url FROM pages WHERE url=?", (url,)).fetchone()
        if cached and cached[0]:
            headers["If-None-Match"] = cached[0]
        self.last_request = self.clock()
        try:
            with self.transport(Request(url, headers=headers, method="GET"), timeout=15) as response:
                if response.status != 200:
                    raise LabError(f"Unexpected HTTP status {response.status}.")
                body = response.read(5_000_001)
                if len(body) > 5_000_000:
                    raise LabError("Page exceeded the five-megabyte response limit.")
                data = json.loads(body)
                if response.headers.get("X-RateLimit-Remaining") == "0":
                    self.set_cooldown(response.headers)
                return data, response.headers.get("ETag"), next_link(response.headers.get("Link", ""))
        except HTTPError as exc:
            if exc.code == 304 and cached:
                if exc.headers.get("X-RateLimit-Remaining") == "0":
                    self.set_cooldown(exc.headers)
                return json.loads(cached[1]), cached[0], cached[2]
            if exc.code in {403, 429}:
                self.set_cooldown(exc.headers)
                raise LabError("API refusal or rate limit: checkpoint preserved; persistent cooldown set; no retry.") from None
            raise LabError(f"GitHub returned HTTP {exc.code}; checkpoint preserved; no retry.") from None
        except (URLError, OSError, ValueError) as exc:
            raise LabError(f"Collection failed ({type(exc).__name__}); checkpoint preserved; no retry.") from None

    def set_cooldown(self, headers):
        now = self.clock()
        values = [now + 60]
        for key, offset in (("Retry-After", now), ("X-RateLimit-Reset", 0)):
            try:
                values.append(float(headers.get(key, "0")) + offset)
            except (ValueError, TypeError):
                pass
        self.store.gate(max(values))

    def collect(self, owner, per_page=30, max_pages=5, refresh=False):
        owner = owner.lower()
        self.policy.validate(f"{owner}/scope-check")
        if not 1 <= per_page <= 100 or not 1 <= max_pages <= 20:
            raise LabError("Use per_page 1–100 and max_pages 1–20.")
        query = urlencode({"type": "owner", "sort": "full_name", "direction": "asc", "per_page": per_page, "page": 1})
        first_url = f"https://api.github.com/users/{owner}/repos?{query}"
        with self.store.db:
            if refresh:
                self.store.db.execute("DELETE FROM items WHERE owner=?", (owner,))
                self.store.db.execute("DELETE FROM runs WHERE owner=?", (owner,))
            self.store.db.execute("INSERT OR IGNORE INTO runs(owner,per_page,next_url,complete) VALUES(?,?,?,0)", (owner, per_page, first_url))
        run = self.store.db.execute("SELECT per_page,next_url,complete,owner_id FROM runs WHERE owner=?", (owner,)).fetchone()
        if run[0] != per_page:
            raise LabError("Page size differs from checkpoint; reuse it or use --refresh.")
        url, complete, pages = run[1], bool(run[2]), 0
        owner_id = run[3]
        seen = set()
        while not complete and pages < max_pages:
            self.validate_url(url, owner, per_page, owner_id)
            if url in seen:
                raise LabError("Pagination cycle detected; checkpoint preserved.")
            seen.add(url)
            data, etag, following = self.fetch(url)
            if not isinstance(data, list) or len(data) > per_page:
                raise LabError("Unexpected repository page schema.")
            rows = []
            for item in data:
                if not isinstance(item, dict):
                    raise LabError("Unexpected repository item schema.")
                name = item.get("full_name", "")
                if not isinstance(name, str) or not isinstance(item.get("license") or {}, dict):
                    raise LabError("Unexpected repository metadata schema.")
                self.policy.validate(name)
                if name.split("/")[0].lower() != owner or item.get("private") is not False:
                    raise LabError("Response escaped the public owner scope.")
                identity = item.get("owner")
                if not isinstance(identity, dict) or str(identity.get("login", "")).lower() != owner or type(identity.get("id")) is not int or identity["id"] <= 0:
                    raise LabError("Repository owner identity is missing or invalid.")
                if owner_id is not None and owner_id != identity["id"]:
                    raise LabError("Repository owner ID changed during collection.")
                owner_id = identity["id"]
                rows.append({"repository": name, "description": item.get("description"), "language": item.get("language"), "license": (item.get("license") or {}).get("spdx_id"), "archived": bool(item.get("archived")), "fork": bool(item.get("fork")), "default_branch": item.get("default_branch"), "pushed_at": item.get("pushed_at")})
            if following:
                self.validate_url(following, owner, per_page, owner_id)
                if following in seen:
                    raise LabError("Pagination cycle detected; checkpoint preserved.")
            with self.store.db:
                self.store.db.execute("INSERT OR REPLACE INTO pages VALUES(?,?,?,?)", (url, etag, json.dumps(data), following))
                self.store.db.executemany("INSERT OR REPLACE INTO items VALUES(?,?,?)", [(owner, row["repository"], json.dumps(row)) for row in rows])
                self.store.db.execute("UPDATE runs SET next_url=?,complete=?,owner_id=? WHERE owner=?", (following, int(following is None), owner_id, owner))
            pages += 1
            url, complete = following, following is None
        return {"owner": owner, "pages_requested": pages, "complete": complete}


def demo_transport(request, timeout):
    parts = urlsplit(request.full_url)
    owner = parts.path.split("/")[2]
    query = parse_qs(parts.query)
    page, size = int(query["page"][0]), int(query["per_page"][0])
    records = [{"full_name": f"{owner}/{name}", "owner": {"login": owner, "id": 123}, "private": False, "description": "Offline study fixture", "language": "Python", "license": {"spdx_id": "MIT"}} for name in ("api-lab", "process-lab", "queue-lab")]
    response = io.BytesIO(json.dumps(records[(page - 1) * size:page * size]).encode())
    response.status = 200
    response.headers = {"ETag": f'"demo-{page}"'}
    if page * size < len(records):
        query["page"] = [str(page + 1)]
        following = f"https://api.github.com{parts.path}?{urlencode(query, doseq=True)}"
        response.headers["Link"] = f'<{following}>; rel="next"'
    return response
