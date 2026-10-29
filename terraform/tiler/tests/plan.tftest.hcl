# `tofu test` (no AWS credentials needed): plans the stack with mocked providers
# and checks the routing and per-region settings derived from datasets.yaml.

mock_provider "aws" {
  mock_data "aws_region" {
    defaults = { region = "us-east-1" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:us-east-1:123456789012:mock" }
  }
  mock_resource "aws_cloudwatch_metric_alarm" {
    defaults = { arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:mock" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:mock" }
  }
  mock_resource "aws_cloudfront_function" {
    defaults = { arn = "arn:aws:cloudfront::123456789012:function/mock" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:us-west-2:123456789012:secret:mock" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = { api_endpoint = "https://abc123.execute-api.us-east-1.amazonaws.com", execution_arn = "arn:aws:execute-api:us-east-1:123456789012:abc123" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:mock", version = "1" }
  }
  mock_resource "aws_lambda_alias" {
    defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:mock:live", invoke_arn = "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:mock:live/invocations" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}
mock_provider "aws" {
  alias = "nasa"

  mock_data "aws_region" {
    defaults = { region = "us-west-2" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:mock" }
  }
  mock_resource "aws_cloudfront_function" {
    defaults = { arn = "arn:aws:cloudfront::123456789012:function/mock" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:us-west-2:123456789012:secret:mock" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = { api_endpoint = "https://abc123.execute-api.us-east-1.amazonaws.com", execution_arn = "arn:aws:execute-api:us-east-1:123456789012:abc123" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:mock", version = "1" }
  }
  mock_resource "aws_lambda_alias" {
    defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:mock:live", invoke_arn = "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:mock:live/invocations" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}
mock_provider "aws" {
  alias = "noaa"

  mock_data "aws_region" {
    defaults = { region = "us-east-1" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:mock" }
  }
  mock_resource "aws_cloudfront_function" {
    defaults = { arn = "arn:aws:cloudfront::123456789012:function/mock" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:us-west-2:123456789012:secret:mock" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = { api_endpoint = "https://abc123.execute-api.us-east-1.amazonaws.com", execution_arn = "arn:aws:execute-api:us-east-1:123456789012:abc123" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:mock", version = "1" }
  }
  mock_resource "aws_lambda_alias" {
    defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:mock:live", invoke_arn = "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:mock:live/invocations" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}
mock_provider "aws" {
  alias = "ecmwf"

  mock_data "aws_region" {
    defaults = { region = "eu-south-1" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:mock" }
  }
  mock_resource "aws_cloudfront_function" {
    defaults = { arn = "arn:aws:cloudfront::123456789012:function/mock" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:us-west-2:123456789012:secret:mock" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_apigatewayv2_api" {
    defaults = { api_endpoint = "https://abc123.execute-api.us-east-1.amazonaws.com", execution_arn = "arn:aws:execute-api:us-east-1:123456789012:abc123" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:mock", version = "1" }
  }
  mock_resource "aws_lambda_alias" {
    defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:mock:live", invoke_arn = "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:mock:live/invocations" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}
mock_provider "random" {}

override_resource {
  target = terraform_data.image
  values = { output = "testtag" }
}

run "plan" {
  command = plan

  # region routes-assert
  assert {
    condition = {
      for b in aws_cloudfront_distribution.this.ordered_cache_behavior : b.path_pattern => b.target_origin_id
      } == {
      "/cmr/*"                        = "nasa"
      "/datasets/nisar-gcov/*"        = "nasa"
      "/datasets/smap-l4/*"           = "nasa"
      "/datasets/hls-l30/*"           = "nasa"
      "/datasets/goes19-abi/*"        = "noaa"
      "/datasets/era5-land-t2m/*"     = "ecmwf"
      "/datasets/viirs-blackmarble/*" = "nasa"
      "/datasets/viirs-lst-daily/*"   = "nasa"
      "/datasets/goes19-lst/*"        = "noaa"
      "/datasets/chirps-daily/*"      = "noaa"
      "/datasets/aster-gdem/*"        = "nasa"
    }
    error_message = "CloudFront routes don't match datasets.yaml"
  }
  # endregion routes-assert

  assert {
    condition     = aws_cloudfront_distribution.this.default_cache_behavior[0].target_origin_id == "noaa"
    error_message = "Default origin should be the NOAA (us-east-1) deployment"
  }

  assert {
    condition     = module.nasa.function_name == "ycgs-titiler-nasa" && module.ecmwf.function_name == "ycgs-titiler-ecmwf"
    error_message = "Unexpected function names"
  }

  # region origin-shield-assert
  assert {
    condition = {
      for o in aws_cloudfront_distribution.this.origin : o.origin_id => o.origin_shield[0].origin_shield_region
      } == {
      nasa  = "us-west-2"
      noaa  = "us-east-1"
      ecmwf = "eu-central-1" # eu-south-1 has no Origin Shield
    }
    error_message = "Origin Shield should be in (or nearest to) each origin's region"
  }
  # endregion origin-shield-assert

  # region guard-assert
  assert {
    condition     = module.nasa.reserved_concurrency == 60 && module.noaa.reserved_concurrency == 60 && module.ecmwf.reserved_concurrency == 30
    error_message = "Default reserved concurrency should cap the tiler at ~$17/h"
  }

  assert {
    condition = (
      abs(aws_cloudwatch_metric_alarm.kill[0].threshold - 50e9 / 12) < 1
      && aws_cloudwatch_metric_alarm.kill[0].evaluation_periods == 3
      && abs(aws_cloudwatch_metric_alarm.warn["warn-bytes"].threshold - 5e9 / 12) < 1
      && abs(aws_cloudwatch_metric_alarm.warn["warn-requests"].threshold - 50000 / 12) < 1
    )
    error_message = "Guard thresholds: kill at 50 GB/h for 15 min, warn at 5 GB/h or 50,000 requests/h (per 5-minute period)"
  }

  assert {
    condition     = aws_budgets_budget.guard[0].limit_amount == "50" && length(aws_budgets_budget.guard[0].notification) == 1
    error_message = "Budget backstop: $50, and without alert emails only the kill notification"
  }
  # endregion guard-assert
}

run "guard_extra_apis" {
  command = plan
  variables {
    guard_extra_functions = [{ name = "places", region = "us-east-1" }]
    guard_extra_apis      = ["api123"]
  }
  assert {
    condition = (
      length(aws_cloudwatch_metric_alarm.api) == 2
      && abs(aws_cloudwatch_metric_alarm.api["kill-api"].threshold - 2000 / 12) < 1
      && aws_cloudwatch_metric_alarm.api["kill-api"].evaluation_periods == 3
      && length(aws_lambda_permission.kill_api_alarm) == 1
    )
    error_message = "Guarded APIs: warn and kill alarms on their request count (kill at 2000/h for 15 min)"
  }
  assert {
    condition     = strcontains(aws_lambda_function.kill[0].environment[0].variables.FUNCTIONS, "\"places\"")
    error_message = "The kill switch must stop the guarded functions too"
  }
}

run "guard_off" {
  command = plan
  variables {
    guard = false
  }
  assert {
    condition     = length(aws_lambda_function.kill) == 0 && length(aws_budgets_budget.guard) == 0
    error_message = "guard = false should create no guard resources"
  }
}

run "origin_shield_off" {
  command = plan
  variables {
    origin_shield = false
  }
  assert {
    condition     = alltrue([for o in aws_cloudfront_distribution.this.origin : length(o.origin_shield) == 0])
    error_message = "origin_shield = false should leave the origins without Origin Shield"
  }
}

run "cors_restricted_adds_origin_to_cache_key" {
  command = plan
  variables {
    cors_origins = ["https://example.org"]
  }
  assert {
    condition     = aws_cloudfront_cache_policy.titiler.parameters_in_cache_key_and_forwarded_to_origin[0].headers_config[0].header_behavior == "whitelist"
    error_message = "Origin must be in the cache key when CORS is restricted"
  }
}
