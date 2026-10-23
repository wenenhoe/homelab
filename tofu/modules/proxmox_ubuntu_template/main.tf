locals {
  image_file_name = "${trimsuffix(basename(var.image_url), ".img")}.qcow2"
}

resource "proxmox_download_file" "image" {
  node_name          = var.node_name
  datastore_id       = var.image_datastore_id
  content_type       = "import"
  url                = var.image_url
  file_name          = local.image_file_name
  checksum           = var.image_checksum
  checksum_algorithm = "sha256"
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
    import_from  = proxmox_download_file.image.id
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
}
