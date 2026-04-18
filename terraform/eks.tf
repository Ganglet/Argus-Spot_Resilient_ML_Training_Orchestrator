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
  version  = "1.30"

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

  # ML Instance defaults. (Fallback will be handled by Operator logic later)
  instance_types = ["g4dn.xlarge", "m5.xlarge", "c5.xlarge"]
  capacity_type  = "SPOT"

  scaling_config {
    desired_size = 0 # Starts at 0, spins up when requested
    max_size     = 2
    min_size     = 0
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