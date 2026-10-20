"""Köppen-Geiger climate zones for stations the Carbon Portal has none for.

Uses the 1 km map for 1991-2020 of Beck et al. (2023), https://doi.org/10.6084/m9.figshare.21789074
(CC BY 4.0). Only that one GeoTIFF and the legend are read out of the 130 MB archive, over HTTP range
requests, and cached.
"""

import io
import re
import zipfile

import numpy as np
import rasterio
import requests

from .config import CACHE

ARCHIVE_URL = "https://ndownloader.figshare.com/files/61012822"  # koppen_geiger_tif.zip
MEMBER = "1991_2020/koppen_geiger_0p00833333.tif"
CITATION = "Beck et al. (2023), Köppen-Geiger 1 km map 1991-2020, doi:10.6084/m9.figshare.21789074"
TIF = CACHE / "koppen_geiger_1991_2020_1km.tif"
LEGEND = CACHE / "koppen_geiger_legend.txt"


class _RangeFile(io.RawIOBase):
    """Read-only file over HTTP range requests (figshare redirects to short-lived signed URLs, so
    every read goes through the figshare link)."""

    def __init__(self, url: str):
        self.url, self.pos = url, 0
        self.size = int(self._get(0, 0).headers["Content-Range"].split("/")[1])

    def _get(self, start, end):
        r = requests.get(self.url, headers={"Range": f"bytes={start}-{end}"}, timeout=300)
        r.raise_for_status()
        return r

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        data = self._get(self.pos, min(self.pos + len(b), self.size) - 1).content
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def _download():
    CACHE.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BufferedReader(_RangeFile(ARCHIVE_URL), buffer_size=1 << 20)) as z:
        TIF.write_bytes(z.read(MEMBER))
        LEGEND.write_bytes(z.read("legend.txt"))


def legend() -> dict[int, tuple[str, str]]:
    """Raster value -> (code, description), e.g. 15 -> ("Cfb", "Temperate, no dry season, warm summer")."""
    out = {}
    for line in LEGEND.read_text().splitlines():
        m = re.match(r"\s*(\d+):\s+(\w+)\s+(.+?)\s+\[", line)
        if m:
            out[int(m.group(1))] = (m.group(2), m.group(3).strip())
    return out


def zones(lons, lats) -> list[tuple[str, str] | None]:
    """(code, description) at each position; None at sea or without a position."""
    if not TIF.exists() or not LEGEND.exists():
        _download()
    names = legend()
    pts = [(float(x), float(y)) for x, y in zip(lons, lats)]
    ok = [np.isfinite(x) and np.isfinite(y) for x, y in pts]
    with rasterio.open(TIF) as src:
        values = [int(v[0]) for v in src.sample([p for p, k in zip(pts, ok) if k])]
    it = iter(values)
    return [names.get(next(it)) if k else None for k in ok]
