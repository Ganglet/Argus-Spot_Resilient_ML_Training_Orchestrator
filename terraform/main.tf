terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ---------------------------------------------------------------------------
# Billing alarm — set this before ANY other resource
# ---------------------------------------------------------------------------
resource "aws_budgets_budget" "dev_limit" {
  name         = "${var.project}-dev-budget"
  budget_type  = "COST"
  limit_amount = "20"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}

# ---------------------------------------------------------------------------
# VPC — 2 AZs, public + private subnets
# EKS requires subnets in at least 2 AZs.
# eu-north-1 has 3 AZs: use a and b.
# ---------------------------------------------------------------------------
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "${var.project}-vpc" }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-igw" }
}

# Public subnets (NAT gateway, load balancers)
resource "aws_subnet" "public" {
  for_each = {
    "a" = "10.0.1.0/24"
    "b" = "10.0.2.0/24"
  }

  vpc_id                  = aws_vpc.main.id
  cidr_block              = each.value
  availability_zone       = "${var.aws_region}${each.key}"
  map_public_ip_on_launch = true

  # Required tag for EKS to discover subnets for load balancers
  tags = {
    Name                                        = "${var.project}-public-${each.key}"
    "kubernetes.io/role/elb"                    = "1"
    "kubernetes.io/cluster/${var.project}-eks"  = "shared"
  }
}

# Private subnets (EKS nodes)
resource "aws_subnet" "private" {
  for_each = {
    "a" = "10.0.10.0/24"
    "b" = "10.0.11.0/24"
  }

  vpc_id            = aws_vpc.main.id
  cidr_block        = each.value
  availability_zone = "${var.aws_region}${each.key}"

  tags = {
    Name                                        = "${var.project}-private-${each.key}"
    "kubernetes.io/role/internal-elb"           = "1"
    "kubernetes.io/cluster/${var.project}-eks"  = "shared"
  }
}

# ---------------------------------------------------------------------------
# NAT Gateway — NOT created here. Added in terraform/eks.tf (Week 6).
# NAT costs $0.045/hr just for existing. Don't create it until EKS needs it.
# ---------------------------------------------------------------------------

# Public route table — internet traffic exits via IGW
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }
  tags = { Name = "${var.project}-public-rt" }
}

# Private route table — no outbound route yet; NAT added when eks.tf is applied
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-private-rt" }
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}
