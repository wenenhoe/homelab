mock_provider "proxmox" {
  mock_resource "proxmox_download_file" {
    defaults = {
      id = "local:import/ubuntu-26.04-server-cloudimg-amd64.qcow2"
    }
  }
}

variables {
  proxmox_endpoint  = "https://pve.example.lan:8006/"
  proxmox_api_token = "tofu@pve!skeleton=secret"
  dns_domain        = "internal.example.com"
  ssh_public_keys   = ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest test"]
}

run "builds_the_template_from_the_pinned_image" {
  command = plan

  assert {
    condition     = module.ubuntu_template.vm_id == 106
    error_message = "the root module must build the template in the 1XX range"
  }
}

run "builds_an_isolated_5xx_block" {
  command = plan

  assert {
    condition     = module.opnsense_5xx.vm_id == 501 && module.ubuntu_5xx.vm_id == 502
    error_message = "the block must be OPNsense 501 and one Ubuntu VM 502"
  }

  assert {
    condition     = module.opnsense_5xx.wan_mac_address == "BC:24:11:01:F5:00" && module.ubuntu_5xx.ip_address == "192.168.50.2"
    error_message = "501 must keep its derived MAC and 502 must sit in 192.168.50.0/24"
  }

  assert {
    condition     = module.opnsense_5xx.wan_mac_address != module.ubuntu_5xx.mac_address
    error_message = "the two VMs must not share a MAC"
  }
}

run "publishes_no_inventory_hosts_for_the_scratch_block" {
  command = plan

  assert {
    condition     = output.ansible_hosts == {}
    error_message = "the scratch block must stay out of the generated inventory"
  }
}
