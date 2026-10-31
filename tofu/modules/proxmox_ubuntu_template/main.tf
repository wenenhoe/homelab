locals {
  # With image_volume_id the image is already on the node; otherwise Proxmox downloads it.
  download_image  = var.image_volume_id == null && var.image_url != null && var.image_checksum != null
  image_file_name = local.download_image ? "${trimsuffix(basename(var.image_url), ".img")}.qcow2" : null
  image_volume    = local.download_image ? one(proxmox_download_file.image[*].id) : var.image_volume_id
}

resource "proxmox_download_file" "image" {
  count = local.download_image ? 1 : 0

  node_name          = var.node_name
  datastore_id       = var.image_datastore_id
  content_type       = "import"
  url                = var.image_url
  file_name          = local.image_file_name
  checksum           = var.image_checksum
  checksum_algorithm = "sha256"
}

# The provider imports a disk only when it creates it and ignores a changed import_from on an
# existing one, so the template is replaced whenever the source of its image changes.
resource "terraform_data" "image" {
  input = [var.image_url, var.image_checksum, var.image_volume_id]
}

resource "proxmox_virtual_environment_vm" "template" {
  node_name   = var.node_name
  vm_id       = var.vm_id
  name        = var.name
  description = "Managed by OpenTofu"
  tags        = ["tofu", "ubuntu"]

  template = true
  started  = false

  machine       = "q35"
  bios          = "ovmf"
  scsi_hardware = "virtio-scsi-single"

  cpu {
    cores = 2
    type  = "x86-64-v2-AES"
  }

  memory {
    dedicated = 2048
  }

  disk {
    datastore_id = var.datastore_id
    import_from  = local.image_volume
    interface    = "scsi0"
    iothread     = true
    discard      = "on"
    ssd          = true
    size         = 8
  }

  efi_disk {
    datastore_id      = var.datastore_id
    type              = "4m"
    pre_enrolled_keys = true
  }

  initialization {
    datastore_id = var.datastore_id
  }

  operating_system {
    type = "l26"
  }

  serial_device {}

  lifecycle {
    replace_triggered_by = [terraform_data.image]

    precondition {
      condition     = var.image_volume_id == null ? (var.image_url != null && var.image_checksum != null) : (var.image_url == null && var.image_checksum == null)
      error_message = "Give either image_url with image_checksum, or image_volume_id alone."
    }
  }
}
