# Three regional deployments of the same image, each next to its data:
#   nasa  (us-west-2)   titiler-cmr: NISAR, SMAP, HLS, Black Marble, ASTER GDEM
#                       (Earthdata Cloud, direct S3)
#   noaa  (us-east-1)   GOES-19 ABI imagery and LST (NOAA Open Data), CHIRPS COGs;
#                       also the default origin
#   ecmwf (the aws.ecmwf provider's region)  ERA5-Land (CDS analysis-ready Zarr)
#
# The providers (and their default_tags, e.g. Service / Environment) come from
# the caller; see examples/test.

# region ecr-repos
module "ecr_nasa" {
  source    = "./modules/ecr"
  providers = { aws = aws.nasa }
  name      = "${var.name}-nasa"
}

module "ecr_noaa" {
  source    = "./modules/ecr"
  providers = { aws = aws.noaa }
  name      = "${var.name}-noaa"
}

module "ecr_ecmwf" {
  source    = "./modules/ecr"
  providers = { aws = aws.ecmwf }
  name      = "${var.name}-ecmwf"
}
# endregion ecr-repos

locals {
  repositories = {
    nasa  = module.ecr_nasa.repository_url
    noaa  = module.ecr_noaa.repository_url
    ecmwf = module.ecr_ecmwf.repository_url
  }

  # region image-tag
  # The image tag is a hash of everything that goes into the image.
  # The app lives at the repository root (tiler/); calling this module by Git URL
  # with "//terraform/tiler" downloads the whole repository, so the path resolves.
  app_dir = "${path.module}/../../tiler"
  app_files = sort([
    for f in setunion(fileset(local.app_dir, "src/**"), ["pyproject.toml", "uv.lock", "Dockerfile"]) :
    f if !strcontains(f, "__pycache__")
  ])
  image_tag = substr(sha256(join("\n", [for f in local.app_files : "${f} ${filesha256("${local.app_dir}/${f}")}"])), 0, 16)
  # endregion image-tag

  architecture = var.image_platform == "linux/arm64" ? "arm64" : "x86_64"

  # region common-env
  common_env = {
    YCGS_ORIGIN_VERIFY       = random_password.origin_verify.result
    YCGS_CORS_ORIGINS        = join(",", var.cors_origins)
    TITILER_CMR_CORS_ORIGINS = join(",", var.cors_origins)
  }
  # endregion common-env
}

# region image-build
# Build the image once per content hash and push it to each region's repository
# (needs docker with buildx and the AWS CLI where tofu runs). Lambda needs a
# single-platform manifest, hence no provenance/SBOM attestations.
resource "terraform_data" "image" {
  for_each = local.repositories

  input            = local.image_tag
  triggers_replace = [local.image_tag, each.value, var.image_platform]

  provisioner "local-exec" {
    working_dir = local.app_dir
    interpreter = ["bash", "-c"]
    environment = {
      REPO     = each.value
      TAG      = local.image_tag
      PLATFORM = var.image_platform
    }
    command = <<-EOT
      set -euo pipefail
      registry="$${REPO%%/*}"
      region="$(cut -d. -f4 <<<"$registry")"
      if aws ecr describe-images --region "$region" --repository-name "$${REPO#*/}" --image-ids imageTag="$TAG" >/dev/null 2>&1; then
        echo "$REPO:$TAG already pushed"
        exit 0
      fi
      aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"
      docker buildx build --platform "$PLATFORM" --provenance=false --sbom=false --push -t "$REPO:$TAG" .
    EOT
  }
}
# endregion image-build

# region nasa
module "nasa" {
  source    = "./modules/regional-api"
  providers = { aws = aws.nasa }

  name                   = "${var.name}-nasa"
  image_uri              = "${local.repositories.nasa}:${terraform_data.image["nasa"].output}"
  architecture           = local.architecture
  memory_size            = var.lambda_memory["nasa"]
  reserved_concurrency   = lookup(var.reserved_concurrency, "nasa", null)
  throttling_rate_limit  = var.throttling_rate_limit
  throttling_burst_limit = var.throttling_burst_limit
  secret_arns            = [aws_secretsmanager_secret.earthdata.arn]
  environment = merge(local.common_env, {
    YCGS_FEATURES                          = "cmr"
    TITILER_CMR_EARTHDATA_S3_DIRECT_ACCESS = "TRUE"
    # A new secret version publishes a new Lambda version, which re-reads it.
    YCGS_SECRET_VERSION = aws_secretsmanager_secret_version.earthdata.version_id
  })
}
# endregion nasa

# region noaa
module "noaa" {
  source    = "./modules/regional-api"
  providers = { aws = aws.noaa }

  name                   = "${var.name}-noaa"
  image_uri              = "${local.repositories.noaa}:${terraform_data.image["noaa"].output}"
  architecture           = local.architecture
  memory_size            = var.lambda_memory["noaa"]
  reserved_concurrency   = lookup(var.reserved_concurrency, "noaa", null)
  throttling_rate_limit  = var.throttling_rate_limit
  throttling_burst_limit = var.throttling_burst_limit
  environment            = local.common_env
}
# endregion noaa

# region ecmwf
module "ecmwf" {
  source    = "./modules/regional-api"
  providers = { aws = aws.ecmwf }

  name                   = "${var.name}-ecmwf"
  image_uri              = "${local.repositories.ecmwf}:${terraform_data.image["ecmwf"].output}"
  architecture           = local.architecture
  memory_size            = var.lambda_memory["ecmwf"]
  reserved_concurrency   = lookup(var.reserved_concurrency, "ecmwf", null)
  throttling_rate_limit  = var.throttling_rate_limit
  throttling_burst_limit = var.throttling_burst_limit
  secret_arns            = [aws_secretsmanager_secret.cds.arn]
  environment = merge(local.common_env, {
    YCGS_SECRET_VERSION = aws_secretsmanager_secret_version.cds.version_id
  })
}
# endregion ecmwf
