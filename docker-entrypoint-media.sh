#!/bin/sh
set -eu

# The mount hides the directory ownership set in the Dockerfile. Repair it before
# the non-root API starts, including root-owned uploads from earlier deployments.
mkdir -p /app/media/tour_plan
chown -R django:django /app/media
find /app/media -type d -exec chmod 0755 {} +
find /app/media -type f -exec chmod 0644 {} +
