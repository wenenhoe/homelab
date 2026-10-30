#!/usr/bin/env bash
# Run on the Proxmox node, after the gateway has been seeded. Updates the scratch
# gateway to the pinned release through its firmware API and checks, before and after,
# that the seeded API user still authenticates and a wrong secret is still refused.
# Usage: update_gateway.sh CREDS GATEWAY_CERT WANT_VERSION OUT_DIR
# CREDS is a shell file setting API_KEY, API_SECRET and LAN_IP. Every call uses the
# certificate read from the console as the only trusted CA, so the pin is checked too.
# The gateway's update list, not its `product_latest`, says where an update lands, and
# the updater always goes to the newest release of the series, so an update that would
# not land on WANT_VERSION is refused unless ALLOW_LATEST=1.
# Environment: GW_IP / GW_PORT (default LAN_IP / 443), ALLOW_LATEST=1,
#   SERIAL_SOCKET (checks the console answers with a login prompt or its menu after a reboot),
#   POLL (seconds between polls, default 5), UPDATE_TIMEOUT / UP_TIMEOUT (seconds).
# Prints "CHECK name: PASS|FAIL" lines; the exit status is the number of FAIL lines.
set -u
# shellcheck disable=SC1090
. "${1:?creds}"
cert=${2:?cert}
want=${3:?version}
dir=${4:?out dir}
ip=${GW_IP:-$LAN_IP}
port=${GW_PORT:-443}
poll=${POLL:-5}
update_timeout=${UPDATE_TIMEOUT:-1800}
up_timeout=${UP_TIMEOUT:-900}
mkdir -p "$dir"
work=$(mktemp -d /tmp/opn-update.XXXXXX)
chmod 700 "$work"
trap 'rm -rf "$work"' EXIT
fails=0

check() { # check NAME EXIT_STATUS
  if [ "$2" = 0 ]; then echo "CHECK $1: PASS"; else echo "CHECK $1: FAIL"; fails=$((fails + 1)); fi
}
note() { echo "  $*"; }

name=$(openssl x509 -in "$cert" -noout -ext subjectAltName | grep -o 'DNS:[^, ]*' | head -n1 | cut -c5-)
api() { curl -s --noproxy "*" --max-time "${API_TIMEOUT:-60}" --cacert "$cert" --resolve "$name:$port:$ip" -u "$API_KEY:$API_SECRET" "$@"; }
get() { api "https://$name:$port/api/$1"; }
post() { api -X POST -d '' "https://$name:$port/api/$1"; }

jget() { # jget FILE DOTTED.PATH -> the value, or nothing
  python3 -I -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    for k in sys.argv[2].split("."):
        d = d[k]
    print(json.dumps(d) if isinstance(d, (dict, list)) else d)
except Exception:
    pass' "$1" "$2"
}

api_up() { [ "$(api -o /dev/null -w '%{http_code}' "https://$name:$port/api/diagnostics/system/system_information")" = 200 ]; }
wait_state() { # wait_state up|down SECONDS
  local end=$((SECONDS + $2))
  while [ "$SECONDS" -lt "$end" ]; do
    if [ "$1" = up ]; then api_up && return 0; else api_up || return 0; fi
    sleep "$poll"
  done
  return 1
}

# Follows a firmware job to its end. Prints done, reboot or timeout. The web server restarts
# during an update, so a poll that gets no answer waits for the API to come back and goes on;
# once the gateway has rebooted its job log is gone, which ends the wait too.
await_job() { # await_job LABEL SECONDS
  local end=$((SECONDS + $2)) st misses=0 gone=0 saw_drop=0
  sleep "$poll"
  while [ "$SECONDS" -lt "$end" ]; do
    if get core/firmware/upgradestatus > "$work/job.json" 2> /dev/null && [ -s "$work/job.json" ]; then
      misses=0
      st=$(jget "$work/job.json" status)
      jget "$work/job.json" log | tail -n 400 > "$dir/job-$1.log"
      case "$st" in
        done | reboot) echo "$st"; return ;;
        error) gone=$((gone + 1)); [ "$saw_drop" = 1 ] && [ "$gone" -ge 3 ] && { echo reboot; return; } ;;
        *) gone=0 ;;
      esac
    else
      misses=$((misses + 1))
      if [ "$misses" -ge 3 ]; then
        saw_drop=1; misses=0; gone=0
        : > "$work/saw_drop"
        wait_state up "$up_timeout" || { echo timeout; return; }
      fi
    fi
    sleep "$poll"
  done
  echo timeout
}

# The seed's API user must still authenticate, and a wrong secret must still be refused,
# over the pinned certificate and on the LAN address the seed set.
cfg() { # cfg LABEL -> 0 when both hold
  local url="https://$name:$port/api/diagnostics/system/system_information" good bad
  good=$(api -o /dev/null -w '%{http_code}' "$url")
  bad=$(api -u "$API_KEY:wrong-secret" -o /dev/null -w '%{http_code}' "$url")
  echo "  auth[$1]: seeded key -> HTTP $good (expect 200), wrong secret -> HTTP $bad (expect 401)" | tee -a "$dir/config-checks.txt"
  [ "$good" = 200 ] && [ "$bad" = 401 ]
}

: > "$dir/config-checks.txt"

# --- the gateway reaches its update mirror (this is what vmbr9 could not give)
post core/firmware/status > "$dir/fw-status-before.json" 2> /dev/null
st=$(jget "$dir/fw-status-before.json" status)
cur=$(jget "$dir/fw-status-before.json" product.product_version)
latest=$(jget "$dir/fw-status-before.json" product.product_latest)
# The release the update would install is the core package's new version in the update list.
# product_latest is a separate listing that lagged the repository (it said 26.1.7 while the
# repository held 26.1.11), so it is only printed. Versions carry a revision (26.1.6_2).
target=$(python3 -I -c '
import json, sys
try:
    for p in json.load(open(sys.argv[1])).get("upgrade_packages", []):
        if p.get("name") == "opnsense":
            print(p.get("new_version", "").split("_")[0])
except Exception:
    pass' "$dir/fw-status-before.json")
note "release $cur, update would install '${target:-nothing}' (the mirror's listing says $latest), firmware status '$st': $(jget "$dir/fw-status-before.json" status_msg)"
if [ -n "$cur" ] && [ "$st" != error ] && [ -n "$st" ]; then check "the gateway reaches its update mirror" 0; else check "the gateway reaches its update mirror" 1; fi
cfg before; check "the seeded API user works before the update" $?

# --- update to the pinned release
rebooted=0
if [ "${cur%%_*}" = "$want" ]; then
  note "already at $want; no update to run"
elif [ "$st" = upgrade ]; then
  note "the mirror offers a major upgrade, not an update; this phase does not run it"
  check "the mirror offers an update to $want" 1
elif [ "$target" != "$want" ] && [ "${ALLOW_LATEST:-0}" != 1 ]; then
  # The updater always goes to the newest release of the series, so it cannot stop at the pin.
  note "the update would install '${target:-nothing}', not $want. Nothing was updated. Re-run with ALLOW_LATEST=1 to update anyway, and tell me which release came out."
  check "the update lands on the pinned $want" 1
else
  rm -f "$work/saw_drop"
  post core/firmware/update > "$dir/fw-update-response.json" 2> /dev/null
  note "update started ($(jget "$dir/fw-update-response.json" status))"
  res=$(await_job update "$update_timeout")
  note "update job ended: $res"
  case "$res" in
    reboot)
      rebooted=1
      # The job can end after the gateway went down and came back, so a drop seen while following it counts.
      if [ -e "$work/saw_drop" ]; then
        note "the gateway went down and came back while the update job was followed"
        check "the gateway went down for the reboot" 0
      else
        wait_state down "${DOWN_TIMEOUT:-300}"; check "the gateway went down for the reboot" $?
      fi
      ;;
    done) ;;
    *) check "the update job finished" 1 ;;
  esac
  wait_state up "$up_timeout"; check "the API answers again after the update" $?
  post core/firmware/status > "$dir/fw-status-after.json" 2> /dev/null
  after=$(jget "$dir/fw-status-after.json" product.product_version)
  note "release now $after (firmware status '$(jget "$dir/fw-status-after.json" status)')"
  if [ "${after%%_*}" = "$want" ]; then check "the gateway runs $want after the update" 0; else check "the gateway runs $want after the update" 1; fi
  cfg after-update; check "the seed's seeded API user works after the update" $?
  if [ "$rebooted" = 1 ] && [ -n "${SERIAL_SOCKET:-}" ]; then
    CONSOLE_WAIT=${CONSOLE_WAIT:-60} python3 -I - "$SERIAL_SOCKET" << 'PY'
import os, socket, sys, time
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(sys.argv[1])
s.settimeout(1)
buf = b""
end = time.monotonic() + float(os.environ["CONSOLE_WAIT"])
last = 0
ready = (b"login:", b"Enter an option:")
while time.monotonic() < end and not any(m in buf for m in ready):
    if time.monotonic() - last > 10:
        s.send(b"\r"); last = time.monotonic()
    try:
        buf += s.recv(4096)
    except socket.timeout:
        pass
sys.exit(0 if any(m in buf for m in ready) else 1)
PY
    check "the serial console shows a login prompt or the menu after the reboot" $?
  fi
fi

exit "$fails"
