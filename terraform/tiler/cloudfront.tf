# One CloudFront distribution in front of the three regional APIs. Each
# dataset preset (/datasets/{id}/*) goes to the deployment named in
# app/src/ycgs_titiler/datasets.yaml; /cmr/* goes to the NASA deployment;
# everything else to the NOAA (us-east-1) deployment, which serves the catalog.

# region routes
locals {
  catalog = yamldecode(file("${local.app_dir}/src/ycgs_titiler/datasets.yaml"))

  origins = {
    nasa  = module.nasa.api_domain
    noaa  = module.noaa.api_domain
    ecmwf = module.ecmwf.api_domain
  }

  routes = concat(
    [{ path = "/cmr/*", origin = "nasa" }],
    [for id, ds in local.catalog.datasets : { path = "/datasets/${id}/*", origin = ds.deployment }],
  )

  cors_any = contains(var.cors_origins, "*")
}
# endregion routes

# region viewer-host
# Pass the viewer's Host on (API Gateway needs its own Host header), so URLs
# the app builds (TileJSON) point at CloudFront.
resource "aws_cloudfront_function" "viewer_host" {
  name    = "${var.name}-viewer-host"
  runtime = "cloudfront-js-2.0"
  comment = "Copy Host to X-YCGS-Host"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      request.headers['x-ycgs-host'] = { value: request.headers.host.value };
      return request;
    }
  EOT
}
# endregion viewer-host

# region cache-policy
# Every query parameter changes the image (time, render, rescale, ...); TTLs
# follow the origin's Cache-Control (long for pinned times, 60 s for "latest").
resource "aws_cloudfront_cache_policy" "titiler" {
  name        = "${var.name}-query-strings"
  min_ttl     = 0
  default_ttl = 3600
  max_ttl     = 31536000

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      # CORS responses vary by Origin unless any origin is allowed
      header_behavior = local.cors_any ? "none" : "whitelist"
      dynamic "headers" {
        for_each = local.cors_any ? [] : [1]
        content {
          items = ["Origin"]
        }
      }
    }
    query_strings_config {
      query_string_behavior = "all"
    }
  }
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}
# endregion cache-policy

resource "aws_cloudfront_distribution" "this" {
  #checkov:skip=CKV_AWS_305:API, not a website; / returns the landing JSON
  #checkov:skip=CKV_AWS_68:No WAF; API Gateway throttling and Lambda concurrency limits bound cost
  #checkov:skip=CKV_AWS_86:Access logging not enabled (API Gateway access logs per region)
  #checkov:skip=CKV_AWS_174:Default CloudFront certificate (no custom domain yet)
  #checkov:skip=CKV_AWS_310:No origin failover; each dataset has one home region
  #checkov:skip=CKV_AWS_374:No geo restriction
  #checkov:skip=CKV2_AWS_32:Response headers come from titiler (CORS, Cache-Control)
  #checkov:skip=CKV2_AWS_42:Default CloudFront certificate (no custom domain yet)
  #checkov:skip=CKV2_AWS_47:No WAF
  enabled         = true
  comment         = var.name # YCGS titiler (multi-region)
  is_ipv6_enabled = true
  http_version    = "http2and3"
  price_class     = var.price_class

  # region origins
  dynamic "origin" {
    for_each = local.origins
    content {
      origin_id   = origin.key
      domain_name = origin.value

      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "https-only"
        origin_ssl_protocols   = ["TLSv1.2"]
        origin_read_timeout    = 30
      }

      custom_header {
        name  = "X-Origin-Verify"
        value = random_password.origin_verify.result
      }
    }
  }
  # endregion origins

  # region behaviors
  default_cache_behavior {
    target_origin_id         = "noaa"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = aws_cloudfront_cache_policy.titiler.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.viewer_host.arn
    }
  }

  dynamic "ordered_cache_behavior" {
    for_each = local.routes
    content {
      path_pattern             = ordered_cache_behavior.value.path
      target_origin_id         = ordered_cache_behavior.value.origin
      viewer_protocol_policy   = "redirect-to-https"
      allowed_methods          = ["GET", "HEAD", "OPTIONS"]
      cached_methods           = ["GET", "HEAD"]
      compress                 = true
      cache_policy_id          = aws_cloudfront_cache_policy.titiler.id
      origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id

      function_association {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.viewer_host.arn
      }
    }
  }
  # endregion behaviors

  # region error-caching
  # Don't cache errors from the origin (e.g. a cold, timed-out tile).
  dynamic "custom_error_response" {
    for_each = [500, 502, 503, 504]
    content {
      error_code            = custom_error_response.value
      error_caching_min_ttl = 0
    }
  }
  # endregion error-caching

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
