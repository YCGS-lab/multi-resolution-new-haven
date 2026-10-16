# Complete, short-lived deployment of the website and the tiler together
# (../..), created and destroyed by scripts/aws-tests/complete.sh. Every
# resource is named ycgs-test-all-<run_id>... and tagged ycgs:purpose=test
# (the tiler through the providers' default_tags, the website through
# extra_tags), so scripts/aws-tests/sweep.sh can prove nothing is left.
#
# Needs docker (buildx) and the AWS CLI where tofu runs (tiler image).
# Secrets are ephemeral: export TF_VAR_earthdata_token (or
# TF_VAR_earthdata_username and TF_VAR_earthdata_password) and TF_VAR_cds_api_key. They are written on the
# first apply only; to write them again (e.g. after an apply without them),
# set -var secrets_version=<n+1> with them exported.

terraform {
  required_version = ">= 1.11"
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

variable "ecmwf_region" {
  description = "Region of the ERA5-Land deployment (eu-south-1 needs an opt-in)"
  type        = string
  default     = "eu-central-1"
}

variable "secrets_version" {
  description = "Bump to write the tiler secrets again (with the TF_VAR_ secrets exported)"
  type        = number
  default     = 1
}

variable "earthdata_username" {
  type      = string
  default   = null
  ephemeral = true
  sensitive = true
}

variable "earthdata_password" {
  type      = string
  default   = null
  ephemeral = true
  sensitive = true
}

variable "earthdata_token" {
  type      = string
  default   = null
  ephemeral = true
  sensitive = true
}

variable "cds_api_key" {
  type      = string
  default   = null
  ephemeral = true
  sensitive = true
}

# region providers
locals {
  name = "ycgs-test-all-${var.run_id}"
  test_tags = {
    "ycgs:purpose"      = "test"
    "ycgs:test-run"     = var.run_id
    "ycgs:delete-after" = var.delete_after
    "ycgs:created-by"   = "multi-resolution-new-haven/scripts/aws-tests/complete.sh"
  }
  tiler_tags = merge(local.test_tags, { Service = "${local.name}-tiler", Environment = "Dev" })
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = local.tiler_tags
  }
}

provider "aws" {
  alias  = "nasa"
  region = "us-west-2"
  default_tags {
    tags = local.tiler_tags
  }
}

provider "aws" {
  alias  = "noaa"
  region = "us-east-1"
  default_tags {
    tags = local.tiler_tags
  }
}

provider "aws" {
  alias  = "ecmwf"
  region = var.ecmwf_region
  default_tags {
    tags = local.tiler_tags
  }
}
# endregion providers

module "complete" {
  source = "../.."
  providers = {
    aws       = aws
    aws.nasa  = aws.nasa
    aws.noaa  = aws.noaa
    aws.ecmwf = aws.ecmwf
  }

  name        = local.name
  environment = "Dev"
  extra_tags  = local.test_tags
  # The site served locally (`just serve`) may call this tiler too.
  extra_cors_origins = ["http://localhost:8000"]

  # Cost guards for a test: low API Gateway limits, secrets deleted at once.
  tiler_throttling_rate_limit  = 20
  tiler_throttling_burst_limit = 40
  secret_recovery_days         = 0

  secrets_version    = var.secrets_version
  earthdata_username = var.earthdata_username
  earthdata_password = var.earthdata_password
  earthdata_token    = var.earthdata_token
  cds_api_key        = var.cds_api_key
}

output "url" {
  value = module.complete.url
}

output "tiler_url" {
  value = module.complete.tiler_url
}

output "env" {
  value = module.complete.env
}

output "bucket" {
  value = module.complete.bucket
}

output "tiler_deployments" {
  value = module.complete.tiler_deployments
}

output "aws_config" {
  value = module.complete.aws_config
}

output "deploy_commands" {
  value = module.complete.deploy_commands
}

output "deploy_access_key_id" {
  value = module.complete.deploy_access_key_id
}

output "deploy_secret_access_key" {
  value     = module.complete.deploy_secret_access_key
  sensitive = true
}
