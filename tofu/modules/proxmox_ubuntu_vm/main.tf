locals {
  vlan_id       = floor(var.vm_id / 100) * 10
  host_octet    = var.vm_id % 100
  subnet_prefix = "192.168.${local.vlan_id}"
  ip_address    = "${local.subnet_prefix}.${local.host_octet}"
  gateway       = "${local.subnet_prefix}.1"
  mac_address   = format("BC:24:11:%02X:%02X:00", floor(var.vm_id / 256), var.vm_id % 256)
  dns_servers   = var.dns_servers == null ? [local.gateway] : var.dns_servers
}

resource "proxmox_virtual_environment_vm" "this" {
  node_name = var.node_name
  vm_id     = var.vm_id
  name      = var.name
  tags      = sort(concat(["tofu", "ubuntu"], var.tags))

  clone {
    vm_id        = var.template_vm_id
    datastore_id = var.datastore_id
    full         = true
  }

  # Without the agent, shutdown relies on ACPI, which the provider documents
  # as unreliable, so destroy powers the VM off.
  stop_on_destroy = true

  cpu {
    cores = var.cores
    type  = "x86-64-v2-AES"
  }

  memory {
    dedicated = var.memory_mb
  }

  # For scsi_hardware and every disk attribute below, the provider plans the
  # schema default over the template's value unless it is repeated here.
  scsi_hardware = "virtio-scsi-single"

  disk {
    datastore_id = var.datastore_id
    interface    = "scsi0"
    iothread     = true
    discard      = "on"
    ssd          = true
    size         = var.disk_gb
  }

  network_device {
    bridge      = var.lan_bridge
    vlan_id     = local.vlan_id
    mac_address = local.mac_address
    model       = "virtio"
  }

  initialization {
    datastore_id = var.datastore_id

    dns {
      domain  = var.dns_domain
      servers = local.dns_servers
    }

    ip_config {
      ipv4 {
        address = "${local.ip_address}/24"
        gateway = local.gateway
      }
    }

    user_account {
      username = var.admin_username
      keys     = var.ssh_public_keys
    }
  }
}
