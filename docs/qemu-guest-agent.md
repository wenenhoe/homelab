# QEMU Guest Agent

Installs `qemu-guest-agent` so Proxmox can read the VM's IP/hostname and
issue a clean shutdown instead of a hard power-off.

## Why there's no enable/start task

The package ships `qemu-guest-agent.service` as a "static" unit:

```
[Unit]
BindsTo=dev-virtio\x2dports-org.qemu.guest_agent.0.device
After=dev-virtio\x2dports-org.qemu.guest_agent.0.device

[Service]
ExecStart=-/usr/sbin/qemu-ga
Restart=always
RestartSec=0

[Install]
```

There's no `WantedBy=` in `[Install]`, so `systemctl enable` has nothing
to symlink — systemd itself reports the unit isn't "meant to be enabled
or disabled using systemctl" (`is-enabled` reports `static`, not
`enabled`; confirmed against the real Ubuntu package). Activation
instead comes from `/usr/lib/udev/rules.d/60-qemu-guest-agent.rules`,
which sets `SYSTEMD_WANTS=qemu-guest-agent.service` the moment the VM's
virtio-serial channel device appears. The package's own `postinst`
already fires that trigger once on install, and udev repeats it on
every later boot.

Forcing `state: started` on top of that adds nothing on a correctly
configured VM (already active by the time Ansible runs) and hard-fails
on any host where the channel isn't present — a Proxmox VM with "QEMU
Guest Agent" left unchecked, or a plain container. That failure mode
isn't something Ansible can fix from inside the guest, so the role
doesn't try: if the agent never comes up, check the VM's Proxmox
options first, not this role.

## Verifying on a real host

```sh
systemctl status qemu-guest-agent   # active (running) once the channel exists
systemctl is-enabled qemu-guest-agent   # reports "static", not "enabled" - expected
```
