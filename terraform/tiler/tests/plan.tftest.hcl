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

override_resource {
  target = terraform_data.zip
  values = { output = "/tmp/zip" }
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

  assert {
    condition     = alltrue([for m in [module.nasa, module.noaa, module.ecmwf] : m.snap_start == "None" && m.package_type == "Zip"])
    error_message = "By default: zip packages, SnapStart off"
  }
}

run "snap_start_on_for_one_deployment" {
  command = plan
  variables {
    snap_start = { nasa = false, noaa = false, ecmwf = true }
  }
  assert {
    condition     = module.ecmwf.snap_start == "PublishedVersions" && module.nasa.snap_start == "None" && module.noaa.snap_start == "None"
    error_message = "snap_start = true should turn SnapStart on for that deployment only"
  }
}

run "container_images" {
  command = plan
  variables {
    packaging = "image"
  }
  assert {
    condition     = alltrue([for m in [module.nasa, module.noaa, module.ecmwf] : m.package_type == "Image"]) && length(terraform_data.zip) == 0
    error_message = "packaging = image: container images, no zip build"
  }
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

# function_layout = "reader": COG datasets get their own function in each deployment that also
# has xarray datasets (nasa: HLS, ASTER; noaa: CHIRPS); ecmwf has only xarray datasets.
run "reader_layout" {
  command = plan
  variables {
    function_layout = "reader"
  }

  # region reader-routes-assert
  assert {
    condition = {
      for b in aws_cloudfront_distribution.this.ordered_cache_behavior : b.path_pattern => b.target_origin_id
      } == {
      "/cmr/rasterio/*"               = "nasa_raster"
      "/cmr/*"                        = "nasa"
      "/cog/*"                        = "noaa_raster"
      "/datasets/nisar-gcov/*"        = "nasa"
      "/datasets/smap-l4/*"           = "nasa"
      "/datasets/hls-l30/*"           = "nasa_raster"
      "/datasets/goes19-abi/*"        = "noaa"
      "/datasets/era5-land-t2m/*"     = "ecmwf"
      "/datasets/viirs-blackmarble/*" = "nasa"
      "/datasets/viirs-lst-daily/*"   = "nasa"
      "/datasets/goes19-lst/*"        = "noaa"
      "/datasets/chirps-daily/*"      = "noaa_raster"
      "/datasets/aster-gdem/*"        = "nasa_raster"
    }
    error_message = "reader layout routes"
  }
  # endregion reader-routes-assert

  assert {
    condition     = [for b in aws_cloudfront_distribution.this.ordered_cache_behavior : b.path_pattern][0] == "/cmr/rasterio/*"
    error_message = "/cmr/rasterio/* must come before /cmr/*"
  }

  assert {
    condition     = length(aws_cloudfront_distribution.this.origin) == 5 && length(module.nasa_raster) == 1 && length(module.noaa_raster) == 1
    error_message = "five origins: nasa, nasa_raster, noaa, noaa_raster, ecmwf"
  }

  assert {
    condition = (
      module.nasa.function_name == "ycgs-titiler-nasa" && module.nasa_raster[0].function_name == "ycgs-titiler-nasa-raster"
      && module.noaa_raster[0].function_name == "ycgs-titiler-noaa-raster"
    )
    error_message = "raster function names"
  }

  assert {
    condition     = length(local.guard_functions) == 5
    error_message = "the kill switch covers every tiler function"
  }

  assert {
    condition = (
      local.backends_env["nasa"].YCGS_BACKENDS == "cmr-xarray,cmr-xarray-grouped"
      && local.backends_env["noaa"].YCGS_BACKENDS == "xarray"
      && length(local.backends_env["ecmwf"]) == 0
    )
    error_message = "YCGS_BACKENDS of the xarray functions"
  }
}

run "deployment_layout_sets_no_backends" {
  command = plan

  assert {
    condition     = alltrue([for d, e in local.backends_env : length(e) == 0]) && length(module.nasa_raster) == 0 && length(module.noaa_raster) == 0
    error_message = "the default layout leaves YCGS_BACKENDS unset (every backend) and adds no functions"
  }
}
