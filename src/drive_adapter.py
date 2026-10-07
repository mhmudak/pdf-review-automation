from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from google_auth import get_credentials

PDF_MIME = "application/pdf"


@dataclass(frozen=True)
class DrivePdf:
    file_id: str
    name: str
    modified_time: str
    size: int
    md5_checksum: str
    web_view_link: str


class DriveAdapter:
    def __init__(self) -> None:
        self.service = build("drive", "v3", credentials=get_credentials(), cache_discovery=False)

    def list_pdfs(self, folder_id: str) -> list[DrivePdf]:
        q = f"'{folder_id}' in parents and trashed = false and mimeType = '{PDF_MIME}'"
        fields = "nextPageToken,files(id,name,modifiedTime,size,md5Checksum,webViewLink)"
        items: list[DrivePdf] = []
        token = None
        while True:
            response = (
                self.service.files()
                .list(
                    q=q,
                    fields=fields,
                    pageToken=token,
                    pageSize=1000,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            for f in response.get("files", []):
                items.append(
                    DrivePdf(
                        file_id=f["id"],
                        name=f["name"],
                        modified_time=f.get("modifiedTime", ""),
                        size=int(f.get("size", 0) or 0),
                        md5_checksum=f.get("md5Checksum", ""),
                        web_view_link=f.get("webViewLink", ""),
                    )
                )
            token = response.get("nextPageToken")
            if not token:
                break
        return sorted(items, key=lambda x: (x.modified_time, x.name, x.file_id))

    def download(self, file_id: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        with destination.open("wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=4 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return destination
