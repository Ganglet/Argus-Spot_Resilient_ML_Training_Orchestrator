#!/usr/bin/env bash
#
# Cost safety net — run after EVERY session to confirm nothing billable is left
# running. Read-only (describe/list only), so it never changes or costs anything.
# Born from a $66 EKS cluster left running unnoticed (see problems_and_decisions).
#
# Usage:  ./scripts/verify_teardown.sh
# Exit 0 = clean; exit 1 = something billable is still up.
#
set -uo pipefail
export AWS_PAGER=""
HOME_REGION="${AWS_REGION:-eu-north-1}"
found=0

hit() { echo "  ⚠️  $1"; found=1; }

echo "== $HOME_REGION — billable resources =="
v=$(aws eks list-clusters --region "$HOME_REGION" --query 'clusters' --output text 2>/dev/null);          [ -n "$v" ] && hit "EKS clusters: $v"
v=$(aws ec2 describe-instances --region "$HOME_REGION" --filters Name=instance-state-name,Values=running,pending --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null); [ -n "$v" ] && hit "running EC2: $v"
v=$(aws ec2 describe-nat-gateways --region "$HOME_REGION" --filter Name=state,Values=available,pending --query 'NatGateways[].NatGatewayId' --output text 2>/dev/null); [ -n "$v" ] && hit "NAT gateways: $v"
v=$(aws elb describe-load-balancers --region "$HOME_REGION" --query 'LoadBalancerDescriptions[].LoadBalancerName' --output text 2>/dev/null);   [ -n "$v" ] && hit "classic LBs: $v"
v=$(aws elbv2 describe-load-balancers --region "$HOME_REGION" --query 'LoadBalancers[].LoadBalancerName' --output text 2>/dev/null);          [ -n "$v" ] && hit "ALB/NLBs: $v"
v=$(aws ec2 describe-addresses --region "$HOME_REGION" --query 'Addresses[?AssociationId==null].PublicIp' --output text 2>/dev/null);         [ -n "$v" ] && hit "unattached Elastic IPs: $v"
v=$(aws ec2 describe-volumes --region "$HOME_REGION" --filters Name=status,Values=available --query 'Volumes[].VolumeId' --output text 2>/dev/null); [ -n "$v" ] && hit "orphaned EBS volumes: $v"

echo "== all-region sweep: stray EC2 / EKS anywhere =="
for reg in $(aws ec2 describe-regions --query 'Regions[].RegionName' --output text 2>/dev/null); do
  ec2=$(aws ec2 describe-instances --region "$reg" --filters Name=instance-state-name,Values=running,pending --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null)
  eks=$(aws eks list-clusters --region "$reg" --query 'clusters' --output text 2>/dev/null)
  { [ -n "$ec2" ] || [ -n "$eks" ]; } && hit "$reg: EC2=[$ec2] EKS=[$eks]"
done

echo "------------------------------------------------------"
if [ "$found" -eq 0 ]; then
  echo "✅ CLEAN — nothing billable running. (S3/SQS/Lambda always-on are ~free.)"
  exit 0
else
  echo "❌ NOT CLEAN — tear down the items above before you walk away."
  exit 1
fi
