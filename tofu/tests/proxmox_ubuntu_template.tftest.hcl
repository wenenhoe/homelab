mock_provider "proxmox" {
  mock_resource "proxmox_download_file" {
    defaults = {
      id = "local:import/ubuntu-26.04-server-cloudimg-amd64.qcow2"
    }
  }
}

variables {
  node_name      = "pve"
  image_url      = "https://cloud-images.ubuntu.com/releases/26.04/release-20260927/ubuntu-26.04-server-cloudimg-amd64.img"
  image_checksum = "0000000000000000000000000000000000000000000000000000000000000000"
}

run "downloads_the_pinned_image_as_an_import_file" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_template"
  }

  assert {
    condition     = proxmox_download_file.image.content_type == "import"
    error_message = "the image must be stored as import content, which import_from requires"
  }

  assert {
    condition     = proxmox_download_file.image.file_name == "ubuntu-26.04-server-cloudimg-amd64.qcow2"
    error_message = "the .img file must be stored under a .qcow2 name"
  }

  assert {
    condition     = proxmox_download_file.image.checksum_algorithm == "sha256" && proxmox_download_file.image.checksum == var.image_checksum
    error_message = "the download must be verified against the given SHA-256"
  }
}

run "builds_a_template_that_is_never_started" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_template"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.template.template == true && proxmox_virtual_environment_vm.template.started == false
    error_message = "the VM must be a stopped template"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.template.vm_id == 106
    error_message = "the template must default to VMID 106, in the 1XX range"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.template.scsi_hardware == "virtio-scsi-single" && proxmox_virtual_environment_vm.template.disk[0].iothread == true
    error_message = "the template's disk must use iothread on the controller that supports it"
  }
}

run "rejects_a_vmid_outside_the_template_range" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_template"
  }

  variables {
    vm_id = 206
  }

  expect_failures = [var.vm_id]
}

run "rejects_a_checksum_that_is_not_sha256_hex" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_template"
  }

  variables {
    image_checksum = "not-a-checksum"
  }

  expect_failures = [var.image_checksum]
}

run "rejects_a_plain_http_image_url" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_template"
  }

  variables {
    image_url = "http://cloud-images.ubuntu.com/releases/26.04/release-20260927/ubuntu-26.04-server-cloudimg-amd64.img"
  }

  expect_failures = [var.image_url]
}
