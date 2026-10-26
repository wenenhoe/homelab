locals {
  # Proxmox accepts import content only under a .raw, .qcow2 or .vmdk name,
  # and the nano image is a raw disk.
  image_file_name = "${trimsuffix(trimsuffix(basename(var.image_url), ".bz2"), ".img")}.raw"
  mac_prefix      = format("BC:24:11:%02X:%02X", floor(var.vm_id / 256), var.vm_id % 256)
}

resource "proxmox_download_file" "image" {
  node_name               = var.node_name
  datastore_id            = var.image_datastore_id
  content_type            = "import"
  url                     = var.image_url
  file_name               = local.image_file_name
  checksum                = var.image_checksum
  checksum_algorithm      = "sha256"
  decompression_algorithm = "bz2"
}

resource "proxmox_virtual_environment_file" "seed" {
  count = var.seed_image_path == null ? 0 : 1

  node_name    = var.node_name
  datastore_id = var.image_datastore_id
  content_type = "import"

  source_file {
    path      = var.seed_image_path
    file_name = "${lower(var.name)}-seed.raw"
    checksum  = filesha256(var.seed_image_path)
  }
}

resource "proxmox_virtual_environment_vm" "this" {
  node_name   = var.node_name
  vm_id       = var.vm_id
  name        = var.name
  description = "Managed by OpenTofu. The seed disk carries the first configuration; the rest is applied by the Ansible play."
  tags        = ["opnsense", "tofu"]

  machine       = "q35"
  scsi_hardware = "virtio-scsi-single"
  boot_order    = ["scsi0"]

  started = var.started

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
    import_from  = proxmox_download_file.image.id
    interface    = "scsi0"
    iothread     = true
    discard      = "on"
    ssd          = true
    size         = var.disk_gb
  }

  dynamic "disk" {
    for_each = proxmox_virtual_environment_file.seed

    content {
      datastore_id = var.datastore_id
      import_from  = disk.value.id
      interface    = "scsi1"
      file_format  = "raw"
      size         = 1
    }
  }

  network_device {
    bridge      = var.wan_bridge
    vlan_id     = var.wan_vlan_id
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

  # The image's console is the serial port, and the script that answers the
  # importer and reads the gateway's certificate talks to this socket.
  serial_device {
    device = "socket"
  }
}
