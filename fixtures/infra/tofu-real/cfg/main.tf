terraform {
  required_providers {
    random = { source = "hashicorp/random", version = "3.6.3" }
    null   = { source = "hashicorp/null", version = "3.2.3" }
  }
}
variable "db_password" {
  type      = string
  sensitive = true
  default   = "PLANTED-SECRET-hunter2"
}
variable "region" {
  type    = string
  default = "europe-west1"
}
resource "random_id" "suffix" {
  byte_length = 4
  keepers     = { region = var.region }
}
resource "random_password" "db" {
  length = 16
}
resource "terraform_data" "db" {
  input = { name = "main-${random_id.suffix.hex}", password = var.db_password }
}
module "svc" {
  source   = "./modules/svc"
  for_each = toset(["api", "worker"])
  name     = each.key
  db_ref   = terraform_data.db.output
  token    = random_password.db.result
}
resource "null_resource" "lit" {
  count    = 2
  triggers = { MODE = "batch", INDEX = tostring(count.index) }
}
output "pw" {
  value     = random_password.db.result
  sensitive = true
}
