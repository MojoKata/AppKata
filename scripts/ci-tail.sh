#!/bin/sh
# CI, after a step fails: the last 40 lines of its output (LOG) as one error annotation titled
# TITLE, so the reason shows on the pull request's Checks page, and through GitHub's API, without
# opening the run's log.
[ -f "$1" ] || exit 0
printf '::error title=%s::%s\n' "$2" "$(tail -n 40 "$1" | sed -e 's/%/%25/g' -e 's/\r/%0D/g' | awk 'BEGIN { ORS = "%0A" } { print }')"
