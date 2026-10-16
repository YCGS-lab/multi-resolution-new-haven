# Credentials, each in the region of the deployment that uses it. Values are
# written with write-only attributes from ephemeral variables, so they never
# appear in state; the Lambda reads them at init (YCGS_SECRET_ARNS).

# region earthdata
resource "aws_secretsmanager_secret" "earthdata" {
  #checkov:skip=CKV2_AWS_57:Third-party credentials; rotation is manual (bump secrets_version)
  #checkov:skip=CKV_AWS_149:AWS-managed key is sufficient
  provider                = aws.nasa
  name                    = "${var.name}/earthdata"
  description             = "NASA Earthdata Login (token, or username and password) for titiler-cmr"
  recovery_window_in_days = var.secret_recovery_days
}

resource "aws_secretsmanager_secret_version" "earthdata" {
  provider  = aws.nasa
  secret_id = aws_secretsmanager_secret.earthdata.id
  secret_string_wo = jsonencode({
    TITILER_CMR_EARTHDATA_USERNAME = var.earthdata_username
    TITILER_CMR_EARTHDATA_PASSWORD = var.earthdata_password
    YCGS_EARTHDATA_TOKEN           = var.earthdata_token
  })
  secret_string_wo_version = var.secrets_version
}
# endregion earthdata

# region cds
resource "aws_secretsmanager_secret" "cds" {
  #checkov:skip=CKV2_AWS_57:Third-party credential; rotation is manual (bump secrets_version)
  #checkov:skip=CKV_AWS_149:AWS-managed key is sufficient
  provider                = aws.ecmwf
  name                    = "${var.name}/cds"
  description             = "Copernicus CDS API key for the ERA5-Land analysis-ready Zarr"
  recovery_window_in_days = var.secret_recovery_days
}

resource "aws_secretsmanager_secret_version" "cds" {
  provider                 = aws.ecmwf
  secret_id                = aws_secretsmanager_secret.cds.id
  secret_string_wo         = jsonencode({ YCGS_CDS_API_KEY = var.cds_api_key })
  secret_string_wo_version = var.secrets_version
}
# endregion cds

# region origin-token
# CloudFront -> API Gateway shared secret (not a credential: it only stops
# requests that bypass the CDN).
resource "random_password" "origin_verify" {
  length  = 40
  special = false
}
# endregion origin-token
