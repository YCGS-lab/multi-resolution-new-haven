# The whole thing: the website (../aws: S3 + CloudFront + deploy user/role)
# and the tiler it reads cloud-only datasets from (../tiler: three regional
# Lambda + HTTP API deployments behind CloudFront), wired together:
#
#   - the website's env.json is written by the site module with
#     services.tiler = the tiler's URL (and the repository's other settings
#     from website/env.json), so the cloud-only datasets work as deployed;
#   - the tiler only allows the website's origin (plus extra_cors_origins,
#     e.g. a local copy of the site) in CORS.
#
# The tiler's providers (aws, aws.nasa, aws.noaa, aws.ecmwf) come from the
# caller, whose default_tags tag its resources; the site module configures
# its own provider from site_region and tags with Service / Environment /
# extra_tags. See examples/test.

terraform {
  # Ephemeral variables and write-only attributes (tiler secrets).
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source                = "hashicorp/aws"
      version               = "~> 6.0"
      configuration_aliases = [aws.nasa, aws.noaa, aws.ecmwf]
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

# region wiring
locals {
  # The site's origin (scheme and host), as browsers send it in `Origin`.
  site_origin = trimsuffix(module.site.url, "/")

  # website/env.json from the repository, with the tiler filled in.
  repo_env = jsondecode(file("${path.module}/../../website/env.json"))
  site_env = merge(local.repo_env, {
    services = merge(try(local.repo_env.services, {}), { tiler = module.tiler.url })
  })
}
# endregion wiring

module "site" {
  source = "../aws"

  name          = var.name
  environment   = var.environment
  region        = var.site_region
  price_class   = var.price_class
  domain_name   = var.domain_name
  attach_domain = var.attach_domain
  extra_tags    = var.extra_tags

  env = local.site_env
}

module "tiler" {
  source = "../tiler"
  providers = {
    aws       = aws
    aws.nasa  = aws.nasa
    aws.noaa  = aws.noaa
    aws.ecmwf = aws.ecmwf
  }

  name         = "${var.name}-tiler"
  price_class  = var.price_class
  cors_origins = distinct(concat([local.site_origin], var.extra_cors_origins))

  lambda_memory          = var.tiler_lambda_memory
  reserved_concurrency   = var.tiler_reserved_concurrency
  throttling_rate_limit  = var.tiler_throttling_rate_limit
  throttling_burst_limit = var.tiler_throttling_burst_limit
  image_platform         = var.tiler_image_platform

  secrets_version      = var.secrets_version
  secret_recovery_days = var.secret_recovery_days
  earthdata_username   = var.earthdata_username
  earthdata_password   = var.earthdata_password
  earthdata_token      = var.earthdata_token
  cds_api_key          = var.cds_api_key
}
