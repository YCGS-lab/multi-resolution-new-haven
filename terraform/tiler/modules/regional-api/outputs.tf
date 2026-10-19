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

output "lookup_table" {
  description = "DynamoDB table of the lookup cache (null without it)"
  value       = var.lookup_cache ? aws_dynamodb_table.lookups[0].name : null
}

output "prune_function_name" {
  description = "Lookup cache prune job (null without the cache)"
  value       = var.lookup_cache ? aws_lambda_function.prune[0].function_name : null
}
