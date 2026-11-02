import httpx

from ..config import get_settings
from .parsing import TEXT_EXT

MAX_FILES = 300
MAX_BYTES = 200_000
API = "https://api.github.com"


def _headers(token: str) -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch_repo(repo: str, branch: str | None = None, token: str = ""):
    """Yield (path, html_url, text) for text/code files in a repo (owner/name)."""
    token = token or get_settings().github_token
    with httpx.Client(headers=_headers(token), timeout=30) as c:
        if not branch:
            r = c.get(f"{API}/repos/{repo}")
            r.raise_for_status()
            branch = r.json()["default_branch"]
        r = c.get(f"{API}/repos/{repo}/git/trees/{branch}", params={"recursive": "1"})
        r.raise_for_status()
        entries = [
            e
            for e in r.json().get("tree", [])
            if e["type"] == "blob"
            and e.get("size", 0) <= MAX_BYTES
            and any(e["path"].lower().endswith(x) for x in TEXT_EXT)
        ][:MAX_FILES]
        for e in entries:
            raw = c.get(
                f"{API}/repos/{repo}/contents/{e['path']}",
                params={"ref": branch},
                headers={"Accept": "application/vnd.github.raw+json"},
            )
            if raw.status_code != 200:
                continue
            yield e["path"], f"https://github.com/{repo}/blob/{branch}/{e['path']}", raw.text
