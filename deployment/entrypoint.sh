#!/bin/sh
set -eu
mkdir -p /data
chown app:app /data
exec gosu app python scripts/deploy.py
