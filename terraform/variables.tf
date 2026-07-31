variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-north-1"
}

variable "project" {
  description = "Project name prefix applied to all resource names"
  type        = string
  default     = "argus"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

# Filled in terraform.tfvars (gitignored) — see terraform.tfvars.example
variable "alert_email" {
  description = "Email address for billing alarms"
  type        = string
}

# Spot node count. Default 0 keeps the cluster free-by-default — no Spot EC2
# runs until a test explicitly overrides this. The Week 6 interruption test
# needs 2: the reschedule path deletes the pod so it can land on a *second*
# non-cordoned node. Set via `terraform apply -var spot_desired_size=2` only
# during a billed test window, then destroy.
variable "spot_desired_size" {
  description = "Desired Spot node count (0 = off; 2 for the Week 6 reschedule test)"
  type        = number
  default     = 0
}

# Workload node capacity + types. Defaults are the Week 6 Free-Tier-safe config
# (On-Demand m7i-flex.large). For Track 1 (real Spot reclaim) on a Paid-plan
# account, override:
#   terraform apply -var 'workload_capacity_type=SPOT' \
#     -var 'workload_instance_types=["m5.large","c5.xlarge","m5.xlarge"]' \
#     -var spot_desired_size=2
variable "workload_capacity_type" {
  description = "ON_DEMAND (Free-Tier-safe default) or SPOT (Track 1, Paid plan only)"
  type        = string
  default     = "ON_DEMAND"
}

variable "workload_instance_types" {
  description = "Workload node instance types. m7i-flex.large is the Free-Tier default; use ML/Spot types for Track 1"
  type        = list(string)
  default     = ["m7i-flex.large"]
}
