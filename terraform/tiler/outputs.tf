output "url" {
  description = "Public URL (CloudFront)"
  value       = "https://${aws_cloudfront_distribution.this.domain_name}"
}

output "distribution_id" {
  value = aws_cloudfront_distribution.this.id
}

output "deployments" {
  description = "Regional deployments (API Gateway endpoints reject requests that don't come through CloudFront)"
  value = {
    for k, m in { nasa = module.nasa, noaa = module.noaa, ecmwf = module.ecmwf } : k => {
      region           = m.region
      api_endpoint     = m.api_endpoint
      function_name    = m.function_name
      live_version     = m.live_version
      image            = "${local.repositories[k]}:${local.image_tag}"
    }
  }
}

output "example_urls" {
  description = "One request per dataset preset"
  value = {
    for id, ds in local.catalog.datasets :
    id => "https://${aws_cloudfront_distribution.this.domain_name}/datasets/${id}/${keys(ds.renders)[0]}/WebMercatorQuad/tilejson.json"
  }
}

output "cors_origins" {
  description = "Origins allowed in CORS."
  value       = var.cors_origins
}
