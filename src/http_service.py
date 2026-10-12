from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from flask import Flask, jsonify

from pipeline import (
    bool_env,
    env_first,
    process_drive_folder,
)


app = Flask(__name__)

_run_lock = threading.Lock()


def _paths() -> tuple[Path, Path]:
    src_dir = Path(__file__).resolve().parent

    master_index = Path(
        env_first(
            "WORKFLOW2_MASTER_INDEX",
            default=str(
                src_dir / "master_page_index.json"
            ),
        )
    )

    config = Path(
        env_first(
            "WORKFLOW2_CONFIG",
            default=str(
                src_dir / "config.json"
            ),
        )
    )

    return master_index, config


def _run_pipeline() -> dict[str, Any]:
    folder_id = env_first(
        "WORKFLOW2_DRIVE_FOLDER_ID",
        "GOOGLE_DRIVE_FOLDER_ID",
    )

    backend_spreadsheet_id = env_first(
        "WORKFLOW2_SPREADSHEET_ID",
        "GOOGLE_SHEETS_SPREADSHEET_ID",
    )

    output_spreadsheet_id = env_first(
        "WORKFLOW2_OUTPUT_SPREADSHEET_ID",
        "OUTPUT_SPREADSHEET_ID",
    )

    dry_run = bool_env(
        "WORKFLOW2_DRY_RUN"
    )

    if not folder_id:
        raise RuntimeError(
            "Drive folder ID is required"
        )

    if not dry_run:
        if not backend_spreadsheet_id:
            raise RuntimeError(
                "Backend spreadsheet ID is required"
            )

        if not output_spreadsheet_id:
            raise RuntimeError(
                "Output spreadsheet ID is required"
            )

    master_index, config = _paths()

    return process_drive_folder(
        folder_id,
        backend_spreadsheet_id,
        output_spreadsheet_id,
        master_index,
        config,
        dry_run,
    )


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "pdf-review-automation",
        }
    ), 200


@app.get("/")
def root():
    return health()


@app.post("/run")
def run():
    if not _run_lock.acquire(
        blocking=False
    ):
        return jsonify(
            {
                "status": "busy",
                "message": (
                    "A synchronization is "
                    "already running."
                ),
            }
        ), 409

    try:
        result = _run_pipeline()

        return jsonify(
            {
                "status": "ok",
                "result": result,
            }
        ), 200

    except Exception as exc:
        app.logger.exception(
            "PDF review synchronization failed"
        )

        return jsonify(
            {
                "status": "error",
                "error": str(exc),
            }
        ), 500

    finally:
        _run_lock.release()


if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            "8080",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
    )
