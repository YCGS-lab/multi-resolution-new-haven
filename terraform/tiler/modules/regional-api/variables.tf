variable "name" {
  type        = string
  description = "Resource name prefix, e.g. ycgs-titiler-nasa"
}

variable "image_uri" {
  type        = string
  description = "Container image (repository:tag) in this region's ECR repository"
}

variable "architecture" {
  type        = string
  description = "Lambda architecture, matching the image platform"
  default     = "arm64"
  validation {
    condition     = contains(["arm64", "x86_64"], var.architecture)
    error_message = "architecture must be arm64 or x86_64."
  }
}

variable "memory_size" {
  type        = number
  description = "Lambda memory (MB); CPU scales with it"
  default     = 3008
}

variable "timeout" {
  type        = number
  description = "Lambda timeout (s); API Gateway HTTP APIs stop waiting after 30 s"
  default     = 30
}

variable "reserved_concurrency" {
  type        = number
  description = "Cap on concurrent executions (cost guard); null = unreserved"
  default     = null
}

variable "snap_start" {
  type        = bool
  description = "Lambda SnapStart on published versions"
  default     = true
}

variable "keep_versions" {
  type        = number
  description = "Published versions to keep (each SnapStart version is billed for its cached snapshot)"
  default     = 3
}

variable "environment" {
  type        = map(string)
  description = "Extra Lambda environment variables"
  default     = {}
}

variable "secret_arns" {
  type        = list(string)
  description = "Secrets Manager secrets the function reads at init (JSON key/values become env vars)"
  default     = []
}

variable "throttling_rate_limit" {
  type        = number
  description = "API Gateway steady-state requests per second"
  default     = 100
}

variable "throttling_burst_limit" {
  type        = number
  description = "API Gateway burst"
  default     = 200
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "lookup_cache" {
  type        = bool
  description = "Persistent cache of slow lookups (CMR granule searches, GOES listings): a DynamoDB table and a weekly prune job"
  default     = false
}

variable "lookup_prune_schedule" {
  type        = string
  description = "EventBridge Scheduler expression of the lookup cache's prune job (UTC)"
  default     = "cron(0 7 ? * MON *)"
}
