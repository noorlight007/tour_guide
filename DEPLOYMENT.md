# Tour upload storage

The API saves uploads under `/app/media`. When nginx runs on the host, both
processes must use the same files. The production Compose override binds
`/var/www/tour_guide/media` to `/app/media` for every service that uses media.
Set `MEDIA_HOST_PATH` in the deployment `.env` if nginx uses a different directory.

The `media_init` service repairs ownership of existing media before the API starts.
It grants the non-root `django` user write access and makes images readable by
nginx. The API itself continues to run as `django`.

## First deployment from the old named media volume

Run these steps on the deployment host, from the existing Compose project
directory. Keep the same project name used by the running deployment. Build first
to minimize downtime:

```sh
docker compose -f docker-compose.yml -f docker-compose.production.yml build web media_init
docker compose -f docker-compose.yml stop web celery_worker celery_beat
```

Before changing mounts, back up both the host media directory and the container's
media volume. For the default production path, with privileges to access it:

```sh
media_backup=$(mktemp -d /var/backups/tour-media.XXXXXX)
mkdir -p "$media_backup/host" "$media_backup/volume"
if [ -d /var/www/tour_guide/media ]; then
    cp -a /var/www/tour_guide/media/. "$media_backup/host/"
fi
docker cp django_web:/app/media/. "$media_backup/volume/"
mkdir -p /var/www/tour_guide/media
```

Use the configured host path instead of `/var/www/tour_guide/media` above if
`MEDIA_HOST_PATH` is set. Compare the two backups before merging. If the same
relative filename contains different bytes, check which picture the corresponding
database record should reference before choosing a version. Merge non-conflicting
volume files into the host directory; for example, with `rsync` installed:

```sh
rsync -a --ignore-existing "$media_backup/volume/" /var/www/tour_guide/media/
```

Keep the backups and the old named volume until public image URLs have been
verified. Start the repaired API and initializer using the override:

```sh
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d web
docker compose -f docker-compose.yml -f docker-compose.production.yml logs media_init web
```

If Celery services were running before maintenance, rebuild and start those with
the same two Compose files so they also use the shared host directory. Use this
same file list for future production Compose commands. Local development can
continue using `docker-compose.yml` alone with its named media volume.

## nginx and verification

The API server block should serve the configured host media directory:

```nginx
location /media/ {
    alias /var/www/tour_guide/media/;
}
```

After applying any nginx configuration change, validate it with `nginx -t` before
reloading. Upload an image using `POST /api/v1/tour/image/`, attach its ID through
`PATCH /api/v1/tour/plan/<id>` with `image_ids`, and open the returned image URL to
verify that nginx serves the saved file.

To replace a tour picture safely, send a multipart `PATCH` containing `file` to
`/api/v1/tour/image/<image_id>`. This keeps the image ID and tour association; a
failed upload leaves the original database reference in place. Deleting the old
image and then uploading a replacement are separate requests and can lose the
association if the second request fails.

## Backend regression tests

```sh
python manage.py test tour_plan.tests --settings=tour_management.test_settings
```

These use an isolated SQLite database and temporary upload directories. They cover
upload/replacement, preservation after upload failure, traveler quantity changes,
capacity validation, and prices for all five traveler categories. They do not
require a production database or change existing bookings.
