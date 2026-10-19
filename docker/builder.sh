#!/bin/sh
# Build the maps now, then every day at BUILD_AT (UTC).
# Each build becomes a release directory; the `current` symlink is swapped atomically,
# so nginx never serves a half-written site.
set -u

BUILD_AT="${BUILD_AT:-03:00}"
KEEP_RELEASES="${KEEP_RELEASES:-3}"
WORK=/data/work
SITE=/data/site

mkdir -p "$WORK" "$SITE/releases"

if [ ! -e "$SITE/current" ]; then
    mkdir -p "$SITE/releases/placeholder"
    printf '<!doctype html><meta charset="utf-8"><title>ICOS Station Maps</title><p>The maps are being built, try again in a few minutes.</p>\n' \
        > "$SITE/releases/placeholder/index.html"
    ln -sfn "$SITE/releases/placeholder" "$SITE/current"
fi

publish() {
    release="$SITE/releases/$(date -u +%Y%m%dT%H%M%SZ)"
    cp -a "$WORK/web" "$release"
    cp "$WORK/CHANGES.txt" "$release/CHANGES.txt"
    ln -sfn "$release" "$SITE/current.tmp"
    mv -T "$SITE/current.tmp" "$SITE/current"
    # Keep the newest releases only.
    ls -1d "$SITE"/releases/2* 2>/dev/null | sort -r | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -rf
    rm -rf "$SITE/releases/placeholder"
    echo "$(date -u +%FT%TZ) published $release"
}

while true; do
    echo "$(date -u +%FT%TZ) building"
    if icos-maps --refresh --out "$WORK"; then
        publish
    else
        echo "$(date -u +%FT%TZ) build failed; keeping the previous site" >&2
    fi
    now=$(date -u +%s)
    next=$(date -u -d "today $BUILD_AT" +%s)
    [ "$next" -le "$now" ] && next=$(date -u -d "tomorrow $BUILD_AT" +%s)
    echo "$(date -u +%FT%TZ) next build at $(date -u -d "@$next" +%FT%TZ)"
    sleep $((next - now))
done
