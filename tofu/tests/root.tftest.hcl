mock_provider "proxmox" {
  mock_resource "proxmox_download_file" {
    defaults = {
      id = "local:import/ubuntu-26.04-server-cloudimg-amd64.qcow2"
    }
  }
}

variables {
  proxmox_endpoint        = "https://pve.example.lan:8006/"
  proxmox_api_token       = "tofu@pve!skeleton=secret"
  dns_domain              = "internal.example.com"
  ansible_ssh_public_keys = ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest test"]
}

run "builds_the_template_from_the_pinned_image" {
  command = plan

  assert {
    condition     = module.ubuntu_template.vm_id == 106
    error_message = "the root module must build the template in the 1XX range"
  }
}

run "imports_the_prepared_image_named_after_the_pinned_release" {
  command = plan

  assert {
    condition     = module.ubuntu_template.image_volume_id == "tofu-images:import/ubuntu-26.04-server-cloudimg-amd64-release-20260927-no-initrd-network.qcow2"
    error_message = "the template must import the prepared copy that prepare_image.sh names from the pinned URL"
  }
}

run "a_new_pin_selects_a_new_volume" {
  command = plan

  variables {
    ubuntu_image_url = "https://cloud-images.ubuntu.com/releases/26.04/release-20261101/ubuntu-26.04-server-cloudimg-amd64.img"
  }

  assert {
    condition     = endswith(module.ubuntu_template.image_volume_id, "-release-20261101-no-initrd-network.qcow2")
    error_message = "a different release directory must give a different volume, so the template is replaced"
  }
}

run "rejects_a_pin_that_is_not_a_release_image" {
  command = plan

  variables {
    ubuntu_image_url = "http://cloud-images.ubuntu.com/releases/26.04/release-20260927/ubuntu.img"
  }

  expect_failures = [var.ubuntu_image_url]
}

run "rejects_a_pin_checksum_that_is_not_sha256_hex" {
  command = plan

  variables {
    ubuntu_image_checksum = "nope"
  }

  expect_failures = [var.ubuntu_image_checksum]
}

run "prints_the_command_that_prepares_the_image" {
  command = plan

  assert {
    condition     = endswith(output.ubuntu_image_prepare_command, "release-20260927/ubuntu-26.04-server-cloudimg-amd64.img 8800651811af9a85465ad1d552add729947bb16488dddb4a9b5305a3d97332b2 OUT_DIR")
    error_message = "the printed command must carry the pinned URL and checksum"
  }
}

run "declares_the_play_host_on_its_vmid" {
  command = plan

  assert {
    condition     = module.play.vm_id == 204 && module.play.hostname == "play"
    error_message = "the play host must be VMID 204, named play"
  }
}

run "declares_the_security_host_on_its_vmid" {
  command = plan

  assert {
    condition     = module.security.vm_id == 205 && module.security.hostname == "security"
    error_message = "the security host must be VMID 205, named security"
  }
}

run "publishes_the_hosts_for_the_inventory_generator" {
  command = plan

  assert {
    condition     = length(output.ansible_hosts) == 2
    error_message = "ansible_hosts must name exactly the VMs the root declares"
  }

  assert {
    condition     = output.ansible_hosts.play.ip_address == "192.168.20.4" && output.ansible_hosts.play.admin_username == "playadmin"
    error_message = "the play entry must carry the VMID-derived address and the admin user the inventory used"
  }

  assert {
    condition     = output.ansible_hosts.security.ip_address == "192.168.20.5" && output.ansible_hosts.security.admin_username == "secadmin"
    error_message = "the security entry must carry the VMID-derived address and the admin user the inventory used"
  }
}
