# ---------------------------------------------------------------------------
# ECR Repositories — one per image
# Free storage up to 500MB/month per repo; push/pull are free within region
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "operator" {
  name                 = "${var.project}/operator"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration { scan_on_push = true }
  tags = { Name = "${var.project}-operator" }
}

resource "aws_ecr_repository" "predict_service" {
  name                 = "${var.project}/predict-service"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration { scan_on_push = true }
  tags = { Name = "${var.project}-predict-service" }
}

resource "aws_ecr_repository" "training_job" {
  name                 = "${var.project}/training-job"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration { scan_on_push = true }
  tags = { Name = "${var.project}-training-job" }
}

# Lifecycle: keep only last 5 images per repo — prevents storage bloat
resource "aws_ecr_lifecycle_policy" "operator" {
  repository = aws_ecr_repository.operator.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "predict_service" {
  repository = aws_ecr_repository.predict_service.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "training_job" {
  repository = aws_ecr_repository.training_job.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}
