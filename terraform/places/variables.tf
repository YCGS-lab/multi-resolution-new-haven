variable "name" {
  type        = string
  description = "Resource name prefix (Lambda function, IAM role, HTTP API, log groups)"
  default     = "ycgs-places"
}

variable "cors_origins" {
  type        = list(string)
  description = "Origins allowed to call the API (the website, e.g. https://d123.cloudfront.net; \"*\" for any)"
}

variable "throttling_rate_limit" {
  type        = number
  description = "Steady-state requests per second (all clients together): bounds the Places bill (see docs/website/search.md)"
  default     = 5
}

variable "throttling_burst_limit" {
  type        = number
  description = "Burst of requests above the rate"
  default     = 10
}

variable "reserved_concurrency" {
  type        = number
  description = "Cap on concurrent Lambda executions"
  default     = 5
}

variable "log_retention_days" {
  type        = number
  description = "Retention of the Lambda and API access logs"
  default     = 30
}
