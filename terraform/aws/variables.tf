variable "name" {
  description = "Prefix for resource names (S3 bucket, IAM user and role), and the Service tag."
  type        = string
  default     = "multi-resolution-new-haven"
}

variable "environment" {
  description = "Environment tag (Dev, Stage or Prod)."
  type        = string
  default     = "Prod"

  validation {
    condition     = contains(["Dev", "Stage", "Prod"], var.environment)
    error_message = "environment must be one of Dev, Stage, Prod."
  }
}

variable "region" {
  description = "Region of the S3 bucket and IAM resources (CloudFront is global)."
  type        = string
  default     = "us-east-1"
}

variable "price_class" {
  description = "CloudFront price class. PriceClass_100 serves from North America and Europe only, the cheapest."
  type        = string
  default     = "PriceClass_100"
}

variable "domain_name" {
  description = "Custom hostname for the site (e.g. newhaven.geospatial.yale.edu). Setting it requests an ACM certificate; see attach_domain."
  type        = string
  default     = null
}

variable "attach_domain" {
  description = "Serve the site at domain_name. Set to true only once the ACM certificate is issued (its validation CNAME is in DNS)."
  type        = bool
  default     = false

  validation {
    condition     = !var.attach_domain || var.domain_name != null
    error_message = "attach_domain needs domain_name."
  }
}
