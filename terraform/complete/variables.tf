variable "name" {
  description = "Name prefix: the website's resources are named after it, the tiler's after \"<name>-tiler\"."
  type        = string
  default     = "multi-resolution-new-haven"
}

variable "environment" {
  description = "Environment tag of the website's resources (Dev, Stage or Prod); the tiler's come from the caller's provider default_tags."
  type        = string
  default     = "Prod"
}

variable "site_region" {
  description = "Region of the website's bucket and IAM resources (CloudFront is global)."
  type        = string
  default     = "us-east-1"
}

variable "price_class" {
  description = "CloudFront price class of both distributions."
  type        = string
  default     = "PriceClass_100"
}

variable "domain_name" {
  description = "Custom hostname for the website (see the site module)."
  type        = string
  default     = null
}

variable "attach_domain" {
  description = "Serve the website at domain_name once its certificate is issued (see the site module)."
  type        = bool
  default     = false
}

variable "extra_tags" {
  description = "Tags added to the website's resources (the tiler's come from the caller's provider default_tags)."
  type        = map(string)
  default     = {}
}

variable "extra_cors_origins" {
  description = "Origins allowed to call the tiler besides the website, e.g. a local copy of the site for testing."
  type        = list(string)
  default     = []
}

variable "tiler_lambda_memory" {
  description = "Tiler Lambda memory (MB) per regional deployment."
  type        = map(number)
  default     = { nasa = 3008, noaa = 2048, ecmwf = 2048 }
}

variable "tiler_reserved_concurrency" {
  description = "Optional cap on concurrent tiler executions per deployment (cost guard)."
  type        = map(number)
  default     = {}
}

variable "tiler_throttling_rate_limit" {
  description = "Tiler API Gateway steady-state requests per second, per deployment."
  type        = number
  default     = 100
}

variable "tiler_throttling_burst_limit" {
  description = "Tiler API Gateway burst, per deployment."
  type        = number
  default     = 200
}

variable "tiler_image_platform" {
  description = "Docker platform of the tiler's Lambda image (linux/arm64 or linux/amd64)."
  type        = string
  default     = "linux/arm64"
}

variable "secrets_version" {
  description = "Bump to write new tiler secret values (with the variables below set)."
  type        = number
  default     = 1
}

variable "secret_recovery_days" {
  description = "Secrets Manager recovery window on deletion (0 deletes at once, e.g. for test deployments)."
  type        = number
  default     = 7
}

variable "earthdata_username" {
  description = "NASA Earthdata Login username (tiler, titiler-cmr)."
  type        = string
  default     = null
  ephemeral   = true
  sensitive   = true
}

variable "earthdata_password" {
  description = "NASA Earthdata Login password (tiler, titiler-cmr)."
  type        = string
  default     = null
  ephemeral   = true
  sensitive   = true
}

variable "cds_api_key" {
  description = "Copernicus CDS API key (tiler, ERA5-Land ARCO Zarr)."
  type        = string
  default     = null
  ephemeral   = true
  sensitive   = true
}
