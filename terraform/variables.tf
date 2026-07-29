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
