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
  description = "Cap on concurrent executions per deployment (cost guard); a deployment left out is unreserved. Each instance costs memory x $0.0000133 per GB-s, so the default caps the tiler at ~$17/h with every instance busy (nasa ~$8.5, noaa ~$5.8, ecmwf ~$2.9)"
  default     = { nasa = 60, noaa = 60, ecmwf = 30 }
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

# region guard-variables
variable "guard" {
  type        = bool
  description = "Cost guard: CloudFront traffic alarms, a kill switch and a budget backstop (guard.tf). Needs the default provider in us-east-1"
  default     = true
}

variable "alert_emails" {
  type        = list(string)
  description = "Addresses for cost-guard warnings, kill reports and budget alerts (each confirms an SNS subscription by email)"
  default     = []
}

variable "guard_extra_distribution_ids" {
  type        = list(string)
  description = "Other CloudFront distributions to watch and disable with the tiler's (e.g. the website's)"
  default     = []
}

variable "guard_extra_functions" {
  type        = list(object({ name = string, region = string }))
  description = "Other Lambda functions the kill switch stops with the tiler's (reserved concurrency 0), e.g. the place search's"
  default     = []
}

variable "guard_extra_apis" {
  type        = list(string)
  description = "IDs of HTTP APIs in the default provider's region whose request count is watched (warn / kill alarms), e.g. the place search's"
  default     = []
}

variable "guard_warn_api_requests_per_hour" {
  type        = number
  description = "Warning: requests per hour to guard_extra_apis"
  default     = 500
}

variable "guard_kill_api_requests_per_hour" {
  type        = number
  description = "Kill: requests per hour to guard_extra_apis, sustained for guard_kill_minutes (2000/h of Places requests at $0.20-0.50 per 1000 ~ $0.40-1/h)"
  default     = 2000
}

variable "guard_warn_bytes_per_hour" {
  type        = number
  description = "Warning: bytes downloaded per hour from the guarded distributions (5 GB ~ $0.43/h)"
  default     = 5e9
}

variable "guard_warn_requests_per_hour" {
  type        = number
  description = "Warning: requests per hour to the guarded distributions"
  default     = 50000
}

variable "guard_kill_bytes_per_hour" {
  type        = number
  description = "Kill: bytes downloaded per hour (50 GB ~ $4.25/h), sustained for guard_kill_minutes"
  default     = 50e9
}

variable "guard_kill_minutes" {
  type        = number
  description = "Kill: how long the download rate must stay above guard_kill_bytes_per_hour (multiple of 5)"
  default     = 15
}

variable "guard_budget_usd" {
  type        = number
  description = "Monthly budget backstop (USD): email at 80% spent and forecast 100%, kill at 100% spent; null: no budget"
  default     = 50
}

variable "guard_budget_filters" {
  type        = map(list(string))
  description = "Budget cost filters (dimension -> values). Default: the services the tiler and website use, account-wide; with the Service tag activated for cost allocation, e.g. { TagKeyValue = [\"user:Service$<name>\"] }"
  default     = { Service = ["Amazon CloudFront", "AWS Lambda", "Amazon API Gateway", "Amazon DynamoDB"] }
}
# endregion guard-variables
