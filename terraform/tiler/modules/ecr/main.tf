# ECR repository for one regional deployment's Lambda image (Lambda can only
# pull images from its own region).

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "name" {
  type = string
}


# region repository
resource "aws_ecr_repository" "this" {
  #checkov:skip=CKV_AWS_136:Images contain only open-source code; AES256 default encryption
  name                 = var.name
  image_tag_mutability = "IMMUTABLE" # tags are content hashes of the app
  force_delete         = true        # images are rebuilt from source

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 most recent images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}
# endregion repository

output "repository_url" {
  value = aws_ecr_repository.this.repository_url
}
