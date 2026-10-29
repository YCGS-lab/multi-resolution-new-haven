# Place search for the website (its header search box): a small Lambda
# (handler.py) that calls Amazon Location Places (v2) in this provider's
# region, behind an API Gateway HTTP API that allows the website's origin in
# CORS and caps the request rate. The Lambda's role may call the three Places
# operations it uses and nothing else; no API key reaches the browser.
#
# Cost: billed per Places request (Suggest at the "Label" price, GetPlace and
# Geocode at "Core"); the stage throttle bounds it. See docs/website/search.md.

data "aws_region" "current" {}

# region iam
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = var.name
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }

  statement {
    sid       = "Places"
    actions   = ["geo-places:Suggest", "geo-places:GetPlace", "geo-places:Geocode"]
    resources = ["arn:aws:geo-places:${data.aws_region.current.region}::provider/default"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "places"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}
# endregion iam

# region lambda
data "archive_file" "handler" {
  type        = "zip"
  source_file = "${path.module}/handler.py"
  output_path = "${path.module}/.build/places.zip"
}

resource "aws_cloudwatch_log_group" "lambda" {
  #checkov:skip=CKV_AWS_158:AWS-managed encryption is sufficient for request logs
  #checkov:skip=CKV_AWS_338:Short retention (log_retention_days) keeps costs down
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "this" {
  #checkov:skip=CKV_AWS_117:Calls the Places API only; no VPC needed
  #checkov:skip=CKV_AWS_116:Synchronous API; a dead-letter queue does not apply
  #checkov:skip=CKV_AWS_272:Code is in this module; no code signing
  #checkov:skip=CKV_AWS_173:Environment holds no credentials
  #checkov:skip=CKV_AWS_50:No tracing needed
  function_name    = var.name
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.handler.output_path
  source_code_hash = data.archive_file.handler.output_base64sha256
  memory_size      = 256
  timeout          = 10

  reserved_concurrent_executions = var.reserved_concurrency

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.lambda.name
  }

  depends_on = [aws_iam_role_policy.lambda]
}
# endregion lambda

# region http-api
resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"

  # Simple GETs; API Gateway answers preflights and adds the headers.
  cors_configuration {
    allow_origins = var.cors_origins
    allow_methods = ["GET"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.this.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 10000
}

resource "aws_apigatewayv2_route" "get" {
  #checkov:skip=CKV_AWS_309:Public search API for the website; throttled, CORS limited to the website
  for_each  = toset(["/suggest", "/place", "/geocode"])
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "GET ${each.value}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_cloudwatch_log_group" "api" {
  #checkov:skip=CKV_AWS_158:AWS-managed encryption is sufficient for request logs
  #checkov:skip=CKV_AWS_338:Short retention (log_retention_days) keeps costs down
  name              = "/aws/apigateway/${var.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.throttling_rate_limit
    throttling_burst_limit = var.throttling_burst_limit
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId          = "$context.requestId"
      ip                 = "$context.identity.sourceIp"
      requestTime        = "$context.requestTime"
      path               = "$context.path"
      status             = "$context.status"
      integrationLatency = "$context.integrationLatency"
      integrationError   = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
# endregion http-api
