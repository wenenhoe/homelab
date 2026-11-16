"""The QEMU layout of the scratch gateway, stated once, and the reader that compares it with the Tofu module.

`tofu/modules/proxmox_opnsense_vm` lays the gateway's VM out for Proxmox. A gateway under QEMU on a CI runner has to be laid
out the same way, or a run there would measure another machine. `STATED` is the layout `qemu_argv` builds the command line
from; `read_module_layout` reads the same facts out of the module's files, and `drift` names every difference, so a change to
either side alone fails a test. Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parents[2] / "tofu" / "modules" / "proxmox_opnsense_vm"
SCSI_HARDWARE = "virtio-scsi-single"
NIC_MODELS = {"virtio": "virtio-net-pci"}
MAC_PREFIX = "52:54:00:00:00"  # locally administered; the module's own prefix comes from the VM id, which a runner has none of
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
VAR_RE = re.compile(r"var\.(\w+)")
VM_RESOURCE = ("proxmox_virtual_environment_vm", "this")


class LayoutError(Exception):
    """The module's files are not shaped the way the reader expects, or the layout cannot be built into a command line."""


@dataclass(frozen=True)
class Disk:
    interface: str
    iothread: bool = False
    discard: bool = False
    ssd: bool = False


@dataclass(frozen=True)
class Nic:
    role: str  # wan or lan
    model: str


@dataclass(frozen=True)
class Layout:
    machine: str
    scsi_hardware: str
    boot_order: tuple[str, ...]
    cores: int
    memory_mb: int
    disk_gb: int  # the system disk, the first
    disks: tuple[Disk, ...]
    nics: tuple[Nic, ...]  # in the order the guest sees them: the WAN first
    serial: str


STATED = Layout(
    machine="q35",
    scsi_hardware=SCSI_HARDWARE,
    boot_order=("scsi0",),
    cores=2,
    memory_mb=2048,
    disk_gb=32,
    disks=(Disk("scsi0", iothread=True, discard=True, ssd=True), Disk("scsi1")),
    nics=(Nic("wan", "virtio"), Nic("lan", "virtio")),
    serial="socket",
)


@dataclass
class Block:
    kind: str
    labels: tuple[str, ...]
    attrs: dict[str, str] = field(default_factory=dict)  # each value as written, a reference or a string with its quotes
    children: list[Block] = field(default_factory=list)

    def child(self, kind: str, *labels: str) -> Block:
        found = [block for block in self.children if block.kind == kind and block.labels == labels]
        if len(found) != 1:
            raise LayoutError(f"expected one `{kind}` block in `{self.kind}`, found {len(found)}")
        return found[0]


class _Reader:
    """Reads the part of HCL the module is written in: blocks, `name = expression` lines, strings with `${}`, comments."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def skip_space(self, *, newlines: bool = True) -> None:
        text = self.text
        while self.pos < len(text):
            char = text[self.pos]
            if char in " \t\r" or (newlines and char == "\n"):
                self.pos += 1
            elif char == "#" or text.startswith("//", self.pos):
                end = text.find("\n", self.pos)
                self.pos = len(text) if end < 0 else end
            elif text.startswith("/*", self.pos):
                end = text.find("*/", self.pos + 2)
                if end < 0:
                    raise LayoutError("a comment is never closed")
                self.pos = end + 2
            else:
                break

    def skip_string(self) -> None:
        """Leave the position after the string that starts at the quote under it."""
        text = self.text
        self.pos += 1
        while self.pos < len(text):
            if text[self.pos] == "\\":
                self.pos += 2
            elif text.startswith(("${", "%{"), self.pos):
                self.skip_template()
            elif text[self.pos] == '"':
                self.pos += 1
                return
            else:
                self.pos += 1
        raise LayoutError("a string is never closed")

    def skip_template(self) -> None:
        text = self.text
        self.pos += 2
        depth = 1
        while self.pos < len(text):
            char = text[self.pos]
            if char == '"':
                self.skip_string()
                continue
            self.pos += 1
            depth += char == "{"
            depth -= char == "}"
            if depth == 0:
                return
        raise LayoutError("a `${` is never closed")

    def expression(self) -> str:
        """The text up to the end of the line, or the end of the brackets the line opens."""
        text = self.text
        start, depth = self.pos, 0
        while self.pos < len(text):
            char = text[self.pos]
            if char == '"':
                self.skip_string()
                continue
            if text.startswith("<<", self.pos):
                raise LayoutError("a heredoc is not read")
            if depth == 0 and (char in "\n#}" or text.startswith("//", self.pos)):
                break
            depth += char in "([{"
            depth -= char in ")]}"
            if depth < 0:
                raise LayoutError("a closing bracket has no opening one")
            self.pos += 1
        if depth:
            raise LayoutError("a bracket is never closed")
        return text[start : self.pos].strip()

    def quoted(self) -> str:
        start = self.pos
        self.skip_string()
        return self.text[start + 1 : self.pos - 1]

    def body(self, *, closing: bool) -> tuple[dict[str, str], list[Block]]:
        attrs: dict[str, str] = {}
        children: list[Block] = []
        while True:
            self.skip_space()
            char = self.peek()
            if char == "":
                if closing:
                    raise LayoutError("a block is never closed")
                return attrs, children
            if char == "}":
                if not closing:
                    raise LayoutError("a closing brace has no block")
                self.pos += 1
                return attrs, children
            word = WORD_RE.match(self.text, self.pos)
            if word is None:
                raise LayoutError(f"unexpected {char!r} where a name should start")
            name = word.group()
            self.pos = word.end()
            self.skip_space(newlines=False)
            if self.peek() == "=":
                self.pos += 1
                self.skip_space(newlines=False)
                attrs[name] = self.expression()
                continue
            labels: list[str] = []
            while self.peek() == '"':
                labels.append(self.quoted())
                self.skip_space(newlines=False)
            if self.peek() != "{":
                raise LayoutError(f"`{name}` is neither an attribute nor a block")
            self.pos += 1
            child_attrs, child_children = self.body(closing=True)
            children.append(Block(name, tuple(labels), child_attrs, child_children))


def parse_hcl(text: str) -> Block:
    """The file as one block whose attributes and children are its top level."""
    reader = _Reader(text)
    attrs, children = reader.body(closing=False)
    return Block("file", (), attrs, children)


def _text(raw: str, what: str) -> str:
    match = re.fullmatch(r'"([^"$%\\]*)"', raw)
    if match is None:
        raise LayoutError(f"{what} is `{raw}`, which is not a plain string")
    return match.group(1)


def _number(raw: str, what: str) -> int:
    if not raw.isdecimal():
        raise LayoutError(f"{what} is `{raw}`, which is not a whole number")
    return int(raw)


def _flag(block: Block, name: str) -> bool:
    raw = block.attrs.get(name, "false")
    if raw not in ("true", "false"):
        raise LayoutError(f"`{name}` is `{raw}`, which is not true or false")
    return raw == "true"


def _strings(raw: str, what: str) -> tuple[str, ...]:
    match = re.fullmatch(r"\[(.*)\]", raw)
    if match is None:
        raise LayoutError(f"{what} is `{raw}`, which is not a list")
    return tuple(_text(item.strip(), what) for item in match.group(1).split(",") if item.strip())


class _Module:
    """The module's resource and the defaults of its variables, which a reference like `var.cores` is read through."""

    def __init__(self, module_dir: Path) -> None:
        main = parse_hcl((module_dir / "main.tf").read_text())
        variables = parse_hcl((module_dir / "variables.tf").read_text())
        self.defaults = {block.labels[0]: block.attrs["default"] for block in variables.children if block.kind == "variable" and "default" in block.attrs}
        self.vm = main.child("resource", *VM_RESOURCE)

    def attr(self, block: Block, name: str) -> str:
        if name not in block.attrs:
            raise LayoutError(f"`{block.kind}` has no `{name}`")
        raw = block.attrs[name]
        reference = VAR_RE.fullmatch(raw)
        if reference is None:
            return raw
        if reference.group(1) not in self.defaults:
            raise LayoutError(f"`{name}` refers to `{raw}`, which has no default")
        return self.defaults[reference.group(1)]

    def disk(self, block: Block) -> Disk:
        discard = _text(block.attrs["discard"], "discard") if "discard" in block.attrs else "ignore"
        if discard not in ("on", "ignore"):
            raise LayoutError(f"`discard` is `{discard}`, which is neither on nor ignore")
        return Disk(_text(self.attr(block, "interface"), "a disk's interface"), _flag(block, "iothread"), discard == "on", _flag(block, "ssd"))


def _nic_role(bridge: str) -> str:
    roles = {"var.wan_bridge": "wan", "var.lan_bridge": "lan"}
    if bridge not in roles:
        raise LayoutError(f"a network device's bridge is `{bridge}`, which is neither var.wan_bridge nor var.lan_bridge")
    return roles[bridge]


def read_module_layout(module_dir: Path = MODULE_DIR) -> Layout:
    """The layout `main.tf` gives the VM, with each `var.` reference taken from the default in `variables.tf`."""
    module = _Module(module_dir)
    vm = module.vm
    disks = [module.disk(block) for block in vm.children if block.kind == "disk"]
    for dynamic in (block for block in vm.children if block.kind == "dynamic" and block.labels == ("disk",)):
        disks.append(module.disk(dynamic.child("content")))
    first = next((block for block in vm.children if block.kind == "disk"), None)
    if first is None:
        raise LayoutError("the VM has no system disk")
    return Layout(
        machine=_text(module.attr(vm, "machine"), "machine"),
        scsi_hardware=_text(module.attr(vm, "scsi_hardware"), "scsi_hardware"),
        boot_order=_strings(module.attr(vm, "boot_order"), "boot_order"),
        cores=_number(module.attr(vm.child("cpu"), "cores"), "cores"),
        memory_mb=_number(module.attr(vm.child("memory"), "dedicated"), "memory"),
        disk_gb=_number(module.attr(first, "size"), "the system disk's size"),
        disks=tuple(disks),
        nics=tuple(
            Nic(_nic_role(block.attrs.get("bridge", "")), _text(module.attr(block, "model"), "a NIC's model"))
            for block in vm.children
            if block.kind == "network_device"
        ),
        serial=_text(module.attr(vm.child("serial_device"), "device"), "the serial device"),
    )


def drift(stated: Layout, module: Layout) -> list[str]:
    """One sentence for each part of the layout on which the two differ; empty when they agree."""
    return [
        f"{part.name}: the module has {getattr(module, part.name)!r}, the QEMU layout has {getattr(stated, part.name)!r}"
        for part in fields(Layout)
        if getattr(stated, part.name) != getattr(module, part.name)
    ]


def _escaped(value: object) -> str:
    return str(value).replace(",", ",,")  # a comma in a QEMU option's value is written twice


def qemu_argv(
    layout: Layout, *, accel: str, system_disk: Path, seed_disk: Path, serial_socket: Path, lan_tap: str, serial_log: Path | None = None
) -> list[str]:
    """The `qemu-system-x86_64` command line that lays the VM out as `layout` says.

    `system_disk` is a qcow2 overlay on the cached image and `seed_disk` a raw file, each given to the disk of that position. `accel` is `kvm` or
    `tcg`; the CPU model is the host's under `kvm`, since a runner's CPU is not the module's `x86-64-v2-AES`.
    """
    if layout.scsi_hardware != SCSI_HARDWARE:
        raise LayoutError(f"the command line is built for {SCSI_HARDWARE}, not {layout.scsi_hardware}")
    if accel not in ("kvm", "tcg"):
        raise LayoutError(f"accel is {accel!r}, not kvm or tcg")
    if layout.serial != "socket":
        raise LayoutError(f"the serial device is built as a socket, not {layout.serial!r}")
    if len(layout.disks) != 2:
        raise LayoutError(f"the command line takes a system disk and a seed disk, not {len(layout.disks)} disks")
    files = (system_disk, seed_disk)
    formats = ("qcow2", "raw")
    argv = ["qemu-system-x86_64", "-accel", accel, "-cpu", "host" if accel == "kvm" else "max"]
    argv += ["-machine", layout.machine, "-smp", str(layout.cores), "-m", str(layout.memory_mb), "-display", "none", "-monitor", "none"]
    chardev = f"socket,id=ser0,path={_escaped(serial_socket)},server=on,wait=off"
    argv += ["-chardev", chardev + (f",logfile={_escaped(serial_log)}" if serial_log else ""), "-serial", "chardev:ser0"]
    for disk, path, file_format in zip(layout.disks, files, formats, strict=True):
        # virtio-scsi-single gives each disk a controller of its own, which is also where its iothread is attached.
        controller = f"virtio-scsi-pci,id=ctl-{disk.interface}"
        if disk.iothread:
            argv += ["-object", f"iothread,id=io-{disk.interface}"]
            controller += f",iothread=io-{disk.interface}"
        drive = f"if=none,id={disk.interface},file={_escaped(path)},format={file_format}" + (",discard=unmap" if disk.discard else "")
        device = f"scsi-hd,drive={disk.interface},bus=ctl-{disk.interface}.0" + (",rotation_rate=1" if disk.ssd else "")
        if disk.interface in layout.boot_order:
            device += f",bootindex={layout.boot_order.index(disk.interface) + 1}"
        argv += ["-device", controller, "-drive", drive, "-device", device]
    for index, nic in enumerate(layout.nics):
        if nic.model not in NIC_MODELS:
            raise LayoutError(f"the NIC model {nic.model!r} has no QEMU device here")
        backend = "user" if nic.role == "wan" else f"tap,ifname={_escaped(lan_tap)},script=no,downscript=no"
        argv += ["-netdev", f"{backend},id={nic.role}", "-device", f"{NIC_MODELS[nic.model]},netdev={nic.role},mac={MAC_PREFIX}:{index:02x}"]
    return argv
