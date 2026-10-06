output "url" {
  description = "The website."
  value       = "https://${var.attach_domain ? var.domain_name : aws_cloudfront_distribution.site.domain_name}/"
}

output "bucket" {
  value = aws_s3_bucket.site.id
}

output "distribution_id" {
  value = aws_cloudfront_distribution.site.id
}

output "distribution_domain_name" {
  description = "Target of the CNAME record for domain_name."
  value       = aws_cloudfront_distribution.site.domain_name
}

output "certificate_validation_records" {
  description = "DNS records that validate the ACM certificate for domain_name."
  value = [
    for o in try(aws_acm_certificate.site[0].domain_validation_options, []) :
    { name = o.resource_record_name, type = o.resource_record_type, value = o.resource_record_value }
  ]
}

output "certificate_status" {
  value = try(aws_acm_certificate.site[0].status, null)
}

output "deploy_role_arn" {
  value = aws_iam_role.deploy.arn
}

output "deploy_access_key_id" {
  value = aws_iam_access_key.deploy.id
}

output "deploy_secret_access_key" {
  value     = aws_iam_access_key.deploy.secret
  sensitive = true
}

output "aws_config" {
  description = "Profiles for ~/.aws/config; put the access key in ~/.aws/credentials under the -deploy-user profile."
  value       = <<-EOT
    [profile ${var.name}-deploy-user]
    region = ${var.region}

    [profile ${var.name}-deploy]
    role_arn = ${aws_iam_role.deploy.arn}
    source_profile = ${var.name}-deploy-user
    region = ${var.region}
  EOT
}

output "deploy_commands" {
  description = "Run from the repository root."
  value       = <<-EOT
    aws --profile ${var.name}-deploy s3 sync website/ s3://${aws_s3_bucket.site.id}/ --delete --exclude ".DS_Store" --cache-control "public, max-age=300"
    aws --profile ${var.name}-deploy cloudfront create-invalidation --distribution-id ${aws_cloudfront_distribution.site.id} --paths "/*"
  EOT
}
