provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project = var.project_name
      Environment = var.environment
      ManagedBy = "terraform"
      DataRegion = "UK"
    }
  }
}

locals { name_prefix = "${var.project_name}-${var.environment}" }

output "name_prefix" { value = local.name_prefix }
output "region" { value = var.aws_region }

