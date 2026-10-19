variable "name" {
  type        = string
  description = "Resource name prefix (Lambda functions, ECR repositories, secrets, CloudFront function and cache policy)"
  default     = "ycgs-titiler"
}

variable "image_platform" {
  type        = string
  description = "Docker platform of the Lambda image (linux/arm64 or linux/amd64)"
  default     = "linux/arm64"
  validation {
    condition     = contains(["linux/arm64", "linux/amd64"], var.image_platform)
    error_message = "image_platform must be linux/arm64 or linux/amd64."
  }
}

variable "lambda_memory" {
  type        = map(number)
  description = "Lambda memory (MB) per deployment; CPU scales with memory"
  default     = { nasa = 3008, noaa = 2048, ecmwf = 2048 }
}

variable "reserved_concurrency" {
  type        = map(number)
  description = "Optional cap on concurrent executions per deployment (cost guard); unset = unreserved"
  default     = {}
}

variable "throttling_rate_limit" {
  type        = number
  description = "API Gateway steady-state requests per second, per deployment"
  default     = 100
}

variable "throttling_burst_limit" {
  type        = number
  description = "API Gateway burst, per deployment"
  default     = 200
}

variable "cors_origins" {
  type        = list(string)
  description = "Allowed CORS origins (\"*\" for any)"
  default     = ["*"]
}

variable "price_class" {
  type        = string
  description = "CloudFront price class"
  default     = "PriceClass_100" # NA + EU only; cheapest
}

variable "secret_recovery_days" {
  type        = number
  description = "Secrets Manager recovery window on deletion (0 deletes at once, e.g. for test deployments)"
  default     = 7
}

# region secret-vars
# --------------------------------------------------------------------------
# Secrets: ephemeral (never written to state or plan files). Required on the
# first apply and whenever secrets_version changes; otherwise leave them unset.

variable "secrets_version" {
  type        = number
  description = "Bump to write new secret values (with the variables below set)"
  default     = 1
}

variable "earthdata_username" {
  type        = string
  description = "NASA Earthdata Login username (titiler-cmr)"
  default     = null
  ephemeral   = true
  sensitive   = true
}

variable "earthdata_password" {
  type        = string
  description = "NASA Earthdata Login password (titiler-cmr)"
  default     = null
  ephemeral   = true
  sensitive   = true
}

variable "cds_api_key" {
  type        = string
  description = "Copernicus Climate Data Store API key (ERA5-Land analysis-ready Zarr)"
  default     = null
  ephemeral   = true
  sensitive   = true
}
# endregion secret-vars

variable "origin_shield" {
  type        = bool
  description = "CloudFront Origin Shield in each regional deployment's region (~$0.0075-0.009 per 10,000 requests that reach it)"
  default     = true
}
