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
}

run "builds_the_template_from_the_pinned_image" {
  command = plan

  assert {
    condition     = module.ubuntu_template.vm_id == 106
    error_message = "the root module must build the template in the 1XX range"
  }
}
