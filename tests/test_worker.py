import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Runs in a separate interpreter: the rest of the suite imports app with DASH_NO_WORKER=1.
PROBE = """
import app, builder
with builder.COND:
    done = builder.COND.wait_for(lambda: builder.META["seq"] >= 1, timeout=20)
print("PROBE", done, ",".join(sorted(builder.STATE["errors"])), builder.STATE["health"]["sources"]["db"]["ok"])
"""


def test_import_starts_the_worker_and_completes_a_cycle(tmp_path):
    """Production imports app with the worker on: logging setup, start-up log line and a first poll cycle."""
    env = {k: v for k, v in os.environ.items() if k != "DASH_NO_WORKER"}
    env.update(HA_URL="", HA_TOKEN="", OPAL_HOST="", LOG_FILE="", NETMAP_LANG="en", PYTHONPATH=str(ROOT),
               DB_PATH=str(tmp_path / "n.db"), NAMES_FILE=str(tmp_path / "names.json"),
               META_FILE=str(tmp_path / "meta.json"))
    run = subprocess.run([sys.executable, "-c", PROBE], cwd=tmp_path, env=env, capture_output=True, text=True,
                         timeout=60)
    assert run.returncode == 0, run.stderr
    probe = [line for line in run.stdout.splitlines() if line.startswith("PROBE ")]
    # HA is not configured, so only the router source fails; Opal is disabled and the database is healthy
    assert probe == ["PROBE True Home Assistant · AX55 True"], run.stdout + run.stderr
