from __future__ import annotations

from google.auth import default
from google.auth.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]


def get_credentials() -> Credentials:
    """Application Default Credentials.

    Local dev: `gcloud auth application-default login`.
    Cloud Run: automatically uses the attached service account.
    """
    credentials, _ = default(scopes=SCOPES)
    return credentials
