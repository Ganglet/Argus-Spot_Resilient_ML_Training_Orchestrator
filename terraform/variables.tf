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
