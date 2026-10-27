mock_provider "proxmox" {}

override_resource {
  target = proxmox_virtual_environment_file.image
  values = {
    id = "tofu-images:import/OPNsense-26.1.6-nano-amd64.raw"
  }
}

override_resource {
  target = proxmox_virtual_environment_file.seed
  values = {
    id = "tofu-images:import/opnsense-seed.raw"
  }
}

variables {
  node_name      = "pve"
  image_url      = "https://mirror.example.net/releases/26.1/OPNsense-26.1.6-nano-amd64.img.bz2"
  image_checksum = "0000000000000000000000000000000000000000000000000000000000000000"
}

run "uploads_the_unpacked_image_as_import_content" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  assert {
    condition     = proxmox_virtual_environment_file.image.content_type == "import" && proxmox_virtual_environment_file.image.datastore_id == "tofu-images"
    error_message = "the image must be uploaded as import content to the images storage the token can delete from"
  }

  assert {
    condition     = proxmox_virtual_environment_file.image.source_file[0].file_name == "OPNsense-26.1.6-nano-amd64.raw"
    error_message = "the image must be stored under a .raw name, which is what Proxmox accepts for import content"
  }
}

run "fetches_the_image_again_when_its_url_or_checksum_changes" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  assert {
    condition     = terraform_data.image.triggers_replace[0] == var.image_url && terraform_data.image.triggers_replace[1] == var.image_checksum
    error_message = "a new URL or checksum must fetch and unpack the image again"
  }

  assert {
    condition     = terraform_data.image.input == ".image-cache/OPNsense-26.1.6-nano-amd64.img"
    error_message = "the unpacked image must land in the cache directory under the release's file name"
  }
}

run "imports_the_image_as_the_system_disk_and_boots_it" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.disk[0].interface == "scsi0" && proxmox_virtual_environment_vm.this.disk[0].import_from == "tofu-images:import/OPNsense-26.1.6-nano-amd64.raw" && proxmox_virtual_environment_vm.this.disk[0].size == 32
    error_message = "the image must be the first disk, on scsi0, imported from the download and sized to disk_gb"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.boot_order == tolist(["scsi0"])
    error_message = "only the system disk may be booted, so the seed disk never is"
  }

  assert {
    condition     = length(proxmox_virtual_environment_vm.this.cdrom) == 0
    error_message = "no installer media is attached"
  }
}

run "gives_the_vm_a_serial_port_on_a_socket" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  assert {
    condition     = length(proxmox_virtual_environment_vm.this.serial_device) == 1 && proxmox_virtual_environment_vm.this.serial_device[0].device == "socket"
    error_message = "the console must be a serial port on a socket for the node's script to reach"
  }
}

run "uploads_the_seed_as_import_content_and_attaches_it_as_a_second_disk" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    seed_image_path = "./modules/proxmox_opnsense_vm/main.tf"
    started         = false
  }

  assert {
    condition     = proxmox_virtual_environment_file.seed[0].content_type == "import" && proxmox_virtual_environment_file.seed[0].datastore_id == "tofu-images" && proxmox_virtual_environment_file.seed[0].source_file[0].file_name == "opnsense-seed.raw"
    error_message = "the seed must be uploaded as import content under a .raw name, next to the image"
  }

  assert {
    condition     = proxmox_virtual_environment_file.seed[0].source_file[0].checksum == filesha256("./modules/proxmox_opnsense_vm/main.tf")
    error_message = "the upload must carry the seed's SHA-256, so a changed seed is uploaded again"
  }

  assert {
    condition     = length(proxmox_virtual_environment_vm.this.disk) == 2 && proxmox_virtual_environment_vm.this.disk[1].interface == "scsi1" && proxmox_virtual_environment_vm.this.disk[1].import_from == "tofu-images:import/opnsense-seed.raw" && proxmox_virtual_environment_vm.this.disk[1].file_format == "raw"
    error_message = "the seed must be the second disk, on scsi1, imported from the uploaded file"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.disk[0].interface == "scsi0" && proxmox_virtual_environment_vm.this.boot_order == tolist(["scsi0"])
    error_message = "the system disk stays scsi0 and the only boot device"
  }
}

run "names_the_seed_after_the_vm_so_two_gateways_do_not_share_it" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    name            = "Opn-Scratch"
    seed_image_path = "./modules/proxmox_opnsense_vm/main.tf"
  }

  assert {
    condition     = proxmox_virtual_environment_file.seed[0].source_file[0].file_name == "opn-scratch-seed.raw"
    error_message = "the seed's file name must derive from the lowercased VM name"
  }
}

run "without_a_seed_the_vm_has_only_its_system_disk" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  assert {
    condition     = length(proxmox_virtual_environment_file.seed) == 0 && length(proxmox_virtual_environment_vm.this.disk) == 1
    error_message = "no seed path must mean no upload and a single disk"
  }
}

run "starts_the_vm_unless_the_caller_holds_it_back" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.started == true
    error_message = "the VM must start by default"
  }
}

run "creates_the_vm_stopped_when_asked" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    started = false
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.started == false
    error_message = "started = false must create the VM stopped, so the script can connect before the first boot"
  }
}

run "puts_the_wan_and_lan_nics_on_their_bridges_untagged" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.network_device[0].bridge == "vmbr0" && proxmox_virtual_environment_vm.this.network_device[1].bridge == "vmbr1"
    error_message = "the first NIC must be on the WAN bridge and the second on the LAN bridge"
  }

  assert {
    condition     = coalesce(proxmox_virtual_environment_vm.this.network_device[0].vlan_id, 0) == 0 && coalesce(proxmox_virtual_environment_vm.this.network_device[1].vlan_id, 0) == 0
    error_message = "neither NIC may carry a VLAN tag"
  }
}

run "tags_the_wan_nic_onto_a_vlan_of_the_lan_bridge" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    wan_bridge  = "vmbr1"
    wan_vlan_id = 20
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.network_device[0].bridge == "vmbr1" && proxmox_virtual_environment_vm.this.network_device[0].vlan_id == 20
    error_message = "the WAN NIC must carry the given tag on the given bridge"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.network_device[1].bridge == "vmbr1" && coalesce(proxmox_virtual_environment_vm.this.network_device[1].vlan_id, 0) == 0
    error_message = "the LAN NIC must stay untagged so OPNsense sees every VLAN"
  }
}

run "rejects_a_wan_vlan_outside_the_valid_range" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    wan_vlan_id = 4095
  }

  expect_failures = [var.wan_vlan_id]
}

run "derives_the_macs_from_the_vmid_and_nic_index" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.network_device[0].mac_address == "BC:24:11:00:C9:00" && proxmox_virtual_environment_vm.this.network_device[1].mac_address == "BC:24:11:00:C9:01"
    error_message = "VMID 201 must get the MACs BC:24:11:00:C9:00 and BC:24:11:00:C9:01"
  }

  assert {
    condition     = output.wan_mac_address == "BC:24:11:00:C9:00" && output.lan_mac_address == "BC:24:11:00:C9:01"
    error_message = "the outputs must carry the NIC MACs"
  }
}

run "carries_a_vmid_above_255_into_the_first_mac_byte" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    vm_id = 501
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.network_device[1].mac_address == "BC:24:11:01:F5:01"
    error_message = "VMID 501 must get the LAN MAC BC:24:11:01:F5:01"
  }
}

run "rejects_a_vmid_that_is_not_a_gateway_vmid" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    vm_id = 202
  }

  expect_failures = [var.vm_id]
}

run "rejects_an_image_that_is_not_a_bzip2_img" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    image_url = "https://mirror.example.net/releases/26.1/OPNsense-26.1.6-nano-amd64.img"
  }

  expect_failures = [var.image_url]
}

run "rejects_an_image_that_is_not_the_nano_one" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    image_url = "https://mirror.example.net/releases/26.1/OPNsense-26.1-vga-amd64.img.bz2"
  }

  expect_failures = [var.image_url]
}

run "rejects_an_image_url_that_is_not_https" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    image_url = "http://mirror.example.net/releases/26.1/OPNsense-26.1.6-nano-amd64.img.bz2"
  }

  expect_failures = [var.image_url]
}

run "rejects_a_checksum_that_is_not_sha256_hex" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    image_checksum = "not-a-checksum"
  }

  expect_failures = [var.image_checksum]
}
