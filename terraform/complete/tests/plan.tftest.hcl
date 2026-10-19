# `tofu test` (no AWS credentials needed): plans the website + tiler with mocked
# providers and checks how they are wired together.

mock_provider "aws" {
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
    defaults = { region = "eu-central-1" }
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

# The site module configures its own providers, which cannot be mocked:
# replace the whole call (its env.json and deploy-command handling are
# checked by scripts/aws-tests/complete.sh against real AWS).
override_module {
  target = module.site
  outputs = {
    url             = "https://dmock.cloudfront.net/"
    bucket          = "ycgs-site-mock"
    distribution_id = "EMOCK"
  }
}

override_resource {
  target = module.tiler.terraform_data.image
  values = { output = "testtag" }
}

run "wiring" {
  command = plan

  variables {
    name               = "ycgs-complete"
    extra_cors_origins = ["http://localhost:8000"]
  }

  # region wiring-asserts
  assert {
    condition     = output.env.services.tiler == module.tiler.url
    error_message = "The website's env.json must point services.tiler at the tiler"
  }

  assert {
    condition     = output.env.services.titiler_cmr == "https://openveda.cloud/api/titiler-cmr" && output.env.cloud == "auto"
    error_message = "env.json must keep the repository's other settings"
  }

  assert {
    condition     = jsonencode(module.tiler.cors_origins) == jsonencode(["https://dmock.cloudfront.net", "http://localhost:8000"])
    error_message = "The tiler must allow the website's origin (and the extra ones)"
  }

  assert {
    condition     = module.tiler.deployments.nasa.function_name == "ycgs-complete-tiler-nasa"
    error_message = "Tiler resources are named <name>-tiler-..."
  }
  # endregion wiring-asserts
}
