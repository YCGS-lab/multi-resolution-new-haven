# Deployment credentials: an IAM user whose access key can do nothing but assume the deploy role,
# which may sync the bucket and invalidate the distribution.

resource "aws_iam_user" "deploy" {
  name = "${var.name}-deploy"
}

resource "aws_iam_access_key" "deploy" {
  user = aws_iam_user.deploy.name
}

data "aws_iam_policy_document" "deploy_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = [aws_iam_user.deploy.arn]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${var.name}-deploy"
  description        = "Upload the ${var.name} website and invalidate its CloudFront cache"
  assume_role_policy = data.aws_iam_policy_document.deploy_assume.json
}

# region deploy-role-policy
data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.site.arn]
  }

  statement {
    sid       = "SyncObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]
  }

  statement {
    sid       = "Invalidate"
    actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation", "cloudfront:ListInvalidations"]
    resources = [aws_cloudfront_distribution.site.arn]
  }
}
# endregion deploy-role-policy

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

data "aws_iam_policy_document" "deploy_user" {
  statement {
    actions   = ["sts:AssumeRole"]
    resources = [aws_iam_role.deploy.arn]
  }
}

resource "aws_iam_user_policy" "deploy" {
  name   = "assume-deploy-role"
  user   = aws_iam_user.deploy.name
  policy = data.aws_iam_policy_document.deploy_user.json
}
