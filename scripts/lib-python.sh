# Sourced: fetch_python SERIES CACHE -- the newest python-build-standalone CPython of SERIES for
# x86_64 Linux (glibc 2.17+), downloaded once to CACHE/python-SERIES.tar.gz (its name beside it in
# .name) and checked against its release's SHA256SUMS. Found on the release page, no API needed.
fetch_python() {
    _series=$1 _cache=$2
    [ -f "$_cache/python-$_series.tar.gz" ] && return 0
    mkdir -p "$_cache"
    echo "== python-build-standalone $_series"
    _tag=$(curl -sSIL -o /dev/null -w '%{url_effective}' https://github.com/astral-sh/python-build-standalone/releases/latest | sed 's#.*/tag/##')
    _name=$(curl -sSL "https://github.com/astral-sh/python-build-standalone/releases/expanded_assets/$_tag" |
            grep -o "cpython-$_series\.[0-9]*+$_tag-x86_64-unknown-linux-gnu-install_only_stripped\.tar\.gz" | head -1)
    [ -n "$_name" ] || { echo "couldn't find a CPython $_series build in release $_tag" >&2; return 1; }
    curl -sSL -o "$_cache/python-$_series.tar.gz.part" "https://github.com/astral-sh/python-build-standalone/releases/download/$_tag/$_name"
    # the release's SHA256SUMS covers every file in it
    _sum=$(curl -fsSL "https://github.com/astral-sh/python-build-standalone/releases/download/$_tag/SHA256SUMS" | grep " $_name\$" | cut -d' ' -f1 || true)
    if [ -n "$_sum" ]; then
        echo "$_sum  $_cache/python-$_series.tar.gz.part" | sha256sum -c --quiet
    else
        echo "warning: no published checksum found for $_name" >&2
    fi
    mv "$_cache/python-$_series.tar.gz.part" "$_cache/python-$_series.tar.gz"
    echo "$_name" > "$_cache/python-$_series.name"
}
