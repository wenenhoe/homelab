mock_provider "proxmox" {}

variables {
  node_name       = "pve"
  name            = "services"
  template_vm_id  = 106
  admin_username  = "svcadmin"
  ssh_public_keys = ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest test"]
}

run "derives_vlan_address_and_mac_from_the_vmid" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id = 203
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.network_device[0].vlan_id == 20
    error_message = "VMID 203 must be tagged with VLAN 20"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.network_device[0].mac_address == "BC:24:11:00:CB:00"
    error_message = "VMID 203 must get the MAC BC:24:11:00:CB:00"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.initialization[0].ip_config[0].ipv4[0].address == "192.168.20.3/24"
    error_message = "VMID 203 must get 192.168.20.3/24"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.initialization[0].ip_config[0].ipv4[0].gateway == "192.168.20.1"
    error_message = "the gateway must be .1 of the VM's VLAN"
  }

  assert {
    condition     = output.ip_address == "192.168.20.3" && output.mac_address == "BC:24:11:00:CB:00" && output.hostname == "services"
    error_message = "the outputs must carry the derived address, MAC and the name"
  }
}

run "keeps_the_templates_scsi_controller_and_disk_settings" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id = 203
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.scsi_hardware == "virtio-scsi-single"
    error_message = "the clone must not fall back to the schema's default SCSI controller"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.disk[0].iothread == true && proxmox_virtual_environment_vm.this.disk[0].discard == "on" && proxmox_virtual_environment_vm.this.disk[0].ssd == true
    error_message = "the clone's disk must repeat the template's iothread, discard and ssd settings"
  }
}

run "takes_a_two_digit_host_part_from_the_last_two_digits" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id = 242
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.initialization[0].ip_config[0].ipv4[0].address == "192.168.20.42/24"
    error_message = "VMID 242 must get 192.168.20.42/24"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.network_device[0].mac_address == "BC:24:11:00:F2:00"
    error_message = "VMID 242 must get the MAC BC:24:11:00:F2:00"
  }
}

run "carries_a_vmid_above_255_into_the_first_mac_byte" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id = 506
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.network_device[0].vlan_id == 50
    error_message = "VMID 506 must be tagged with VLAN 50"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.network_device[0].mac_address == "BC:24:11:01:FA:00"
    error_message = "VMID 506 must get the MAC BC:24:11:01:FA:00"
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.initialization[0].ip_config[0].ipv4[0].address == "192.168.50.6/24"
    error_message = "VMID 506 must get 192.168.50.6/24"
  }
}

run "resolves_through_the_gateway_by_default" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id = 203
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.initialization[0].dns[0].servers == tolist(["192.168.20.1"])
    error_message = "the default nameserver must be the VLAN's gateway"
  }
}

run "takes_nameservers_from_the_caller" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id       = 203
    dns_servers = ["192.168.20.9"]
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.initialization[0].dns[0].servers == tolist(["192.168.20.9"])
    error_message = "dns_servers must replace the gateway default"
  }
}

run "tags_stay_sorted_because_proxmox_sorts_them" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id = 203
    tags  = ["docker", "zebra"]
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.tags == tolist(["docker", "tofu", "ubuntu", "zebra"])
    error_message = "tags must be sorted, or every plan shows a difference"
  }
}

run "rejects_the_reserved_vmid_zero" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id = 200
  }

  expect_failures = [var.vm_id]
}

run "rejects_the_gateway_vmid" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id = 201
  }

  expect_failures = [var.vm_id]
}

run "rejects_the_gateway_vmid_of_a_later_range" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id = 301
  }

  expect_failures = [var.vm_id]
}

run "rejects_a_vmid_in_the_dhcp_pool" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id = 250
  }

  expect_failures = [var.vm_id]
}

run "rejects_a_vmid_past_the_last_vlan" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id = 602
  }

  expect_failures = [var.vm_id]
}

run "rejects_a_disk_smaller_than_the_template" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id   = 203
    disk_gb = 4
  }

  expect_failures = [var.disk_gb]
}

run "rejects_a_vm_without_ssh_keys" {
  command = plan

  module {
    source = "./modules/proxmox_ubuntu_vm"
  }

  variables {
    vm_id           = 203
    ssh_public_keys = []
  }

  expect_failures = [var.ssh_public_keys]
}
