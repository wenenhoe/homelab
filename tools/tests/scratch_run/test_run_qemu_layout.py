from __future__ import annotations

import shutil
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest
from scratch_run.qemu_layout import MODULE_DIR, STATED, Disk, LayoutError, Nic, drift, parse_hcl, qemu_argv, read_module_layout

ARGV = {
    "system_disk": Path("/work/system.qcow2"),
    "seed_disk": Path("/secret/seed.img"),
    "serial_socket": Path("/run/serial0"),
    "lan_tap": "spktap",
}


def argv(layout=STATED, accel="kvm", **more) -> list[str]:
    return qemu_argv(layout, accel=accel, **(ARGV | more))


def after(items: list[str], flag: str, starting: str) -> str:
    """The value of the first `flag` whose value starts with `starting`."""
    return next(value for name, value in pairwise(items) if name == flag and value.startswith(starting))


@pytest.fixture
def module(tmp_path_factory) -> Path:
    """A copy of the module's Tofu files a test may change."""
    copy = tmp_path_factory.mktemp("module")
    for name in ("main.tf", "variables.tf"):
        shutil.copy(MODULE_DIR / name, copy / name)
    return copy


def mutate(module: Path, name: str, old: str, new: str) -> None:
    text = (module / name).read_text()
    assert old in text, f"{name} no longer holds the text this test changes: {old!r}"
    (module / name).write_text(text.replace(old, new, 1))


def test_the_module_and_the_stated_layout_agree():
    assert drift(STATED, read_module_layout()) == []


def test_a_copy_of_the_module_agrees_too(module):
    assert drift(STATED, read_module_layout(module)) == []


@pytest.mark.parametrize(
    ("file", "old", "new", "part"),
    [
        pytest.param("main.tf", 'machine       = "q35"', 'machine       = "pc"', "machine", id="machine-type"),
        pytest.param("main.tf", 'scsi_hardware = "virtio-scsi-single"', 'scsi_hardware = "virtio-scsi-pci"', "scsi_hardware", id="scsi-controller"),
        pytest.param("main.tf", 'boot_order    = ["scsi0"]', 'boot_order    = ["scsi1"]', "boot_order", id="boot-order"),
        pytest.param("variables.tf", 'default     = 2\n}\n\nvariable "memory_mb"', 'default     = 4\n}\n\nvariable "memory_mb"', "cores", id="cores"),
        pytest.param("variables.tf", "default     = 2048", "default     = 4096", "memory_mb", id="memory"),
        pytest.param("variables.tf", "default     = 32", "default     = 16", "disk_gb", id="disk-size"),
        pytest.param("main.tf", "iothread     = true", "iothread     = false", "disks", id="iothread"),
        pytest.param("main.tf", 'interface    = "scsi1"', 'interface    = "scsi2"', "disks", id="seed-disk-slot"),
        pytest.param("main.tf", "ssd          = true", "ssd          = false", "disks", id="ssd"),
        pytest.param("main.tf", 'model       = "virtio"\n  }\n\n  network_device', 'model       = "e1000"\n  }\n\n  network_device', "nics", id="nic-model"),
        pytest.param("main.tf", 'device = "socket"', 'device = "unix"', "serial", id="serial-device"),
    ],
)
def test_a_change_to_the_module_is_named_as_drift(module, file, old, new, part):
    mutate(module, file, old, new)
    named = [sentence.split(":")[0] for sentence in drift(STATED, read_module_layout(module))]
    assert named == [part]


def test_swapping_the_wan_and_the_lan_is_named_as_drift(module):
    mutate(module, "main.tf", "bridge      = var.wan_bridge", "bridge      = var.XXX")
    mutate(module, "main.tf", "bridge      = var.lan_bridge", "bridge      = var.wan_bridge")
    mutate(module, "main.tf", "bridge      = var.XXX", "bridge      = var.lan_bridge")
    found = read_module_layout(module)
    assert found.nics == (Nic("lan", "virtio"), Nic("wan", "virtio"))
    assert [sentence.split(":")[0] for sentence in drift(STATED, found)] == ["nics"]


def test_drift_says_what_each_side_has():
    (sentence,) = drift(STATED, replace(STATED, machine="pc"))
    assert sentence == "machine: the module has 'pc', the QEMU layout has 'q35'"


@pytest.mark.parametrize(
    ("file", "old", "new", "message"),
    [
        pytest.param(
            "main.tf", 'machine       = "q35"', "machine       = local.kind", "machine is `local.kind`, which is not a plain string", id="machine-from-a-local"
        ),
        pytest.param(
            "main.tf", '  serial_device {\n    device = "socket"\n  }\n', "", "expected one `serial_device` block in `resource`, found 0", id="no-serial-device"
        ),
        pytest.param(
            "main.tf",
            "bridge      = var.wan_bridge",
            'bridge      = "vmbr0"',
            'is `"vmbr0"`, which is neither var.wan_bridge nor var.lan_bridge',
            id="bridge-not-a-variable",
        ),
        pytest.param("variables.tf", "default     = 2048", "", "`dedicated` refers to `var.memory_mb`, which has no default", id="no-default"),
        pytest.param("main.tf", "  cpu {\n    cores = var.cores", "  cpu {\n    cores = var.XXX", "which has no default", id="unknown-variable"),
        pytest.param("main.tf", "ssd          = true", 'ssd          = "yes"', '`ssd` is `"yes"`, which is not true or false', id="flag-not-a-bool"),
        pytest.param("main.tf", 'discard      = "on"', 'discard      = "full"', "`discard` is `full`, which is neither on nor ignore", id="discard-unknown"),
    ],
)
def test_a_module_the_reader_cannot_read_is_refused_with_the_reason(module, file, old, new, message):
    mutate(module, file, old, new)
    with pytest.raises(LayoutError, match=message):
        read_module_layout(module)


def test_the_reader_goes_through_strings_comments_and_templates():
    text = """
    # a comment with a { brace
    resource "t" "this" { // trailing
      /* block { comment */
      name = "a ${var.x == "}" ? "{" : "b"} c" # note
      list = [
        "one",
        "two",
      ]
      inner { value = 1 }
    }
    """
    (block,) = parse_hcl(text).children
    assert block.labels == ("t", "this")
    assert block.attrs["name"] == '"a ${var.x == "}" ? "{" : "b"} c"'
    assert block.attrs["list"] == '[\n        "one",\n        "two",\n      ]'
    assert block.child("inner").attrs == {"value": "1"}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param('a = "open', "a string is never closed", id="open-string"),
        pytest.param('a = "x ${ y"', "a string is never closed", id="open-template"),
        pytest.param("b {\n a = 1\n", "a block is never closed", id="open-block"),
        pytest.param("}", "a closing brace has no block", id="stray-brace"),
        pytest.param("a = [1, 2", "a bracket is never closed", id="open-bracket"),
        pytest.param("a = 1)", "a closing bracket has no opening one", id="stray-bracket"),
        pytest.param("a = <<EOT\nx\nEOT\n", "a heredoc is not read", id="heredoc"),
        pytest.param("/* open", "a comment is never closed", id="open-comment"),
        pytest.param("a b", "`a` is neither an attribute nor a block", id="word-alone"),
        pytest.param("= 1", "unexpected '=' where a name should start", id="no-name"),
    ],
)
def test_text_that_is_not_hcl_is_refused(text, message):
    with pytest.raises(LayoutError, match=message):
        parse_hcl(text)


def test_the_machine_is_laid_out_as_the_layout_says():
    items = argv()
    assert (after(items, "-machine", "q35"), after(items, "-smp", "2"), after(items, "-m", "2048")) == ("q35", "2", "2048")


def test_each_disk_has_a_controller_of_its_own_and_the_system_disk_boots():
    items = argv()
    assert after(items, "-device", "virtio-scsi-pci,id=ctl-scsi0") == "virtio-scsi-pci,id=ctl-scsi0,iothread=io-scsi0"
    assert after(items, "-device", "virtio-scsi-pci,id=ctl-scsi1") == "virtio-scsi-pci,id=ctl-scsi1"
    assert after(items, "-device", "scsi-hd,drive=scsi0") == "scsi-hd,drive=scsi0,bus=ctl-scsi0.0,rotation_rate=1,bootindex=1"
    assert after(items, "-device", "scsi-hd,drive=scsi1") == "scsi-hd,drive=scsi1,bus=ctl-scsi1.0"
    assert after(items, "-drive", "if=none,id=scsi0") == "if=none,id=scsi0,file=/work/system.qcow2,format=qcow2,discard=unmap"
    assert after(items, "-drive", "if=none,id=scsi1") == "if=none,id=scsi1,file=/secret/seed.img,format=raw"


def test_the_wan_comes_first_on_user_mode_networking_and_the_lan_second_on_the_tap():
    items = argv()
    nics = [value for name, value in pairwise(items) if name == "-device" and value.startswith("virtio-net-pci")]
    assert nics == ["virtio-net-pci,netdev=wan,mac=52:54:00:00:00:00", "virtio-net-pci,netdev=lan,mac=52:54:00:00:00:01"]
    assert after(items, "-netdev", "user") == "user,id=wan"
    assert after(items, "-netdev", "tap") == "tap,ifname=spktap,script=no,downscript=no,id=lan"


def test_the_console_is_a_socket_and_a_log_is_added_when_asked_for():
    plain = argv()
    logged = argv(serial_log=Path("/secret/console.log"))
    assert after(plain, "-chardev", "socket") == "socket,id=ser0,path=/run/serial0,server=on,wait=off"
    assert after(logged, "-chardev", "socket") == "socket,id=ser0,path=/run/serial0,server=on,wait=off,logfile=/secret/console.log"
    assert after(plain, "-serial", "chardev") == "chardev:ser0"


@pytest.mark.parametrize(("accel", "cpu"), [pytest.param("kvm", "host", id="kvm"), pytest.param("tcg", "max", id="tcg")])
def test_the_accelerator_decides_the_cpu_model(accel, cpu):
    items = argv(accel=accel)
    assert (after(items, "-accel", accel), after(items, "-cpu", cpu)) == (accel, cpu)


def test_the_command_line_follows_the_layout_it_is_given():
    other = replace(STATED, machine="pc", cores=4, memory_mb=1024, nics=(Nic("lan", "virtio"), Nic("wan", "virtio")), boot_order=("scsi1",))
    other = replace(other, disks=(Disk("scsi0"), Disk("scsi1")))
    items = argv(other)
    assert (after(items, "-machine", "pc"), after(items, "-smp", "4"), after(items, "-m", "1024")) == ("pc", "4", "1024")
    assert after(items, "-device", "scsi-hd,drive=scsi1") == "scsi-hd,drive=scsi1,bus=ctl-scsi1.0,bootindex=1"
    assert after(items, "-device", "scsi-hd,drive=scsi0") == "scsi-hd,drive=scsi0,bus=ctl-scsi0.0"
    assert after(items, "-drive", "if=none,id=scsi0") == "if=none,id=scsi0,file=/work/system.qcow2,format=qcow2"
    assert after(items, "-device", "virtio-net-pci") == "virtio-net-pci,netdev=lan,mac=52:54:00:00:00:00"
    assert "-object" not in items


def test_a_comma_in_a_path_is_written_twice_so_it_stays_one_value():
    items = argv(system_disk=Path("/work/a,b.qcow2"))
    assert after(items, "-drive", "if=none,id=scsi0").startswith("if=none,id=scsi0,file=/work/a,,b.qcow2,format=")


@pytest.mark.parametrize(
    ("layout", "accel", "message"),
    [
        pytest.param(replace(STATED, scsi_hardware="lsi"), "kvm", "built for virtio-scsi-single, not lsi", id="controller"),
        pytest.param(STATED, "hvf", "accel is 'hvf', not kvm or tcg", id="accelerator"),
        pytest.param(replace(STATED, serial="unix"), "kvm", "serial device is built as a socket, not 'unix'", id="serial"),
        pytest.param(replace(STATED, disks=(Disk("scsi0"),)), "kvm", "takes a system disk and a seed disk, not 1 disks", id="one-disk"),
        pytest.param(replace(STATED, nics=(Nic("wan", "e1000"), Nic("lan", "virtio"))), "kvm", "NIC model 'e1000' has no QEMU device", id="nic-model"),
    ],
)
def test_a_layout_the_command_line_cannot_express_is_refused(layout, accel, message):
    with pytest.raises(LayoutError, match=message):
        argv(layout, accel)
