import io

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from ..config import get_settings
from .parsing import extract_text

MAX_BYTES = 5_000_000
MAX_FILES = 500
EXPORT = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
}
DOWNLOAD = {"application/pdf": ".pdf", "text/plain": ".txt", "text/markdown": ".md", "text/csv": ".csv"}
FIELDS = (
    "nextPageToken, files(id,name,mimeType,webViewLink,modifiedTime,size,"
    "owners(emailAddress),permissions(type,emailAddress,domain,role,allowFileDiscovery))"
)


def _service(refresh_token: str):
    s = get_settings()
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _download(svc, request) -> bytes:
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = dl.next_chunk()
        if buf.tell() > MAX_BYTES:
            raise ValueError("file too large")
    return buf.getvalue()


def list_files(refresh_token: str):
    """Yield (file_metadata, text) for every readable Drive file."""
    svc = _service(refresh_token)
    mimes = list(EXPORT) + list(DOWNLOAD)
    q = "trashed = false and (" + " or ".join(f"mimeType = '{m}'" for m in mimes) + ")"
    token, n = None, 0
    while n < MAX_FILES:
        res = svc.files().list(q=q, fields=FIELDS, pageSize=100, pageToken=token, orderBy="modifiedTime desc").execute()
        for f in res.get("files", []):
            n += 1
            try:
                mime = f["mimeType"]
                if mime in EXPORT:
                    data = _download(svc, svc.files().export_media(fileId=f["id"], mimeType=EXPORT[mime]))
                    text = data.decode("utf-8", errors="replace")
                else:
                    if int(f.get("size", 0)) > MAX_BYTES:
                        continue
                    data = _download(svc, svc.files().get_media(fileId=f["id"]))
                    text = extract_text(f["name"] + DOWNLOAD[mime], data)
            except Exception:
                continue  # unreadable file: skip, don't fail the whole sync
            yield f, text
        token = res.get("nextPageToken")
        if not token:
            break
