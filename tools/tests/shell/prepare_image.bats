#!/usr/bin/env bats

setup() {
  load test_helper/harness
  harness_setup
  SCRIPT=$(install_script tofu/modules/proxmox_ubuntu_template/prepare_image.sh)
  OUT="$BATS_TEST_TMPDIR/out"
  URL=https://cloud-images.example.net/releases/26.04/release-20260101/ubuntu-26.04-server-cloudimg-amd64.img
  NAME=ubuntu-26.04-server-cloudimg-amd64-release-20260101-no-dyn-netconf.qcow2
  printf 'QCOW2BASE\n' > "$BATS_TEST_TMPDIR/served.img"
  SUM=$(sha256sum "$BATS_TEST_TMPDIR/served.img" | cut -d' ' -f1)
  export SERVED="$BATS_TEST_TMPDIR/served.img" REGENERATED="$BATS_TEST_TMPDIR/regenerated" MIN_FREE_KB=1 PART_WAIT=0

  stub curl <<'BODY'
while [ "$#" -gt 0 ]; do
  [ "$1" = -o ] && cp "$SERVED" "$2"
  shift
done
BODY
  # Both conversions write their own arguments into the file they produce.
  stub qemu-img <<'BODY'
printf 'qemu-img %s\n' "$*" > "${*: -1}"
BODY
  stub sudo <<'BODY'
if [ "$1" = -v ]; then
  [ -z "${SUDO_FAIL:-}" ]
else
  exec "$@"
fi
BODY
  stub losetup <<'BODY'
[ "$1" != --find ] || echo /dev/loop7
BODY
  stub lsblk <<'BODY'
printf '%s\n' /dev/loop7 /dev/loop7p1 /dev/loop7p14 /dev/loop7p15 /dev/loop7p16
BODY
  # The host's own partitions carry the same labels, so the script must ask about the loop device only.
  stub blkid <<'BODY'
case "${*: -1}" in
  /dev/loop7p1) [ -n "${NO_ROOT_LABEL:-}" ] || echo cloudimg-rootfs ;;
  /dev/loop7p15) echo UEFI ;;
  /dev/loop7p16) [ -n "${NO_BOOT_PART:-}" ] || echo BOOT ;;
  *) exit 2 ;;
esac
BODY
  # The image's initramfs files are listings of dracut modules, as lsinitrd -m prints them.
  stub mount <<'BODY'
target=${*: -1}
listing() {
  printf 'dracut modules:\nsystemd\n'
  [ -n "${NO_MODULE:-}" ] || printf 'dyn-netconf\n'
  printf 'bash\n'
}
case "$*" in
  "/dev/loop7p1 "*)
    mkdir -p "$target/boot" "$target/etc"
    [ -z "${NO_BOOT_PART:-}" ] || listing > "$target/boot/initrd.img-6.8.0-31-generic"
    ;;
  "/dev/loop7p16 "*) listing > "$target/initrd.img-6.8.0-31-generic" ;;
esac
BODY
  stub umount <<'BODY'
case "${*: -1}" in
  *"/${UMOUNT_FAIL:-NONE}") exit 1 ;;
esac
BODY
  # dracut regenerates only when the omission is in the image's configuration by then.
  stub chroot <<'BODY'
mnt=$1
shift
case "$1" in
  /bin/sh) [ -z "${NO_DRACUT:-}" ] ;;
  lsinitrd)
    [ -z "${LSINITRD_FAIL:-}" ] || exit 1
    [ -z "${LSINITRD_FAIL_AFTER:-}" ] || [ ! -e "$REGENERATED" ] || exit 1
    cat "$mnt$3"
    ;;
  dracut)
    [ "$(cat "$mnt/etc/dracut.conf.d/99-no-dyn-netconf.conf")" = 'omit_dracutmodules+=" dyn-netconf "' ] || exit 9
    touch "$REGENERATED"
    [ -n "${DRACUT_NOOP:-}" ] || sed -i '/dyn-netconf/d' "$mnt"/boot/initrd.img-*
    ;;
esac
BODY
}

teardown() {
  harness_teardown
}

# The recorded calls of one tool, with the random work directory replaced.
calls() {
  calls_to "$1" | sed -E "s#$OUT/\.prepare\.[A-Za-z0-9]+#WORK#g"
}

@test "writes the compressed qcow2 copy and its checksum, and nothing else in the output directory" {
  run -0 "$SCRIPT" "$URL" "$SUM" "$OUT"

  run ls -A "$OUT"
  assert_output "$NAME
$NAME.sha256"
  [ "$(cat "$OUT/$NAME.sha256")" = "$(sha256sum "$OUT/$NAME" | cut -d' ' -f1)" ]
  run -0 grep -E '^qemu-img convert -O qcow2 -c .*/disk\.raw .*/image\.qcow2$' "$OUT/$NAME"
}

@test "downloads the image with one curl and unpacks that file to a raw disk" {
  run -0 "$SCRIPT" "$URL" "$SUM" "$OUT"

  run calls curl
  assert_output "curl -fL --retry 3 -o WORK/base.img $URL"
  run calls qemu-img
  assert_output "qemu-img convert -f qcow2 -O raw WORK/base.img WORK/disk.raw
qemu-img convert -O qcow2 -c WORK/disk.raw WORK/image.qcow2"
}

@test "writes the omission before dracut runs and regenerates without host-only mode" {
  run -0 "$SCRIPT" "$URL" "$SUM" "$OUT"

  run calls chroot
  assert_output --partial "chroot WORK/mnt dracut --regenerate-all --force --no-hostonly --no-hostonly-cmdline"
}

@test "asks about the loop device's partitions only" {
  run -0 "$SCRIPT" "$URL" "$SUM" "$OUT"

  run calls lsblk
  assert_output "lsblk -rno PATH /dev/loop7"
  run calls blkid
  assert_output "blkid -p -o value -s LABEL /dev/loop7
blkid -p -o value -s LABEL /dev/loop7p1
blkid -p -o value -s LABEL /dev/loop7p14
blkid -p -o value -s LABEL /dev/loop7p15
blkid -p -o value -s LABEL /dev/loop7p16"
}

@test "mounts the boot partition under /boot when the image has one" {
  run -0 "$SCRIPT" "$URL" "$SUM" "$OUT"

  run calls mount
  assert_output "mount /dev/loop7p1 WORK/mnt
mount /dev/loop7p16 WORK/mnt/boot
mount --bind WORK/tmp WORK/mnt/var/tmp
mount --bind /dev WORK/mnt/dev
mount -t proc proc WORK/mnt/proc
mount -t sysfs sysfs WORK/mnt/sys"
}

@test "reads the initramfs from the root partition when the image has no boot partition" {
  NO_BOOT_PART=1 run -0 "$SCRIPT" "$URL" "$SUM" "$OUT"

  run calls mount
  assert_output "mount /dev/loop7p1 WORK/mnt
mount --bind WORK/tmp WORK/mnt/var/tmp
mount --bind /dev WORK/mnt/dev
mount -t proc proc WORK/mnt/proc
mount -t sysfs sysfs WORK/mnt/sys"
  run -0 ls "$OUT/$NAME"
}

@test "binds a directory of the host's disk over the image's /var/tmp before dracut runs" {
  run -0 "$SCRIPT" "$URL" "$SUM" "$OUT"

  bound=$(grep -n -m1 -E '^mount --bind .*/tmp .*/mnt/var/tmp$' "$CALLS" | cut -d: -f1)
  regenerated=$(grep -n -m1 ' dracut ' "$CALLS" | cut -d: -f1)
  [ -n "$bound" ]
  [ "$bound" -lt "$regenerated" ]
}

@test "asks for sudo before it downloads anything, and stops when it is refused" {
  [ "$(id -u)" -ne 0 ] || skip "root does not use sudo"

  run -0 "$SCRIPT" "$URL" "$SUM" "$OUT"
  [ "$(grep -n -m1 '^sudo -v$' "$CALLS" | cut -d: -f1)" -lt "$(grep -n -m1 '^curl ' "$CALLS" | cut -d: -f1)" ]

  rm -rf "$OUT"
  : > "$CALLS"
  SUDO_FAIL=1 run -1 "$SCRIPT" "$URL" "$SUM" "$OUT"
  assert_output --partial "sudo is needed to attach and mount the image"
  run calls curl
  assert_output ""
}

@test "unmounts in reverse order and detaches the loop device" {
  run -0 "$SCRIPT" "$URL" "$SUM" "$OUT"

  run calls umount
  assert_output "umount WORK/mnt/sys
umount WORK/mnt/proc
umount WORK/mnt/dev
umount WORK/mnt/var/tmp
umount WORK/mnt/boot
umount WORK/mnt"
  run calls losetup
  assert_output --regexp 'losetup -d /dev/loop7$'
}

@test "a checksum mismatch fails before the disk is attached and leaves nothing behind" {
  run -1 "$SCRIPT" "$URL" "$(printf '1%.0s' $(seq 64))" "$OUT"

  assert_output --partial "checksum mismatch for $URL: expected"
  run calls losetup
  assert_output ""
  run ls -A "$OUT"
  assert_output ""
}

@test "an initramfs that still lists the module after regeneration fails and writes no image" {
  DRACUT_NOOP=1 run -1 "$SCRIPT" "$URL" "$SUM" "$OUT"

  assert_output --partial "/boot/initrd.img-6.8.0-31-generic still lists dyn-netconf after the initramfs was regenerated"
  run calls umount
  assert_output "umount WORK/mnt/sys
umount WORK/mnt/proc
umount WORK/mnt/dev
umount WORK/mnt/var/tmp
umount WORK/mnt/boot
umount WORK/mnt"
  run ls -A "$OUT"
  assert_output ""
}

@test "a listing that fails after regeneration is a failure, not a pass" {
  LSINITRD_FAIL_AFTER=1 run -1 "$SCRIPT" "$URL" "$SUM" "$OUT"

  assert_output --partial "could not list the modules of /boot/initrd.img-6.8.0-31-generic"
  run ls -A "$OUT"
  assert_output ""
}

@test "an image whose initramfs lists no such module fails before anything is written to it" {
  NO_MODULE=1 run -1 "$SCRIPT" "$URL" "$SUM" "$OUT"

  assert_output --partial "no initramfs of the image lists dyn-netconf: there is nothing to omit"
  run calls chroot
  refute_output --partial " dracut "
  run ls -A "$OUT"
  assert_output ""
}

@test "an image without dracut fails before any initramfs is listed" {
  NO_DRACUT=1 run -1 "$SCRIPT" "$URL" "$SUM" "$OUT"

  assert_output --partial "the image has no dracut"
  run calls chroot
  assert_equal "${#lines[@]}" 1
}

@test "an image with no partition labelled cloudimg-rootfs fails with the loop device detached" {
  NO_ROOT_LABEL=1 PART_TRIES=2 run -1 "$SCRIPT" "$URL" "$SUM" "$OUT"

  assert_output --partial "no partition of the image is labelled cloudimg-rootfs"
  run calls mount
  assert_output ""
  run calls losetup
  assert_output --regexp 'losetup -d /dev/loop7$'
}

@test "a failed unmount fails the run and leaves the work directory in place" {
  UMOUNT_FAIL=dev run -1 "$SCRIPT" "$URL" "$SUM" "$OUT"

  assert_output --partial "it is left in place, unmount by hand before removing it"
  run ls -A "$OUT"
  assert_output --regexp '^\.prepare\.[A-Za-z0-9]+$'
}

@test "refuses a URL that is not an https .img file and a checksum that is not a SHA-256" {
  run -1 "$SCRIPT" http://cloud-images.example.net/ubuntu.img "$SUM" "$OUT"
  assert_output --partial "IMAGE_URL must be an https:// URL of an Ubuntu cloud .img file"
  run -1 "$SCRIPT" "$URL" ABC "$OUT"
  assert_output --partial "IMAGE_CHECKSUM must be 64 lowercase hexadecimal characters"

  run calls curl
  assert_output ""
}
