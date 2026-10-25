# Sourced: fetch_python SERIES CACHE -- python-build-standalone's CPython of SERIES for x86_64 Linux
# (glibc 2.17+), from the release PYTHON_BUILD names (packaging/versions.env), downloaded once to
# CACHE and sets PYTHON_TARBALL to it. PYTHON_BUILD itself is checked against PYTHON_LINUX_SHA256
# each time; another series, to try one, against that release's SHA256SUMS.
fetch_python() {
    _series=$1 _cache=$2 _release=${PYTHON_BUILD#*+} _v=${PYTHON_BUILD%%+*} _pin=
    _url=https://github.com/astral-sh/python-build-standalone/releases/download/$_release
    if [ "${_v%.*}" = "$_series" ]; then
        _name=cpython-$PYTHON_BUILD-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz _pin=$PYTHON_LINUX_SHA256
        PYTHON_TARBALL=$_cache/$_name
        [ -f "$PYTHON_TARBALL" ] && echo "$_pin  $PYTHON_TARBALL" | sha256sum -c --quiet >/dev/null 2>&1 && return 0
    else
        for PYTHON_TARBALL in "$_cache"/cpython-"$_series".*+"$_release"-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz; do
            [ -f "$PYTHON_TARBALL" ] && return 0
        done
        _name=$(curl -fsSL "https://github.com/astral-sh/python-build-standalone/releases/expanded_assets/$_release" |
                grep -o "cpython-$_series\.[0-9]*+$_release-x86_64-unknown-linux-gnu-install_only_stripped\.tar\.gz" | head -1)
        [ -n "$_name" ] || { echo "release $_release has no CPython $_series build" >&2; return 1; }
        PYTHON_TARBALL=$_cache/$_name
        _pin=$(curl -fsSL "$_url/SHA256SUMS" | grep " $_name\$" | cut -d' ' -f1 || true)
        [ -n "$_pin" ] || { echo "release $_release's SHA256SUMS doesn't list $_name" >&2; return 1; }
    fi
    mkdir -p "$_cache"
    echo "== python-build-standalone $_name"
    curl -fsSL -o "$PYTHON_TARBALL.part" "$_url/$_name"
    echo "$_pin  $PYTHON_TARBALL.part" | sha256sum -c --quiet ||
        { echo "$_name doesn't match its SHA-256" >&2; return 1; }
    mv "$PYTHON_TARBALL.part" "$PYTHON_TARBALL"
}
