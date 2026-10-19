# One regional titiler deployment: Lambda (container image, SnapStart, "live"
# alias) and an API Gateway HTTP API in front of it.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

data "aws_region" "current" {}

# region iam
# --------------------------------------------------------------------------
# IAM

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
  name               = "${var.name}-${data.aws_region.current.region}"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }

  dynamic "statement" {
    for_each = length(var.secret_arns) > 0 ? [1] : []
    content {
      sid       = "ReadSecrets"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = var.secret_arns
    }
  }

  dynamic "statement" {
    for_each = var.lookup_cache ? [1] : []
    content {
      sid       = "LookupCache"
      actions   = ["dynamodb:GetItem", "dynamodb:PutItem"]
      resources = [aws_dynamodb_table.lookups[0].arn]
    }
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "titiler"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}
# endregion iam

# --------------------------------------------------------------------------
# Lambda

resource "aws_cloudwatch_log_group" "lambda" {
  #checkov:skip=CKV_AWS_158:AWS-managed encryption is sufficient for request logs
  #checkov:skip=CKV_AWS_338:Short retention (log_retention_days) keeps costs down
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
}

# region gdal-env
locals {
  # titiler / titiler-cmr recommended GDAL settings for Lambda
  gdal_env = {
    GDAL_CACHEMAX                      = "200"
    GDAL_DISABLE_READDIR_ON_OPEN       = "EMPTY_DIR"
    GDAL_INGESTED_BYTES_AT_OPEN        = "32768"
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES = "YES"
    GDAL_HTTP_MULTIPLEX                = "YES"
    GDAL_HTTP_VERSION                  = "2"
    VSI_CACHE                          = "TRUE"
    VSI_CACHE_SIZE                     = "5000000"
    PYTHONWARNINGS                     = "ignore"
    AWS_EC2_METADATA_DISABLED          = "true"
  }
}
# endregion gdal-env

# region lambda
resource "aws_lambda_function" "this" {
  #checkov:skip=CKV_AWS_117:Reads public/Earthdata endpoints over the internet; a VPC would only add a NAT gateway
  #checkov:skip=CKV_AWS_116:Synchronous API; a dead-letter queue does not apply
  #checkov:skip=CKV_AWS_272:Images are built and pushed by this stack; no code signing
  #checkov:skip=CKV_AWS_173:Environment holds no credentials (only the CloudFront origin token); credentials come from Secrets Manager at init
  function_name = var.name
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = [var.architecture]
  memory_size   = var.memory_size
  timeout       = var.timeout
  publish       = true # SnapStart only applies to published versions

  reserved_concurrent_executions = coalesce(var.reserved_concurrency, -1)

  environment {
    variables = merge(local.gdal_env, var.environment, {
      YCGS_SECRET_ARNS  = join(",", var.secret_arns)
      YCGS_LOOKUP_TABLE = var.lookup_cache ? aws_dynamodb_table.lookups[0].name : ""
    })
  }

  dynamic "snap_start" {
    for_each = var.snap_start ? [1] : []
    content {
      apply_on = "PublishedVersions"
    }
  }

  logging_config {
    log_format            = "JSON"
    log_group             = aws_cloudwatch_log_group.lambda.name
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  tracing_config {
    mode = "PassThrough"
  }

  depends_on = [aws_iam_role_policy.lambda]
}
# endregion lambda

# region alias
# API Gateway invokes the alias, i.e. the latest published (snapshotted) version.
resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.this.function_name
  function_version = terraform_data.version_active.output
}

# A published SnapStart version stays Pending for minutes while its snapshot
# is taken, and invoking it fails until then: wait before the alias moves.
resource "terraform_data" "version_active" {
  input            = aws_lambda_function.this.version
  triggers_replace = [aws_lambda_function.this.version]

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    environment = {
      FN      = aws_lambda_function.this.function_name
      REGION  = data.aws_region.current.region
      VERSION = aws_lambda_function.this.version
    }
    command = <<-EOT
      set -euo pipefail
      for i in 1 2 3 4; do # the CLI waiter gives up after 5 min
        aws lambda wait published-version-active --region "$REGION" --function-name "$FN" --qualifier "$VERSION" && exit 0
      done
      exit 1
    EOT
  }
}
# endregion alias

# region prune-versions
# Delete old published versions (their SnapStart snapshots are billed while they exist).
resource "terraform_data" "prune_versions" {
  triggers_replace = [aws_lambda_alias.live.function_version]

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    environment = {
      FN     = aws_lambda_function.this.function_name
      REGION = data.aws_region.current.region
      KEEP   = var.keep_versions
      LIVE   = aws_lambda_alias.live.function_version
    }
    command = <<-EOT
      set -euo pipefail
      aws lambda list-versions-by-function --region "$REGION" --function-name "$FN" \
        --query 'Versions[?Version!=`$LATEST`].Version' --output text \
        | tr '\t' '\n' | sort -n | awk -v keep="$KEEP" '{v[NR]=$0} END {for (i = 1; i <= NR - keep; i++) print v[i]}' \
        | while read -r v; do
            [ -n "$v" ] && [ "$v" != "$LIVE" ] && aws lambda delete-function --region "$REGION" --function-name "$FN" --qualifier "$v"
          done
    EOT
  }
}
# endregion prune-versions

# region http-api
# --------------------------------------------------------------------------
# API Gateway HTTP API

resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.live.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "default" {
  #checkov:skip=CKV_AWS_309:Public tile API; the app rejects requests without CloudFront's X-Origin-Verify header
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "$default"
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
      method             = "$context.httpMethod"
      path               = "$context.path"
      status             = "$context.status"
      responseLength     = "$context.responseLength"
      integrationLatency = "$context.integrationLatency"
      integrationError   = "$context.integrationErrorMessage"
    })
  }
}
# endregion http-api

# region permission
resource "aws_lambda_permission" "api" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  qualifier     = aws_lambda_alias.live.name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
# endregion permission

# region lookup-cache
# --------------------------------------------------------------------------
# Lookup cache (ycgs_titiler.lookups): CMR granule searches and GOES listings,
# shared by every execution environment; pruned weekly by the same image.

resource "aws_dynamodb_table" "lookups" {
  #checkov:skip=CKV_AWS_28:A cache: every item can be recomputed, so no point-in-time recovery
  #checkov:skip=CKV_AWS_119:Public catalog metadata; AWS-owned encryption is sufficient
  count        = var.lookup_cache ? 1 : 0
  name         = "${var.name}-lookups"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires"
    enabled        = true
  }
}

resource "aws_iam_role" "prune" {
  count              = var.lookup_cache ? 1 : 0
  name               = "${var.name}-prune-${data.aws_region.current.region}"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "prune" {
  count = var.lookup_cache ? 1 : 0
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.prune[0].arn}:*"]
  }
  statement {
    sid       = "LookupCache"
    actions   = ["dynamodb:Scan", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.lookups[0].arn]
  }
}

resource "aws_iam_role_policy" "prune" {
  count  = var.lookup_cache ? 1 : 0
  name   = "prune"
  role   = aws_iam_role.prune[0].id
  policy = data.aws_iam_policy_document.prune[0].json
}

resource "aws_cloudwatch_log_group" "prune" {
  #checkov:skip=CKV_AWS_158:AWS-managed encryption is sufficient for job logs
  #checkov:skip=CKV_AWS_338:Short retention (log_retention_days) keeps costs down
  count             = var.lookup_cache ? 1 : 0
  name              = "/aws/lambda/${var.name}-prune"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "prune" {
  #checkov:skip=CKV_AWS_117:Reads public endpoints (CMR, NOAA Open Data) over the internet; a VPC would only add a NAT gateway
  #checkov:skip=CKV_AWS_116:Scheduled job; the next week's run retries
  #checkov:skip=CKV_AWS_272:Images are built and pushed by this stack; no code signing
  #checkov:skip=CKV_AWS_173:Environment holds no credentials
  #checkov:skip=CKV_AWS_115:Runs once a week; no concurrency limit needed
  count         = var.lookup_cache ? 1 : 0
  function_name = "${var.name}-prune"
  role          = aws_iam_role.prune[0].arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = [var.architecture]
  memory_size   = 1024
  timeout       = 900

  image_config {
    command = ["ycgs_titiler.prune.handler"]
  }

  environment {
    variables = merge(local.gdal_env, var.environment, {
      YCGS_LOOKUP_TABLE = aws_dynamodb_table.lookups[0].name
    })
  }

  logging_config {
    log_format            = "JSON"
    log_group             = aws_cloudwatch_log_group.prune[0].name
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  tracing_config {
    mode = "PassThrough"
  }

  depends_on = [aws_iam_role_policy.prune]
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  count              = var.lookup_cache ? 1 : 0
  name               = "${var.name}-prune-schedule-${data.aws_region.current.region}"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  count = var.lookup_cache ? 1 : 0
  name  = "invoke-prune"
  role  = aws_iam_role.scheduler[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.prune[0].arn
    }]
  })
}

resource "aws_scheduler_schedule" "prune" {
  count                        = var.lookup_cache ? 1 : 0
  name                         = "${var.name}-prune"
  schedule_expression          = var.lookup_prune_schedule
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.prune[0].arn
    role_arn = aws_iam_role.scheduler[0].arn
    retry_policy {
      maximum_retry_attempts = 0 # the job isn't urgent: next week's run catches up
    }
  }
}
# endregion lookup-cache
