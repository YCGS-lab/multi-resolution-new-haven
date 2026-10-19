terraform {
  # Ephemeral variables and write-only attributes keep secret values out of state.
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
      # aws (default): CloudFront and other global resources (us-east-1).
      # aws.nasa:  next to NASA Earthdata Cloud (us-west-2; direct S3 access to DAAC buckets only works in-region).
      # aws.noaa:  next to NOAA Open Data (us-east-1).
      # aws.ecmwf: nearest to ECMWF's data centre (eu-south-1 if the account opted in, else eu-central-1).
      configuration_aliases = [aws.nasa, aws.noaa, aws.ecmwf]
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}
