#!/usr/bin/env bash
# Builds a copy of an Ubuntu cloud image whose initramfs has no dyn-netconf dracut module.
# Usage: prepare_image.sh IMAGE_URL IMAGE_CHECKSUM OUT_DIR
# With the module, the initramfs brings the NIC up with DHCP before cloud-init runs, so
# cloud-init's rename of the NIC fails as busy and the static address of the VM never applies.
# The script downloads the image, checks it against IMAGE_CHECKSUM, unpacks it to a raw disk on a
# loop device, omits the module in the image's dracut configuration, regenerates the image's
# initramfs files and fails unless none of them lists the module any more. It writes
# OUT_DIR/<image name>-no-dyn-netconf.qcow2 and its SHA-256 beside it as <file>.sha256, and removes
# everything else on every exit path.
# Run it as root or as a user with sudo, which it asks for before it downloads anything. It needs
# curl, qemu-img, losetup, lsblk, blkid, mount, umount, chroot and about 8 GB free in OUT_DIR
# (MIN_FREE_KB). PART_TRIES and PART_WAIT bound the wait for the loop device's partitions to appear.
set -euo pipefail

usage="usage: prepare_image.sh IMAGE_URL IMAGE_CHECKSUM OUT_DIR"
url=${1:?$usage}
sum=${2:?$usage}
mkdir -p "${3:?$usage}"
out=$(cd "$3" && pwd)
module=dyn-netconf

die() {
  echo "$*" >&2
  exit 1
}

[[ "$url" =~ ^https://[A-Za-z0-9._~:/%+-]+\.img$ ]] || die "IMAGE_URL must be an https:// URL of an Ubuntu cloud .img file"
[[ "$sum" =~ ^[0-9a-f]{64}$ ]] || die "IMAGE_CHECKSUM must be 64 lowercase hexadecimal characters"
for t in curl qemu-img losetup lsblk blkid mount umount chroot; do
  command -v "$t" > /dev/null || die "$t is not installed here"
done
free_kb=$(df -Pk "$out" | awk 'NR==2 {print $4}')
[ "$free_kb" -ge "${MIN_FREE_KB:-8000000}" ] || die "less than 8 GB free where $out is"

if [ "$(id -u)" -eq 0 ]; then
  priv() { "$@"; }
else
  # Asked for here so the password prompt comes before the download, not in the middle of the run.
  sudo -v || die "sudo is needed to attach and mount the image"
  priv() { sudo "$@"; }
fi

target=$out/$(basename "$url" .img)-no-dyn-netconf.qcow2
work=$(mktemp -d "$out/.prepare.XXXXXX")
mnt=$work/mnt
scratch=$work/tmp
loop=""
mounted=()

# Unmounts in reverse order and detaches the loop device. Stops at the first failure and keeps what
# is still mounted recorded, so the cleanup can try again.
unmount_all() {
  local i
  for ((i = ${#mounted[@]} - 1; i >= 0; i--)); do
    priv umount "${mounted[i]}" || return 1
    unset 'mounted[i]'
  done
  if [ -n "$loop" ]; then
    priv losetup -d "$loop" || return 1
    loop=""
  fi
}

# rm -rf over a mount that is still there would delete the image's files and the node's /dev
# entries, so the work directory is removed only once nothing is mounted.
cleanup() {
  local status=$?
  trap - EXIT
  set +e
  if ! unmount_all; then
    echo "could not unmount everything under $work; it is left in place, unmount by hand before removing it" >&2
    exit 1
  fi
  priv rm -rf "$scratch"
  rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT

# The last argument is the mount point.
do_mount() {
  priv mount "$@"
  mounted+=("${*: -1}")
}

in_image() { priv chroot "$mnt" "$@"; }

initramfs_files() {
  priv find "$mnt/boot" -maxdepth 1 -type f \( -name 'initrd.img-*' -o -name 'initramfs-*.img' \) -printf '%f\n' | sort
}

# Succeeds when the initramfs in /boot of the image lists the module. The listing is captured
# before it is searched: grep -q closing a pipe early would turn the pipeline's status into
# lsinitrd's SIGPIPE under pipefail, and a failed listing would then read as "not listed".
carries_module() {
  local listing
  listing=$(in_image lsinitrd -m "/boot/$1") || die "could not list the modules of /boot/$1"
  grep -Eq "(^|[^[:alnum:]_-])[0-9]*$module(\$|[^[:alnum:]_-])" <<< "$listing"
}

curl -fL --retry 3 -o "$work/base.img" "$url"
got=$(sha256sum "$work/base.img" | cut -d' ' -f1)
[ "$got" = "$sum" ] || die "checksum mismatch for $url: expected $sum, downloaded $got"

qemu-img convert -f qcow2 -O raw "$work/base.img" "$work/disk.raw"
rm -f "$work/base.img"
loop=$(priv losetup --find --show --partscan "$work/disk.raw")

# Only the loop device's own partitions are looked at: the host may carry the same labels.
root_dev=""
boot_dev=""
for _ in $(seq "${PART_TRIES:-20}"); do
  while read -r dev; do
    case "$(priv blkid -p -o value -s LABEL "$dev" 2> /dev/null || true)" in
      cloudimg-rootfs) root_dev=$dev ;;
      BOOT) boot_dev=$dev ;;
    esac
  done < <(lsblk -rno PATH "$loop")
  [ -z "$root_dev" ] || break
  sleep "${PART_WAIT:-0.5}"
done
[ -n "$root_dev" ] || die "no partition of the image is labelled cloudimg-rootfs"

mkdir -p "$mnt"
do_mount "$root_dev" "$mnt"
[ -z "$boot_dev" ] || do_mount "$boot_dev" "$mnt/boot"
# dracut builds the initramfs in /var/tmp, and the image's root file system has almost no free
# space until the first boot grows it, so a directory on this host's disk is bound over it.
mkdir -p "$scratch"
chmod 1777 "$scratch"
do_mount --bind "$scratch" "$mnt/var/tmp"
do_mount --bind /dev "$mnt/dev"
do_mount -t proc proc "$mnt/proc"
do_mount -t sysfs sysfs "$mnt/sys"

in_image /bin/sh -c 'command -v dracut > /dev/null && command -v lsinitrd > /dev/null' || die "the image has no dracut, so there is no initramfs module to omit"
before=$(initramfs_files)
[ -n "$before" ] || die "no initramfs file in /boot of the image"
carrying=0
while read -r f; do
  if carries_module "$f"; then carrying=1; fi
done <<< "$before"
[ "$carrying" = 1 ] || die "no initramfs of the image lists $module: there is nothing to omit"

priv mkdir -p "$mnt/etc/dracut.conf.d"
printf 'omit_dracutmodules+=" %s "\n' "$module" | priv tee "$mnt/etc/dracut.conf.d/99-no-$module.conf" > /dev/null
# A chroot sees the build host's devices, so a host-only initramfs would fit this host and not the VMs.
in_image dracut --regenerate-all --force --no-hostonly --no-hostonly-cmdline

after=$(initramfs_files)
[ -n "$after" ] || die "no initramfs file in /boot of the image after it was regenerated"
while read -r f; do
  if carries_module "$f"; then die "/boot/$f still lists $module after the initramfs was regenerated"; fi
done <<< "$after"

unmount_all || die "could not unmount the image"
qemu-img convert -O qcow2 -c "$work/disk.raw" "$work/image.qcow2"
result=$(sha256sum "$work/image.qcow2" | cut -d' ' -f1)
mv "$work/image.qcow2" "$target"
printf '%s\n' "$result" > "$target.sha256"
echo "initramfs files without $module: $(tr '\n' ' ' <<< "$after")"
echo "wrote $target"
echo "sha256 $result"
