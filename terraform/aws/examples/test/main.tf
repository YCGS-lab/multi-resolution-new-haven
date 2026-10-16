# Short-lived test deployment of the website module (../..), created and
# destroyed by scripts/aws-tests/site.sh. Every resource is named
# ycgs-test-site-<run_id>... and tagged ycgs:purpose=test, so
# scripts/aws-tests/sweep.sh can prove nothing is left behind.
#
# State is local (one file per run under .aws-tests/, see site.sh); persistent
# deployments go through the ycgs-aws-infra repository instead.

terraform {
  required_version = ">= 1.6"
  backend "local" {}
}

variable "run_id" {
  description = "Test run id (lowercase letters, digits and dashes)"
  type        = string
}

variable "delete_after" {
  description = "ISO date after which anything left from this run may be deleted"
  type        = string
}

module "site" {
  source = "../.."

  name        = "ycgs-test-site-${var.run_id}"
  environment = "Dev"
  region      = "us-east-1"
  price_class = "PriceClass_100"

  extra_tags = {
    "ycgs:purpose"      = "test"
    "ycgs:test-run"     = var.run_id
    "ycgs:delete-after" = var.delete_after
    "ycgs:created-by"   = "multi-resolution-new-haven/scripts/aws-tests/site.sh"
  }
}

output "url" {
  value = module.site.url
}

output "bucket" {
  value = module.site.bucket
}

output "distribution_id" {
  value = module.site.distribution_id
}

output "aws_config" {
  value = module.site.aws_config
}

output "deploy_commands" {
  value = module.site.deploy_commands
}

output "deploy_access_key_id" {
  value = module.site.deploy_access_key_id
}

output "deploy_secret_access_key" {
  value     = module.site.deploy_secret_access_key
  sensitive = true
}
