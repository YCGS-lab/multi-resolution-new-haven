output "url" {
  description = "The website."
  value       = module.site.url
}

output "tiler_url" {
  description = "The tiler (also in the website's env.json as services.tiler)."
  value       = module.tiler.url
}

output "places_url" {
  description = "The place search (also in the website's env.json as services.places; null when places = false)."
  value       = var.places ? module.places[0].url : null
}

output "env" {
  description = "The website's env.json, as written to its bucket."
  value       = local.site_env
}

output "bucket" {
  value = module.site.bucket
}

output "distribution_id" {
  value = module.site.distribution_id
}

output "tiler_distribution_id" {
  value = module.tiler.distribution_id
}

output "tiler_deployments" {
  value = module.tiler.deployments
}

output "certificate_validation_records" {
  value = module.site.certificate_validation_records
}

output "aws_config" {
  description = "Profiles for ~/.aws/config (website deploy user and role)."
  value       = module.site.aws_config
}

output "deploy_commands" {
  description = "Deploy website/ (run from the repository root); env.json is managed by OpenTofu."
  value       = module.site.deploy_commands
}

output "deploy_access_key_id" {
  value = module.site.deploy_access_key_id
}

output "deploy_secret_access_key" {
  value     = module.site.deploy_secret_access_key
  sensitive = true
}

output "tiler_guard" {
  description = "Cost guard: alert topic, kill switch function (us-east-1) and budget."
  value       = module.tiler.guard
}
