#!/usr/bin/env bash
# compose-boot-test boots the deployed stack with its real config; this
# boots the image alone, as the user the image sets, on a fresh named
# volume, with a config that holds the one regular endpoint Gatus
# requires. It passes when the image's own /wget gets /health and the
# sqlite file appears in /data. Usage: gatus.sh <image>
set -euo pipefail

image="$1"
name="gatus-smoke-$$"
work="$(mktemp -d)"

cleanup() {
  docker rm --force "$name" > /dev/null 2>&1 || true
  docker volume rm "$name" > /dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

user="$(docker image inspect --format '{{.Config.User}}' "$image")"
if [[ ! "$user" =~ ^[1-9][0-9]*(:[0-9]+)?$ ]]; then
  echo "::error::$image runs as '${user:-root}', not a non-root numeric user"
  exit 1
fi

cat > "$work/config.yaml" << 'YAML'
storage:
  type: sqlite
  path: /data/data.db
endpoints:
  - name: self
    url: http://localhost:8080/health
    interval: 5s
    conditions:
      - "[STATUS] == 200"
YAML
chmod 644 "$work/config.yaml"

docker run --detach --name "$name" \
  --volume "$name:/data" \
  --volume "$work/config.yaml:/config/config.yaml:ro" \
  "$image" > /dev/null

for _ in $(seq 1 30); do
  if docker exec "$name" /wget --no-verbose --tries=1 --spider http://localhost:8080/health; then
    break
  fi
  sleep 1
done

if ! docker exec "$name" /wget --no-verbose --tries=1 --spider http://localhost:8080/health \
  || ! docker cp "$name:/data/data.db" - > /dev/null; then
  docker logs "$name"
  echo "::error::$image did not serve /health and create /data/data.db as $user"
  exit 1
fi
