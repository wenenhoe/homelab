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
    condition     = module.ubuntu_template.image_volume_id == "tofu-images:import/ubuntu-26.04-server-cloudimg-amd64-release-20260927-prepared-Asia-Singapore.qcow2"
    error_message = "the template must import the prepared copy that prepare_image.sh names from the pinned URL"
  }
}

run "a_new_pin_selects_a_new_volume" {
  command = plan

  variables {
    ubuntu_image_url = "https://cloud-images.ubuntu.com/releases/26.04/release-20261101/ubuntu-26.04-server-cloudimg-amd64.img"
  }

  assert {
    condition     = endswith(module.ubuntu_template.image_volume_id, "-release-20261101-prepared-Asia-Singapore.qcow2")
    error_message = "a different release directory must give a different volume, so the template is replaced"
  }
}

run "another_timezone_selects_a_new_volume_and_is_passed_to_the_script" {
  command = plan

  variables {
    timezone = "Europe/Paris"
  }

  assert {
    condition     = endswith(module.ubuntu_template.image_volume_id, "-prepared-Europe-Paris.qcow2")
    error_message = "a different timezone must give a different volume, so the template is replaced"
  }

  assert {
    condition     = endswith(output.ubuntu_image_prepare_command, " OUT_DIR Europe/Paris")
    error_message = "the printed command must carry the timezone the image is prepared for"
  }
}

run "rejects_a_timezone_that_is_not_a_zoneinfo_name" {
  command = plan

  variables {
    timezone = "../etc/passwd"
  }

  expect_failures = [var.timezone]
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
    condition     = endswith(output.ubuntu_image_prepare_command, "release-20260927/ubuntu-26.04-server-cloudimg-amd64.img 8800651811af9a85465ad1d552add729947bb16488dddb4a9b5305a3d97332b2 OUT_DIR Asia/Singapore")
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

run "declares_the_tailscale_host_on_its_vmid" {
  command = plan

  assert {
    condition     = module.tailscale.vm_id == 202 && module.tailscale.hostname == "tailscale"
    error_message = "the tailscale host must be VMID 202, named tailscale"
  }
}

run "declares_the_services_host_on_its_vmid" {
  command = plan

  assert {
    condition     = module.services.vm_id == 203 && module.services.hostname == "services"
    error_message = "the services host must be VMID 203, named services"
  }
}

run "declares_the_storage_host_on_its_vmid" {
  command = plan

  assert {
    condition     = module.storage.vm_id == 206 && module.storage.hostname == "storage"
    error_message = "the storage host must be VMID 206, named storage"
  }
}

run "puts_the_storage_hosts_disk_on_the_backup_datastore" {
  command = plan

  assert {
    condition     = module.storage.datastore_id == "backup"
    error_message = "the storage host's disk must sit on the backup datastore, not on the disk of the hosts it protects"
  }
}

run "keeps_the_other_hosts_off_the_backup_datastore" {
  command = plan

  assert {
    condition     = module.play.datastore_id == "local-lvm" && module.security.datastore_id == "local-lvm" && module.tailscale.datastore_id == "local-lvm" && module.services.datastore_id == "local-lvm"
    error_message = "only the storage host's disk may sit on the backup datastore"
  }
}

run "publishes_the_hosts_for_the_inventory_generator" {
  command = plan

  assert {
    condition     = length(output.ansible_hosts) == 5
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

  assert {
    condition     = output.ansible_hosts.storage.ip_address == "192.168.20.6" && output.ansible_hosts.storage.admin_username == "storeadmin"
    error_message = "the storage entry must carry the VMID-derived address and the admin user the inventory used"
  }

  assert {
    condition     = output.ansible_hosts.services.ip_address == "192.168.20.3" && output.ansible_hosts.services.admin_username == "svcadmin"
    error_message = "the services entry must carry the VMID-derived address and the admin user the inventory used"
  }

  assert {
    condition     = output.ansible_hosts.tailscale.ip_address == "192.168.20.2" && output.ansible_hosts.tailscale.admin_username == "tsadmin"
    error_message = "the tailscale entry must carry the VMID-derived address and the admin user the inventory used"
  }
}
