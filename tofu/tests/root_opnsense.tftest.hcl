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

run "declares_the_production_gateway_as_vmid_201" {
  command = plan

  assert {
    condition     = module.opnsense.vm_id == 201
    error_message = "the production gateway must be VMID 201, which the hosts' neighbour tables and the MAC scheme rest on"
  }
}

run "derives_the_macs_from_the_gateway_vmid" {
  command = plan

  assert {
    condition     = module.opnsense.wan_mac_address == "BC:24:11:00:C9:00" && module.opnsense.lan_mac_address == "BC:24:11:00:C9:01"
    error_message = "the rebuilt gateway must carry the MACs the MAC scheme derives from VMID 201"
  }
}

run "attaches_no_seed_unless_one_is_given" {
  command = plan

  assert {
    condition     = var.opnsense_seed_image_path == null
    error_message = "the steady state carries no seed, so an apply after the first boot drops the uploaded file"
  }
}
