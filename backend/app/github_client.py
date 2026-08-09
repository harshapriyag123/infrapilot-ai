import base64
import re
import io
import tarfile
import json
import os
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import httpx

from .config import get_settings

# Simple in-memory metrics
CACHE_HITS = 0
NETWORK_FETCHES = 0
FILE_FETCHES = 0

def get_metrics():
    return {"cache_hits": CACHE_HITS, "network_fetches": NETWORK_FETCHES, "file_fetches": FILE_FETCHES}


@dataclass
class RepoSnapshot:
    owner: str
    repo: str
    default_branch: str
    description: str | None
    files: list[str]
    contents: dict[str, str]


def parse_github_url(url: str) -> tuple[str, str]:
    match = re.match(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)", url.strip())
    if not match:
        raise ValueError("Please enter a GitHub repository URL such as https://github.com/owner/repo")
    owner, repo = match.group(1), match.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


class GitHubClient:
    API = "https://api.github.com"
    TIMEOUT = 25

    def __init__(self):
        settings = get_settings()
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "InfraPilot-AI/1.0",
        }
        if settings.github_token:
            self.headers["Authorization"] = f"Bearer {settings.github_token}"

    def _get_json(self, client: httpx.Client, path: str):
        response = client.get(f"{self.API}{path}")
        if response.status_code == 404:
            raise ValueError("Repository not found or not accessible.")
        if response.status_code == 403:
            raise ValueError("GitHub API rate limit reached. Set GITHUB_TOKEN and retry.")
        response.raise_for_status()
        return response.json()

    def _fetch_file(self, client: httpx.Client, owner: str, repo: str, branch: str, path: str):
        try:
            response = client.get(f"{self.API}/repos/{owner}/{repo}/contents/{path}?ref={branch}")
            if response.status_code != 200:
                return None
            data = response.json()
            if data.get("encoding") == "base64" and data.get("content"):
                raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                return path, raw
        except Exception:
            return None
        return None

    def snapshot(self, repo_url: str, progress_callback=None) -> RepoSnapshot:
        owner, repo = parse_github_url(repo_url)
        settings = get_settings()
        # simple on-disk cache to avoid repeated network calls during development
        cache_ttl = settings.github_cache_ttl_seconds_value
        cache_dir = Path(settings.github_cache_dir_value)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = None
        # Note: branch value will be set after reading meta; we compute key later if needed
        with httpx.Client(timeout=self.TIMEOUT, headers=self.headers, follow_redirects=True) as client:
            meta = self._get_json(client, f"/repos/{owner}/{repo}")
            branch = meta.get("default_branch") or "main"
            # Resolve the commit SHA for the branch to use as a stable cache key
            try:
                commit_json = self._get_json(client, f"/repos/{owner}/{repo}/commits/{branch}")
                commit_sha = commit_json.get("sha")
            except Exception:
                commit_sha = None
            cache_key = f"{owner}__{repo}__{commit_sha or branch}"
            cache_path = cache_dir / f"{cache_key}.json"
            if cache_path.exists():
                try:
                    mtime = cache_path.stat().st_mtime
                    if time.time() - mtime < cache_ttl:
                        with cache_path.open("r", encoding="utf-8") as fh:
                            data = json.load(fh)
                        # cache hit
                        global CACHE_HITS
                        CACHE_HITS += 1
                        if progress_callback:
                            progress_callback({"event": "cache_hit", "key": cache_path.name})
                        return RepoSnapshot(
                            owner=data.get("owner"),
                            repo=data.get("repo"),
                            default_branch=data.get("default_branch"),
                            description=data.get("description"),
                            files=data.get("files", []),
                            contents=data.get("contents", {}),
                        )
                except Exception:
                    # fall through to refresh cache
                    pass
            # Optionally use tarball download which is generally faster for large public repos.
            is_private = bool(meta.get("private", False))
            if settings.github_use_tarball_value and not is_private:
                # network tarball fetch
                global NETWORK_FETCHES
                NETWORK_FETCHES += 1
                if progress_callback:
                    progress_callback({"event": "network_fetch_start", "type": "tarball"})
                snapshot = self._snapshot_from_tarball(client, owner, repo, commit_sha or branch, meta)
                # persist cache
                try:
                    cache_path = cache_dir / f"{cache_key}.json"
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    with cache_path.open("w", encoding="utf-8") as fh:
                        json.dump({
                            "owner": snapshot.owner,
                            "repo": snapshot.repo,
                            "default_branch": snapshot.default_branch,
                            "description": snapshot.description,
                            "files": snapshot.files,
                            "contents": snapshot.contents,
                        }, fh)
                except Exception:
                    pass
                return snapshot
            tree = self._get_json(client, f"/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
        entries = tree.get("tree") or []
        files = [entry["path"] for entry in entries if entry.get("type") == "blob"][:5000]

        # Pull only small/high-signal configuration files.
        interesting_names = {
            "package.json", "requirements.txt", "pyproject.toml", "Pipfile",
            "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
            ".env.example", ".env.sample", ".env.template", "example.env", "Procfile", "go.mod", "pom.xml",
            "build.gradle", "build.gradle.kts", "Cargo.toml", "Gemfile",
            "manage.py", "alembic.ini", "vite.config.js", "vite.config.ts",
            "next.config.js", "next.config.mjs", "next.config.ts",
            "nuxt.config.ts", "angular.json", "zerops.yaml", "zerops.yml",
        }
        important_dirs = (
            "apps/", "api/", "backend/", "frontend/", "services/", "packages/",
            "workers/", "server/", "client/", "web/",
        )

        candidates = []
        for path in files:
            name = path.split("/")[-1]
            if name in interesting_names or name.startswith("Dockerfile"):
                candidates.append(path)
            elif name in {"main.py", "app.py", "server.py", "index.js", "index.ts", "manage.py"}:
                if any(path.startswith(prefix) for prefix in important_dirs) or path.count("/") <= 4:
                    candidates.append(path)

        contents = {}
        # Fetch file contents in parallel using a single shared httpx.Client.
        settings = get_settings()
        limit = 12
        max_workers = min(settings.github_parallel_fetch_value, max(2, len(candidates[:limit])))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            with httpx.Client(timeout=self.TIMEOUT, headers=self.headers, follow_redirects=True) as client:
                futures = {
                    executor.submit(self._fetch_file, client, owner, repo, branch, path): path
                    for path in candidates[:limit]
                }
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        path, raw = result
                        global FILE_FETCHES
                        FILE_FETCHES += 1
                        if progress_callback:
                            try:
                                progress_callback({"event": "file_fetched", "path": path})
                            except Exception:
                                pass
                        contents[path] = raw[:100_000]

        # write cache
        try:
            if cache_key is None:
                cache_key = f"{owner}__{repo}__{branch}"
            cache_path = cache_dir / f"{cache_key}.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("w", encoding="utf-8") as fh:
                json.dump({
                    "owner": owner,
                    "repo": repo,
                    "default_branch": branch,
                    "description": meta.get("description"),
                    "files": files,
                    "contents": contents,
                }, fh)
        except Exception:
            pass

        return RepoSnapshot(
            owner=owner,
            repo=repo,
            default_branch=branch,
            description=meta.get("description"),
            files=files,
            contents=contents,
        )

    def _snapshot_from_tarball(self, client: httpx.Client, owner: str, repo: str, branch: str, meta: dict) -> RepoSnapshot:
        """Download the repository tarball and extract interesting files without writing to disk."""
        url = f"{self.API}/repos/{owner}/{repo}/tarball/{branch}"
        files = []
        contents = {}
        try:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                bio = io.BytesIO(response.content)
                # GitHub returns a gzipped tarball
                try:
                    tf = tarfile.open(fileobj=bio, mode="r:gz")
                except tarfile.ReadError:
                    bio.seek(0)
                    tf = tarfile.open(fileobj=bio, mode="r:*")

                interesting_names = {
                    "package.json", "requirements.txt", "pyproject.toml", "Pipfile",
                    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
                    ".env.example", ".env.sample", ".env.template", "example.env", "Procfile", "go.mod", "pom.xml",
                    "build.gradle", "build.gradle.kts", "Cargo.toml", "Gemfile",
                    "manage.py", "alembic.ini", "vite.config.js", "vite.config.ts",
                    "next.config.js", "next.config.mjs", "next.config.ts",
                    "nuxt.config.ts", "angular.json", "zerops.yaml", "zerops.yml",
                }
                important_dirs = (
                    "apps/", "api/", "backend/", "frontend/", "services/", "packages/",
                    "workers/", "server/", "client/", "web/",
                )

                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    parts = member.name.split('/', 1)
                    if len(parts) == 2:
                        path = parts[1]
                    else:
                        path = parts[0]
                    files.append(path)
                    name = path.split('/')[-1]
                    should_capture = False
                    if name in interesting_names or name.startswith("Dockerfile"):
                        should_capture = True
                    elif name in {"main.py", "app.py", "server.py", "index.js", "index.ts", "manage.py"}:
                        if any(path.startswith(prefix) for prefix in important_dirs) or path.count('/') <= 4:
                            should_capture = True
                    if should_capture:
                        try:
                            f = tf.extractfile(member)
                            if f:
                                raw = f.read(100_000)
                                try:
                                    raw_text = raw.decode("utf-8", errors="replace")
                                except Exception:
                                    raw_text = str(raw)
                                contents[path] = raw_text
                        except Exception:
                            continue
        except Exception:
            # fallback to tree + per-file fetch on failure
            tree = self._get_json(client, f"/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
            entries = tree.get("tree") or []
            files = [entry["path"] for entry in entries if entry.get("type") == "blob"][:5000]
        return RepoSnapshot(
            owner=owner,
            repo=repo,
            default_branch=branch,
            description=meta.get("description"),
            files=files,
            contents=contents,
        )
