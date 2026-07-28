# ---------------------------------------------------------------------------
# EKS Cluster + Managed Node Groups (1 On-Demand for control, 1 Spot for workload)
# Week 2 Milestone
# ---------------------------------------------------------------------------

# IAM roles for EKS
resource "aws_iam_role" "eks_cluster" {
  name = "${var.project}-eks-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "eks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.eks_cluster.name
}

# The Cluster
resource "aws_eks_cluster" "main" {
  name     = "${var.project}-eks"
  role_arn = aws_iam_role.eks_cluster.arn
  version  = "1.32"

  vpc_config {
    subnet_ids = [
      for s in aws_subnet.public : s.id
    ]
    endpoint_public_access = true
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy
  ]
}

# IAM Role for Nodes
resource "aws_iam_role" "eks_nodes" {
  name = "${var.project}-eks-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eks_worker_node" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_iam_role_policy_attachment" "eks_cni" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.eks_nodes.name
}

resource "aws_iam_role_policy_attachment" "eks_registry" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  role       = aws_iam_role.eks_nodes.name
}

# --- 1 On-Demand Node Group (Control/System Pods) ---
resource "aws_eks_node_group" "system_nodes" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.project}-system-nodes"
  node_role_arn   = aws_iam_role.eks_nodes.arn
  subnet_ids      = [for s in aws_subnet.public : s.id] # Using public for simplicity without NAT

  instance_types = ["t3.small"]
  capacity_type  = "ON_DEMAND"

  scaling_config {
    desired_size = 1
    max_size     = 2
    min_size     = 1
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_worker_node,
    aws_iam_role_policy_attachment.eks_cni,
    aws_iam_role_policy_attachment.eks_registry,
  ]
}

# --- 1 Spot Node Group (Machine Learning Workloads) ---
resource "aws_eks_node_group" "spot_nodes" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.project}-spot-nodes"
  node_role_arn   = aws_iam_role.eks_nodes.arn
  subnet_ids      = [for s in aws_subnet.public : s.id]

  # On-Demand m7i-flex.large. ROOT CAUSE (2026-07-28, extends P-006): this AWS
  # account is HARD-RESTRICTED to Free-Tier-eligible instance types — any other
  # type fails with "InvalidParameterCombination: not eligible for Free Tier"
  # and the node group hangs ~20 min then CREATE_FAILED. That killed every
  # g4dn/m5/c5/t3.xlarge attempt (spot AND on-demand). m7i-flex.large is the
  # largest Free-Tier-eligible x86 type here: 2 vCPU / 8 GB — enough for the CPU
  # CIFAR-10 job + predict-service + operator. Only Free-Tier types will launch.
  instance_types = ["m7i-flex.large"]
  capacity_type  = "ON_DEMAND"

  scaling_config {
    desired_size = var.spot_desired_size # 0 by default; set to 2 for the Week 6 reschedule test
    max_size     = 2
    min_size     = 1 # mirror the working system node group (was 0)
  }

  labels = {
    lifecycle = "spot"
    workload  = "ml-training"
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_worker_node,
    aws_iam_role_policy_attachment.eks_cni,
    aws_iam_role_policy_attachment.eks_registry,
  ]
}