# Sourced: tier1_setup HERE -- the container tier 1 runs in (an Ubuntu 24.04 image, appkata-tier1),
# and the release's Python and PySide6 for it (packaging/versions.env), made once. Sets IMG, SITE
# (PySide6, for PYTHONPATH) and PYT (the Python, a path under HERE).
tier1_setup() {
    . "$1/packaging/versions.env"
    PYT=$(sh "$1/scripts/python-standalone.sh")
    # what Qt's offscreen platform and the tests need from a desktop system (Ubuntu 24.04's glibc 2.39),
    # curl for coworker/iso's download test, and Nimbus Sans as the sans-serif font, the default where
    # the committed Linux screenshots were first taken. The image's tag follows this recipe, so a
    # change makes a new image.
    _df="FROM $NOBLE_IMAGE"'
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git gnupg openssh-client libgl1 libegl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libglib2.0-0t64 fonts-dejavu-core fonts-urw-base35 fontconfig python3 python3-gi zip unzip xz-utils file ca-certificates curl >/dev/null
RUN printf "<?xml version=\"1.0\"?><!DOCTYPE fontconfig SYSTEM \"fonts.dtd\"><fontconfig><alias><family>sans-serif</family><prefer><family>Nimbus Sans</family></prefer></alias></fontconfig>\n" > /etc/fonts/local.conf && fc-match sans-serif | grep -q "Nimbus Sans"'
    IMG=appkata-tier1:$(printf '%s' "$_df" | sha256sum | cut -c1-12)
    docker image inspect "$IMG" >/dev/null 2>&1 || printf '%s\n' "$_df" | docker build -q -t "$IMG" - >/dev/null
    SITE="$1/build/pyside-$PYSIDE-py$PY_SERIES"
    if [ ! -d "$SITE/PySide6" ]; then
        echo "== PySide6-Essentials $PYSIDE for Python $PY_SERIES" >&2
        rm -rf "$SITE.part" && mkdir -p "$SITE.part"
        docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$1:$1:ro" -v "$SITE.part:/site" "$IMG" \
            "$PYT" -m pip install -q --no-deps --disable-pip-version-check --target /site "PySide6-Essentials==$PYSIDE" "shiboken6==$PYSIDE"
        rm -rf "$SITE" && mv "$SITE.part" "$SITE"
    fi
}
