import httpx

from ..config import get_settings
from .parsing import TEXT_EXT

MAX_FILES = 300
MAX_BYTES = 200_000
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
SKIP_PARTS = ("node_modules/", "/dist/", "/build/", "/.next/", "vendor/", ".min.")
SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock"}


def wanted(path: str, size: int) -> bool:
    low = path.lower()
    return (
        size <= MAX_BYTES
        and low.rsplit("/", 1)[-1] not in SKIP_NAMES
        and not any(p in f"/{low}" for p in SKIP_PARTS)
        and any(low.endswith(x) for x in TEXT_EXT)
    )


def _headers(token: str) -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch_repo(repo: str, branch: str | None = None, token: str = ""):
    """Yield (path, html_url, text) for text/code files in a repo (owner/name).

    Without a token, file bodies come from raw.githubusercontent.com, which does
    not consume the 60 requests/hour unauthenticated API limit (only the two
    metadata calls do). With a token, the contents API is used so private repos work.
    """
    token = token or get_settings().github_token
    with httpx.Client(headers=_headers(token), timeout=30, follow_redirects=True) as c:
        if not branch:
            r = c.get(f"{API}/repos/{repo}")
            r.raise_for_status()
            branch = r.json()["default_branch"]
        r = c.get(f"{API}/repos/{repo}/git/trees/{branch}", params={"recursive": "1"})
        r.raise_for_status()
        entries = [e for e in r.json().get("tree", []) if e["type"] == "blob" and wanted(e["path"], e.get("size", 0))]
        for e in entries[:MAX_FILES]:
            if token:
                raw = c.get(
                    f"{API}/repos/{repo}/contents/{e['path']}",
                    params={"ref": branch},
                    headers={"Accept": "application/vnd.github.raw+json"},
                )
            else:
                raw = c.get(f"{RAW}/{repo}/{branch}/{e['path']}", headers={})
            if raw.status_code != 200:
                continue
            yield e["path"], f"https://github.com/{repo}/blob/{branch}/{e['path']}", raw.text
