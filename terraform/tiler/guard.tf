# Cost guard: alarms on CloudFront traffic, a kill switch, and a budget
# backstop. Reserved concurrency (reserved_concurrency) caps what the tiler's
# Lambdas can spend; this caps the rest, which no Lambda limit sees: requests
# and transfer served from CloudFront's cache.
#
#   warning alarms (email): bytes downloaded or requests well above normal
#   kill alarm: bytes downloaded far above normal, sustained -> kill Lambda
#   budget (email at 80% / forecast 100%; at 100% -> kill Lambda)
#
# The kill Lambda sets the tiler Lambdas' reserved concurrency to 0 and
# disables the distributions (this one and guard_extra_distribution_ids, e.g.
# the website's). `tofu apply` restores both. CloudFront metrics exist only in
# us-east-1, so the default provider must be us-east-1.

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# region guard-locals
locals {
  guard_distributions = concat([aws_cloudfront_distribution.this.id], var.guard_extra_distribution_ids)
  guard_functions = [
    for m in [module.nasa, module.noaa, module.ecmwf] : { name = m.function_name, region = m.region }
  ]
  account = data.aws_caller_identity.current.account_id
  # CloudFront publishes per-distribution metrics every minute; alarms sum
  # them over 5-minute periods, so hourly thresholds become per-period ones.
  guard_period = 300
  per_period   = local.guard_period / 3600
}
# endregion guard-locals

# region guard-topics
resource "aws_sns_topic" "alerts" {
  #checkov:skip=CKV_AWS_26:Alert notifications carry no sensitive data
  count = var.guard ? 1 : 0
  name  = "${var.name}-cost-alerts"
}

resource "aws_sns_topic_subscription" "alert_email" {
  for_each  = var.guard ? toset(var.alert_emails) : toset([])
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email" # the address must confirm the subscription (AWS sends a link)
  endpoint  = each.value
}

# The budget backstop publishes here; the kill Lambda is subscribed.
resource "aws_sns_topic" "kill" {
  #checkov:skip=CKV_AWS_26:Budget notifications carry no sensitive data
  count = var.guard ? 1 : 0
  name  = "${var.name}-cost-kill"
}

data "aws_iam_policy_document" "kill_topic" {
  count = var.guard ? 1 : 0
  statement {
    sid       = "Budgets"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.kill[0].arn]
    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
}

resource "aws_sns_topic_policy" "kill" {
  count  = var.guard ? 1 : 0
  arn    = aws_sns_topic.kill[0].arn
  policy = data.aws_iam_policy_document.kill_topic[0].json
}
# endregion guard-topics

# region kill-lambda
data "archive_file" "kill" {
  type        = "zip"
  source_file = "${path.module}/guard/kill.py"
  output_path = "${path.module}/.build/guard-kill.zip"
}

data "aws_iam_policy_document" "kill_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "kill" {
  count              = var.guard ? 1 : 0
  name               = "${var.name}-cost-kill"
  assume_role_policy = data.aws_iam_policy_document.kill_assume.json
}

data "aws_iam_policy_document" "kill" {
  count = var.guard ? 1 : 0
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.kill[0].arn}:*"]
  }
  statement {
    sid       = "StopTiler"
    actions   = ["lambda:PutFunctionConcurrency", "lambda:GetFunctionConcurrency"]
    resources = [for f in local.guard_functions : "arn:aws:lambda:${f.region}:${local.account}:function:${f.name}"]
  }
  statement {
    sid       = "DisableDistributions"
    actions   = ["cloudfront:GetDistributionConfig", "cloudfront:UpdateDistribution"]
    resources = [for d in local.guard_distributions : "arn:aws:cloudfront::${local.account}:distribution/${d}"]
  }
  statement {
    sid       = "Report"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts[0].arn]
  }
}

resource "aws_iam_role_policy" "kill" {
  count  = var.guard ? 1 : 0
  name   = "cost-kill"
  role   = aws_iam_role.kill[0].id
  policy = data.aws_iam_policy_document.kill[0].json
}

resource "aws_cloudwatch_log_group" "kill" {
  #checkov:skip=CKV_AWS_158:AWS-managed encryption is sufficient for these logs
  count             = var.guard ? 1 : 0
  name              = "/aws/lambda/${var.name}-cost-kill"
  retention_in_days = 365 # rare, and worth keeping
}

resource "aws_lambda_function" "kill" {
  #checkov:skip=CKV_AWS_117:Calls AWS APIs only; no VPC needed
  #checkov:skip=CKV_AWS_116:Alarm and SNS invocations retry on their own
  #checkov:skip=CKV_AWS_272:Code is in this module; no code signing
  #checkov:skip=CKV_AWS_173:Environment holds no credentials
  #checkov:skip=CKV_AWS_115:Invoked only by the guard
  #checkov:skip=CKV_AWS_50:No tracing needed
  count            = var.guard ? 1 : 0
  function_name    = "${var.name}-cost-kill"
  role             = aws_iam_role.kill[0].arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "kill.handler"
  filename         = data.archive_file.kill.output_path
  source_code_hash = data.archive_file.kill.output_base64sha256
  memory_size      = 128
  timeout          = 120

  environment {
    variables = {
      FUNCTIONS     = jsonencode(local.guard_functions)
      DISTRIBUTIONS = jsonencode(local.guard_distributions)
      ALERT_TOPIC   = aws_sns_topic.alerts[0].arn
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.kill[0].name
  }

  depends_on = [aws_iam_role_policy.kill]

  lifecycle {
    precondition {
      condition     = data.aws_region.current.region == "us-east-1"
      error_message = "The cost guard needs the default aws provider in us-east-1 (CloudFront metrics are only there)."
    }
  }
}

resource "aws_lambda_permission" "kill_alarm" {
  count         = var.guard ? 1 : 0
  statement_id  = "KillAlarm"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.kill[0].function_name
  principal     = "lambda.alarms.cloudwatch.amazonaws.com"
  source_arn    = aws_cloudwatch_metric_alarm.kill[0].arn
}

resource "aws_lambda_permission" "kill_sns" {
  count         = var.guard ? 1 : 0
  statement_id  = "KillBudget"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.kill[0].function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.kill[0].arn
}

resource "aws_sns_topic_subscription" "kill" {
  count     = var.guard ? 1 : 0
  topic_arn = aws_sns_topic.kill[0].arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.kill[0].arn
}
# endregion kill-lambda

# region guard-alarms
# Sum of a CloudFront metric over every guarded distribution, per period.
locals {
  guard_alarms = {
    warn-bytes = {
      metric      = "BytesDownloaded"
      threshold   = var.guard_warn_bytes_per_hour * local.per_period
      periods     = 1
      kill        = false
      description = "CloudFront downloads above ${var.guard_warn_bytes_per_hour / 1e9} GB/h (warning)"
    }
    warn-requests = {
      metric      = "Requests"
      threshold   = var.guard_warn_requests_per_hour * local.per_period
      periods     = 1
      kill        = false
      description = "CloudFront requests above ${var.guard_warn_requests_per_hour}/h (warning)"
    }
    kill = {
      metric      = "BytesDownloaded"
      threshold   = var.guard_kill_bytes_per_hour * local.per_period
      periods     = ceil(var.guard_kill_minutes * 60 / local.guard_period)
      kill        = true
      description = "CloudFront downloads above ${var.guard_kill_bytes_per_hour / 1e9} GB/h for ${var.guard_kill_minutes} min: stops the tiler and disables its distributions"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "warn" {
  for_each            = var.guard ? { for k, a in local.guard_alarms : k => a if !a.kill } : {}
  alarm_name          = "${var.name}-${each.key}"
  alarm_description   = each.value.description
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = each.value.periods
  threshold           = each.value.threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  ok_actions          = [aws_sns_topic.alerts[0].arn]

  metric_query {
    id          = "total"
    expression  = "SUM(METRICS())"
    label       = "${each.value.metric} (all guarded distributions)"
    return_data = true
  }

  dynamic "metric_query" {
    for_each = local.guard_distributions
    content {
      id = "m${metric_query.key}"
      metric {
        namespace   = "AWS/CloudFront"
        metric_name = each.value.metric
        period      = local.guard_period
        stat        = "Sum"
        dimensions  = { DistributionId = metric_query.value, Region = "Global" }
      }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "kill" {
  count               = var.guard ? 1 : 0
  alarm_name          = "${var.name}-kill"
  alarm_description   = local.guard_alarms.kill.description
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = local.guard_alarms.kill.periods
  datapoints_to_alarm = local.guard_alarms.kill.periods
  threshold           = local.guard_alarms.kill.threshold
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_lambda_function.kill[0].arn, aws_sns_topic.alerts[0].arn]

  metric_query {
    id          = "total"
    expression  = "SUM(METRICS())"
    label       = "BytesDownloaded (all guarded distributions)"
    return_data = true
  }

  dynamic "metric_query" {
    for_each = local.guard_distributions
    content {
      id = "m${metric_query.key}"
      metric {
        namespace   = "AWS/CloudFront"
        metric_name = "BytesDownloaded"
        period      = local.guard_period
        stat        = "Sum"
        dimensions  = { DistributionId = metric_query.value, Region = "Global" }
      }
    }
  }
}
# endregion guard-alarms

# region guard-budget
# Backstop on actual spend. Billing data lags by hours, so this catches slow
# leaks, not floods. Linked accounts can't filter by cost-allocation tag
# unless the management account activates it, so by default this counts the
# services the tiler and website use, account-wide (every deployment, and
# anything else in the account using them).
resource "aws_budgets_budget" "guard" {
  count        = var.guard && var.guard_budget_usd != null ? 1 : 0
  name         = "${var.name}-cost-guard"
  budget_type  = "COST"
  limit_amount = tostring(var.guard_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "cost_filter" {
    for_each = var.guard_budget_filters
    content {
      name   = cost_filter.key
      values = cost_filter.value
    }
  }

  # Email only: 80% of the budget spent, or the month forecast to exceed it.
  dynamic "notification" {
    for_each = length(var.alert_emails) > 0 ? { ACTUAL = 80, FORECASTED = 100 } : {}
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.key
      subscriber_email_addresses = var.alert_emails
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.alert_emails
    subscriber_sns_topic_arns  = [aws_sns_topic.kill[0].arn]
  }

  depends_on = [aws_sns_topic_policy.kill]
}
# endregion guard-budget
