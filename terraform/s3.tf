# ---------------------------------------------------------------------------
# Checkpoint bucket — stores model state every N training steps
# Versioned so a bad checkpoint doesn't overwrite a good one
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "checkpoints" {
  bucket        = "${var.project}-checkpoints-${data.aws_caller_identity.current.account_id}"
  force_destroy = true # safe for dev; remove in prod

  tags = { Name = "${var.project}-checkpoints" }
}

resource "aws_s3_bucket_versioning" "checkpoints" {
  bucket = aws_s3_bucket.checkpoints.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "checkpoints" {
  bucket = aws_s3_bucket.checkpoints.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "checkpoints" {
  bucket                  = aws_s3_bucket.checkpoints.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# Feature store bucket — Lambda writes Spot price CSVs here every 5 min
# The ML pipeline (Person B) reads from this bucket
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "feature_store" {
  bucket        = "${var.project}-feature-store-${data.aws_caller_identity.current.account_id}"
  force_destroy = true

  tags = { Name = "${var.project}-feature-store" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "feature_store" {
  bucket = aws_s3_bucket.feature_store.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "feature_store" {
  bucket                  = aws_s3_bucket.feature_store.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle: expire raw price data after 180 days (6 months of history)
resource "aws_s3_bucket_lifecycle_configuration" "feature_store" {
  bucket = aws_s3_bucket.feature_store.id
  rule {
    id     = "expire-raw-prices"
    status = "Enabled"
    filter { prefix = "raw/" }
    expiration { days = 180 }
  }
}

# Current account ID — used to make bucket names globally unique
data "aws_caller_identity" "current" {}
