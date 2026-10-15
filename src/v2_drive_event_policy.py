"""Drive observation decisions for PDF Review Automation V2.

Pure logic. The caller must store observations durably.
No Drive, Sheets, SMTP or other network operations.
"""

from hashlib import sha256


def observe_pdf(file_metadata, previous=None, *, initialized=False):
    """Classify a PDF observation across scheduled runs.

    initialized=True means the folder observation baseline
    has already been established.

    previous must be a persisted observation of the same
    Drive file ID, or None for an unseen file.
    """
    file_id = str(file_metadata.get("id") or "").strip()
    modified = str(
        file_metadata.get("modifiedTime") or ""
    ).strip()
    mime = str(file_metadata.get("mimeType") or "").strip()

    if not file_id or not modified:
        raise ValueError("Drive file identity and modifiedTime required")

    if mime and mime != "application/pdf":
        raise ValueError("Only PDF observations are supported")

    checksum = str(
        file_metadata.get("md5Checksum") or ""
    ).strip().lower()

    # Drive versions are not sufficient evidence of new PDF
    # content: metadata changes can also increment versions.
    observation = {
        "file_id": file_id,
        "modified_time": modified,
        "md5_checksum": checksum,
    }

    token = sha256(
        ("\\x1f".join([
            file_id, modified, checksum
        ])).encode("utf-8")
    ).hexdigest()

    observation["event_id"] = token

    if previous is None:
        if not initialized:
            action = "INITIAL_BASELINE"
        else:
            action = "NEW_FILE_OBSERVED"
    else:
        if str(previous.get("file_id") or "") != file_id:
            raise ValueError("Previous observation belongs to another file")

        if str(previous.get("event_id") or "") == token:
            action = "NO_CHANGE"
        else:
            action = "FILE_MODIFIED"

    return {
        "action": action,
        "new_event": action in {
            "NEW_FILE_OBSERVED", "FILE_MODIFIED"
        },
        "observation": observation,
    }
