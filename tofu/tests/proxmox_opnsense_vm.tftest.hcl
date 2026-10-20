mock_provider "proxmox" {
  mock_resource "proxmox_download_file" {
    defaults = {
      id = "local:iso/OPNsense-26.1-dvd-amd64.iso"
    }
  }
}

variables {
  node_name    = "pve"
  iso_url      = "https://mirror.example.net/releases/26.1/OPNsense-26.1-dvd-amd64.iso.bz2"
  iso_checksum = "0000000000000000000000000000000000000000000000000000000000000000"
}

run "fetches_the_installer_and_unpacks_it_as_an_iso" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  assert {
    condition     = proxmox_download_file.iso.content_type == "iso" && proxmox_download_file.iso.decompression_algorithm == "bz2"
    error_message = "the .iso.bz2 must be downloaded as iso content and decompressed"
  }

  assert {
    condition     = proxmox_download_file.iso.file_name == "OPNsense-26.1-dvd-amd64.iso"
    error_message = "the unpacked file must be stored under a .iso name"
  }

  assert {
    condition     = proxmox_download_file.iso.datastore_id == "tofu-images"
    error_message = "the installer must be stored on the images storage the token can delete from"
  }

  assert {
    condition     = proxmox_download_file.iso.checksum_algorithm == "sha256" && proxmox_download_file.iso.checksum == var.iso_checksum
    error_message = "the download must be verified against the given SHA-256"
  }
}

run "attaches_the_installer_and_boots_the_disk_first" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.cdrom[0].file_id == "local:iso/OPNsense-26.1-dvd-amd64.iso" && proxmox_virtual_environment_vm.this.cdrom[0].interface == "ide2"
    error_message = "the installer must be attached as the CD-ROM"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.boot_order == tolist(["scsi0", "ide2"])
    error_message = "the disk must come before the installer, so an installed VM boots from it"
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

run "rejects_an_installer_that_is_not_a_bzip2_iso" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    iso_url = "https://mirror.example.net/releases/26.1/OPNsense-26.1-dvd-amd64.iso"
  }

  expect_failures = [var.iso_url]
}

run "rejects_a_checksum_that_is_not_sha256_hex" {
  command = plan

  module {
    source = "./modules/proxmox_opnsense_vm"
  }

  variables {
    iso_checksum = "not-a-checksum"
  }

  expect_failures = [var.iso_checksum]
}
