variable "name" { type = string }
variable "db_ref" {}
variable "token" {
  type      = string
  sensitive = true
}
resource "terraform_data" "unit" {
  input = {
    service = var.name
    env = [
      { name = "DATABASE_URL", value = var.db_ref }, 
      { name = "API_TOKEN", value = var.token },
      { name = "LOG_LEVEL", value = "info" },
    ]
  }
}
