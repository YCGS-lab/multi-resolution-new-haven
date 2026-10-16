output "api_endpoint" {
  description = "API Gateway endpoint (https://...); requests must come through CloudFront"
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "api_domain" {
  value = replace(aws_apigatewayv2_api.this.api_endpoint, "https://", "")
}

output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "live_version" {
  value = aws_lambda_alias.live.function_version
}

output "region" {
  value = data.aws_region.current.region
}
