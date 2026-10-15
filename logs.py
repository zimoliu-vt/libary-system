
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone

LOG_FILE = Path(__file__).with_name("logs.json")


def load_logs():
    if not LOG_FILE.exists():
        return []

    with open(LOG_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_logs(logs):
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".logs-", suffix=".json.tmp", dir=LOG_FILE.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            json.dump(logs, temporary_file, indent=4)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, LOG_FILE)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def add_log(action, book):
    logs = load_logs()

    log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "book_id": book["id"],
        "title": book["title"],
        "author": book["author"]
    }

    logs.append(log)
    save_logs(logs)


def get_logs():
    return load_logs()
