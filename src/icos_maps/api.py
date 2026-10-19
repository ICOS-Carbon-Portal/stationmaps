"""REST interface: build status, on-demand rebuilds, and single maps rendered with custom options.

Runs in the app container behind nginx at /api. A worker thread runs one build at a time (from the
nightly schedule or POST /builds) and publishes it as a new release of the static site; rendering a
single map shares the same lock, since matplotlib is not thread-safe.
"""

import contextlib
import hashlib
import json
import os
import queue
import secrets
import shutil
import threading
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .config import MEMBERS

SITE = Path(os.environ.get("SITE_DIR", "/data/site"))
WORK = Path(os.environ.get("WORK_DIR", "/data/work"))
RENDER_CACHE = WORK / "render-cache"
BUILD_AT = os.environ.get("BUILD_AT", "03:00")  # UTC
KEEP_RELEASES = int(os.environ.get("KEEP_RELEASES", "3"))
API_TOKEN = os.environ.get("API_TOKEN", "")
MAX_BUILDS_KEPT = 20

@contextlib.asynccontextmanager
async def lifespan(_app):
    ensure_placeholder()
    threading.Thread(target=worker, daemon=True, name="build-worker").start()
    threading.Thread(target=scheduler, daemon=True, name="scheduler").start()
    enqueue([], True, "startup")
    yield


app = FastAPI(
    lifespan=lifespan,
    title="ICOS Station Maps API",
    description="Status of the ICOS station maps, on-demand rebuilds, and single maps rendered with custom options. "
                "Starting a build needs a bearer token.",
    root_path="/api",
)
lock = threading.Lock()  # one build or render at a time
jobs: "queue.Queue[Build]" = queue.Queue()
builds: dict[str, "Build"] = {}
_network = None  # station data for on-demand renders, reloaded after each build


@dataclass
class Build:
    id: str
    countries: list[str]
    refresh: bool
    trigger: str
    state: Literal["queued", "running", "succeeded", "failed"] = "queued"
    created: str = field(default_factory=lambda: _now())
    started: str | None = None
    finished: str | None = None
    release: str | None = None
    error: str | None = None

    @property
    def log(self) -> Path:
        return WORK / "build-logs" / f"{self.id}.log"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current() -> Path:
    return SITE / "current"


def _manifest() -> dict:
    path = _current() / "manifest.json"
    if not path.exists():
        raise HTTPException(503, "No maps published yet; the first build is still running.")
    return json.loads(path.read_text())


# ---------- Builds ----------

def publish() -> str:
    """Copy the build output into a new release and switch the site to it atomically."""
    release = SITE / "releases" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copytree(WORK / "web", release)
    shutil.copy(WORK / "CHANGES.txt", release / "CHANGES.txt")
    tmp = SITE / "current.tmp"
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(release)
    tmp.replace(SITE / "current")
    for old in sorted((SITE / "releases").glob("2*"), reverse=True)[KEEP_RELEASES:]:
        shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(SITE / "releases" / "placeholder", ignore_errors=True)
    return release.name


def run_build(b: Build):
    global _network
    from .build import build

    b.state, b.started = "running", _now()
    b.log.parent.mkdir(parents=True, exist_ok=True)
    with lock, open(b.log, "w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            build(WORK, b.countries or list(MEMBERS), ["svg", "pdf", "png"], b.refresh, overview=True)
            b.release = publish()
            b.state = "succeeded"
            _network = None
            shutil.rmtree(RENDER_CACHE, ignore_errors=True)
        except Exception as e:  # keep the previous site online
            traceback.print_exc()
            b.state, b.error = "failed", f"{type(e).__name__}: {e}"
    b.finished = _now()
    print(f"{b.finished} build {b.id} ({b.trigger}) {b.state}" + (f", release {b.release}" if b.release else ""), flush=True)


def worker():
    while True:
        run_build(jobs.get())


def enqueue(countries: list[str], refresh: bool, trigger: str) -> Build:
    b = Build(id=uuid.uuid4().hex[:12], countries=countries, refresh=refresh, trigger=trigger)
    builds[b.id] = b
    for old in list(builds)[:-MAX_BUILDS_KEPT]:
        builds.pop(old, None)
    jobs.put(b)
    return b


def next_scheduled(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    hh, mm = map(int, BUILD_AT.split(":"))
    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return t if t > now else t + timedelta(days=1)


def scheduler():
    while True:
        wait = (next_scheduled() - datetime.now(timezone.utc)).total_seconds()
        threading.Event().wait(max(wait, 1))
        enqueue([], True, "schedule")


def ensure_placeholder():
    if _current().exists():
        return
    placeholder = SITE / "releases" / "placeholder"
    placeholder.mkdir(parents=True, exist_ok=True)
    (placeholder / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>ICOS Station Maps</title>'
        "<p>The maps are being built, try again in a few minutes.</p>\n")
    _current().symlink_to(placeholder)


bearer = HTTPBearer(auto_error=False)


def require_token(creds: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not API_TOKEN:
        raise HTTPException(403, "Builds over the API are disabled: no API_TOKEN configured.")
    if creds is None or not secrets.compare_digest(creds.credentials, API_TOKEN):
        raise HTTPException(401, "Missing or wrong bearer token.", headers={"WWW-Authenticate": "Bearer"})


class BuildRequest(BaseModel):
    countries: list[str] = Field(default_factory=list, description="Member country codes; empty for all 16.")
    refresh: bool = Field(True, description="Re-download station metadata and ocean tracks first.")


# ---------- Endpoints ----------

@app.get("/", summary="Index")
def index(request: Request):
    base = str(request.base_url).rstrip("/")
    return {"docs": f"{base}/docs", "status": f"{base}/status", "countries": f"{base}/countries",
            "builds": f"{base}/builds", "map": f"{base}/maps/{{country}}/{{panel}}.{{png|svg|pdf}}"}


@app.get("/status", summary="Published maps and build schedule")
def status():
    current = _current().resolve() if _current().exists() else None
    m = json.loads((current / "manifest.json").read_text()) if current and (current / "manifest.json").exists() else {}
    running = next((asdict(b) for b in builds.values() if b.state in ("queued", "running")), None)
    changes = (current / "CHANGES.txt").read_text().splitlines() if current and (current / "CHANGES.txt").exists() else []
    return {"release": current.name if current else None, "generated": m.get("generated"),
            "n_stations": m.get("n_stations"), "next_scheduled_build": next_scheduled().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "active_build": running, "changes": changes}


@app.get("/countries", summary="Member countries with their map panels")
def countries():
    m = _manifest()
    return {cc: {"name": c["name"], "stations": c["stations"], "by_theme": c.get("by_theme"),
                 "panels": [{"key": p["key"], "kind": p["kind"], "title": p["title"], "files": p["files"]} for p in c["panels"]]}
            for cc, c in m["countries"].items()}


@app.get("/countries/{cc}", summary="One country: panels and station table")
def country(cc: str):
    cc = cc.upper()
    m = _manifest()
    if cc not in m["countries"]:
        raise HTTPException(404, f"Unknown country {cc}; choose from {', '.join(m['countries'])}.")
    tables = json.loads((_current() / "tables.json").read_text())
    return {**m["countries"][cc], "stations_table": tables.get(cc, [])}


@app.get("/builds", summary="Recent builds")
def list_builds():
    return [asdict(b) for b in reversed(builds.values())]


@app.post("/builds", status_code=202, dependencies=[Depends(require_token)], summary="Start a build (token required)")
def start_build(req: BuildRequest):
    unknown = [c for c in req.countries if c.upper() not in MEMBERS]
    if unknown:
        raise HTTPException(422, f"Not ICOS members: {', '.join(unknown)}.")
    active = next((b for b in builds.values() if b.state in ("queued", "running")), None)
    if active:
        raise HTTPException(409, {"message": "A build is already queued or running.", "build": asdict(active)})
    return asdict(enqueue([c.upper() for c in req.countries], req.refresh, "api"))


@app.get("/builds/{build_id}", summary="One build, with the end of its log")
def get_build(build_id: str, log_lines: int = Query(40, ge=0, le=1000)):
    b = builds.get(build_id)
    if not b:
        raise HTTPException(404, "Unknown build (only the most recent builds are kept).")
    log = b.log.read_text().splitlines()[-log_lines:] if b.log.exists() and log_lines else []
    return {**asdict(b), "log": log}


@app.get("/maps/{cc}/{panel}.{fmt}", summary="A single map, optionally rendered with custom options",
         response_class=FileResponse)
def get_map(cc: str, panel: str, fmt: Literal["png", "svg", "pdf"],
            dpi: int = Query(300, ge=72, le=600, description="PNG resolution."),
            marker_scale: float = Query(1.0, ge=0.5, le=3.0, description="Multiplier for the station marker size.")):
    """Default options redirect to the published file; other options render the map on request
    (a few seconds) and cache it until the next build."""
    cc, panel = cc.upper(), panel.lower()
    m = _manifest()
    entry = m["countries"].get(cc)
    p = next((p for p in (entry or {}).get("panels", []) if p["key"] == panel), None)
    if p is None:
        raise HTTPException(404, f"No panel {panel!r} for {cc}.")
    if dpi == 300 and marker_scale == 1.0 and fmt in p["files"]:
        return RedirectResponse(f"/{p['files'][fmt]}", status_code=307)

    key = hashlib.sha256(json.dumps([m["generated"], cc, panel, fmt, dpi, marker_scale]).encode()).hexdigest()[:16]
    out = RENDER_CACHE / f"{cc}_{panel}_{key}.{fmt}"
    if not out.exists():
        if not lock.acquire(timeout=120):
            raise HTTPException(503, "Busy with a build; try again shortly.", headers={"Retry-After": "60"})
        try:
            render_one(cc, panel, out, fmt, dpi, marker_scale)
        finally:
            lock.release()
    return FileResponse(out, filename=f"{cc}_{panel}_{p['kind']}.{fmt}")


def render_one(cc, panel, out: Path, fmt, dpi, marker_scale):
    global _network
    from .build import load_network, number_stations
    from .layout import plan_country
    from .render import render_panel, setup_fonts

    setup_fonts()
    if _network is None:
        _network = load_network(refresh=False)
    st = _network[_network["member"] == cc]
    mapped = st[st["has_geometry"]]
    p = next(p for p in plan_country(cc, mapped) if p.key == panel)
    out.parent.mkdir(parents=True, exist_ok=True)
    render_panel(p, cc, mapped, number_stations(st), out.with_suffix(""), [fmt], dpi=dpi, marker_scale=marker_scale)


def main():
    import uvicorn

    uvicorn.run("icos_maps.api:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("API_PORT", "8000")),
                proxy_headers=True, forwarded_allow_ips="*")
