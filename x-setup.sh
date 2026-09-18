#!/bin/sh
# Store the x.com session the nightly pull needs.
# A short top-level name, alongside the other entry points, because the real
# script lives four directories down and a long path is easy to mistype.
exec "$(dirname "$0")/research/x/setup-session.sh" "$@"
