"""Start standalone or as a Home Assistant app without logging credentials."""
import json
import os
from pathlib import Path

import uvicorn


def configure(environ, options_path=Path("/data/options.json")):
    options = json.loads(options_path.read_text()) if options_path.exists() else {}
    level = options.get("log_level", "info")
    if level not in {"debug", "info", "warning", "error"}:
        raise ValueError("Ogiltig loggnivå")
    if environ.get("SUPERVISOR_TOKEN"):
        environ.setdefault("HA_URL", "http://supervisor/core")
        environ["INGRESS_ONLY"] = "true"
        # HA authentication protects Ingress; a standalone token is not needed.
        environ.pop("APP_TOKEN", None)
    return level


def drop_privileges(directory):
    if os.geteuid() != 0:
        return
    uid = gid = 10001
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    os.chown(root, uid, gid)
    # Supervisor creates the data volume as root. Keep its options untouched.
    for child in root.iterdir():
        if child.is_file() and (child.name.startswith("predictor.sqlite3") or child.suffix in {".joblib", ".tmp"}):
            os.chown(child, uid, gid)
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)


def main():
    level = configure(os.environ)
    directory = os.environ.setdefault("DATA_DIR", "/data")
    drop_privileges(directory)
    uvicorn.run("app.main:create_app", factory=True, host="0.0.0.0", port=8080,
                log_level=level, proxy_headers=False)


if __name__ == "__main__":
    main()
