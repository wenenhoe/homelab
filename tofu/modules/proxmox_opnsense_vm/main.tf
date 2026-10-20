locals {
  iso_file_name = trimsuffix(basename(var.iso_url), ".bz2")
  mac_prefix    = format("BC:24:11:%02X:%02X", floor(var.vm_id / 256), var.vm_id % 256)
}

resource "proxmox_download_file" "iso" {
  node_name               = var.node_name
  datastore_id            = var.iso_datastore_id
  content_type            = "iso"
  url                     = var.iso_url
  file_name               = local.iso_file_name
  checksum                = var.iso_checksum
  checksum_algorithm      = "sha256"
  decompression_algorithm = "bz2"
}

resource "proxmox_virtual_environment_vm" "this" {
  node_name   = var.node_name
  vm_id       = var.vm_id
  name        = var.name
  description = "Managed by OpenTofu. Install and initial configuration are manual."
  tags        = ["opnsense", "tofu"]

  machine       = "q35"
  scsi_hardware = "virtio-scsi-single"
  boot_order    = ["scsi0", "ide2"]

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

  disk {
    datastore_id = var.datastore_id
    interface    = "scsi0"
    iothread     = true
    discard      = "on"
    ssd          = true
    size         = var.disk_gb
  }

  cdrom {
    file_id   = proxmox_download_file.iso.id
    interface = "ide2"
  }

  network_device {
    bridge      = var.wan_bridge
    mac_address = "${local.mac_prefix}:00"
    model       = "virtio"
  }

  network_device {
    bridge      = var.lan_bridge
    mac_address = "${local.mac_prefix}:01"
    model       = "virtio"
  }

  operating_system {
    type = "other"
  }
}
