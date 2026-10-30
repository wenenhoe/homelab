locals {
  # With image_volume_id the image is already on the node; otherwise it is fetched here and uploaded.
  fetch_image = var.image_volume_id == null && var.image_url != null
  image_bz2   = local.fetch_image ? "${var.image_cache_dir}/${basename(var.image_url)}" : null
  image_img   = local.fetch_image ? trimsuffix(local.image_bz2, ".bz2") : null
  # Proxmox accepts import content only under a .raw, .qcow2 or .vmdk name,
  # and the nano image is a raw disk.
  image_file_name = local.fetch_image ? "${trimsuffix(basename(local.image_img), ".img")}.raw" : null
  image_volume    = local.fetch_image ? one(proxmox_virtual_environment_file.image[*].id) : var.image_volume_id
  mac_prefix      = format("BC:24:11:%02X:%02X", floor(var.vm_id / 256), var.vm_id % 256)
}

# Proxmox refuses to decompress a download of import content, and OPNsense
# publishes the image only as .img.bz2, so the host running Tofu downloads it,
# checks the published checksum and unpacks it before it is uploaded.
resource "terraform_data" "image" {
  count = local.fetch_image ? 1 : 0

  triggers_replace = [var.image_url, var.image_checksum]
  input            = local.image_img

  provisioner "local-exec" {
    interpreter = ["bash", "-euo", "pipefail", "-c"]
    environment = {
      URL = var.image_url
      SUM = var.image_checksum
      BZ2 = local.image_bz2
    }
    command = "bash \"${path.module}/fetch_image.sh\""
  }
}

resource "proxmox_virtual_environment_file" "image" {
  count = local.fetch_image ? 1 : 0

  node_name    = var.node_name
  datastore_id = var.image_datastore_id
  content_type = "import"

  source_file {
    path      = one(terraform_data.image[*].output)
    file_name = local.image_file_name
  }

  lifecycle {
    replace_triggered_by = [terraform_data.image]
  }
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
    import_from  = local.image_volume
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

  # started decides only whether the VM boots when it is created. A later apply
  # would otherwise stop a running gateway to match started = false.
  lifecycle {
    ignore_changes = [started]

    precondition {
      condition     = var.image_volume_id == null ? (var.image_url != null && var.image_checksum != null) : (var.image_url == null && var.image_checksum == null)
      error_message = "Give either image_url with image_checksum, or image_volume_id alone."
    }
  }
}
