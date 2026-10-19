import argparse
from pathlib import Path

from .config import MEMBERS, ROOT


def main() -> None:
    parser = argparse.ArgumentParser(prog="icos-maps", description="Build ICOS station network maps from Carbon Portal metadata.")
    parser.add_argument("countries", nargs="*", default=list(MEMBERS), help="member country codes (default: all 16)")
    parser.add_argument("--out", type=Path, default=ROOT / "out")
    parser.add_argument("--formats", nargs="+", default=["svg", "pdf", "png"], choices=["svg", "pdf", "png"])
    parser.add_argument("--refresh", action="store_true", help="re-download station metadata and ocean tracks")
    parser.add_argument("--no-overview", action="store_true", help="skip the Europe overview map")
    args = parser.parse_args()

    unknown = [c for c in args.countries if c.upper() not in MEMBERS]
    if unknown:
        parser.error(f"not ICOS members: {', '.join(unknown)}; choose from {', '.join(MEMBERS)}")

    from .build import build

    build(args.out, [c.upper() for c in args.countries], args.formats, args.refresh, overview=not args.no_overview)
