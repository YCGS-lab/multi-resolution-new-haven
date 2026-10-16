# Complete, short-lived deployment of the tiler module (../..): three regional
# Lambda + HTTP API deployments behind one CloudFront distribution. Created
# and destroyed by scripts/aws-tests/tiler.sh; every resource is named
# ycgs-test-tiler-<run_id>... and (through the providers' default_tags) tagged
# ycgs:purpose=test, so scripts/aws-tests/sweep.sh can prove nothing is left.
#
# This is also the reference for a persistent deployment (ycgs-aws-infra
# stacks/titiler): the same module call with a remote backend, Environment =
# Prod and no test tags.
#
# Needs docker (buildx) and the AWS CLI where tofu runs (image build and push).
# Secrets are ephemeral: export TF_VAR_earthdata_token (or
# TF_VAR_earthdata_username and TF_VAR_earthdata_password) and TF_VAR_cds_api_key.

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

# region secret-vars
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
# endregion secret-vars

# region providers
locals {
  name = "ycgs-test-tiler-${var.run_id}"
  tags = {
    Service             = local.name
    Environment         = "Dev"
    "ycgs:purpose"      = "test"
    "ycgs:test-run"     = var.run_id
    "ycgs:delete-after" = var.delete_after
    "ycgs:created-by"   = "multi-resolution-new-haven/scripts/aws-tests/tiler.sh"
  }
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = local.tags
  }
}

provider "aws" {
  alias  = "nasa"
  region = "us-west-2"
  default_tags {
    tags = local.tags
  }
}

provider "aws" {
  alias  = "noaa"
  region = "us-east-1"
  default_tags {
    tags = local.tags
  }
}

provider "aws" {
  alias  = "ecmwf"
  region = var.ecmwf_region
  default_tags {
    tags = local.tags
  }
}
# endregion providers

module "tiler" {
  source = "../.."
  providers = {
    aws       = aws
    aws.nasa  = aws.nasa
    aws.noaa  = aws.noaa
    aws.ecmwf = aws.ecmwf
  }

  name = local.name
  # Cost guards for a test: low API Gateway limits, secrets deleted at once.
  throttling_rate_limit  = 20
  throttling_burst_limit = 40
  secret_recovery_days   = 0

  earthdata_username = var.earthdata_username
  earthdata_password = var.earthdata_password
  earthdata_token    = var.earthdata_token
  cds_api_key        = var.cds_api_key
}

output "url" {
  value = module.tiler.url
}

output "deployments" {
  value = module.tiler.deployments
}

output "example_urls" {
  value = module.tiler.example_urls
}
