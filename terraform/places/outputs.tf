output "url" {
  description = "The API's base URL (no trailing slash): /suggest, /place, /geocode"
  value       = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")
}

output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "api_id" {
  value = aws_apigatewayv2_api.this.id
}

output "region" {
  value = data.aws_region.current.region
}
