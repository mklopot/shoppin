# ==============================================================================
# Shoppin OpenTofu / Terraform Configuration
# Cost-Optimized Single-Host Architecture (~$15-$20/month)
# ==============================================================================

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "Shoppin"
      Environment = "Production"
      ManagedBy   = "OpenTofu"
    }
  }
}

# 1. Random suffix for unique bucket name
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

# 2. S3 Bucket for Automated Database Backups
resource "aws_s3_bucket" "db_backups" {
  bucket        = "shoppin-db-backups-${random_id.bucket_suffix.hex}"
  force_destroy = false
}

resource "aws_s3_bucket_server_side_encryption_configuration" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "db_backups" {
  bucket                  = aws_s3_bucket.db_backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id
  rule {
    id     = "prune-backups-after-30-days"
    status = "Enabled"
    expiration {
      days = 30
    }
  }
}

# 3. Cost-Optimized VPC (1 Public Subnet, 0 NAT Gateways)
resource "aws_vpc" "shoppin_vpc" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = {
    Name = "shoppin-vpc"
  }
}

resource "aws_internet_gateway" "gw" {
  vpc_id = aws_vpc.shoppin_vpc.id
  tags = {
    Name = "shoppin-igw"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.shoppin_vpc.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true
  availability_zone       = "${var.aws_region}a"
  tags = {
    Name = "shoppin-public-subnet"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.shoppin_vpc.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.gw.id
  }
  tags = {
    Name = "shoppin-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# 4. Security Group (Port 80 HTTP, Port 443 HTTPS, Port 22 SSH)
resource "aws_security_group" "server_sg" {
  name        = "shoppin-server-sg"
  description = "Allow inbound HTTP, HTTPS, and SSH traffic"
  vpc_id      = aws_vpc.shoppin_vpc.id

  ingress {
    description = "HTTP for Let's Encrypt challenge & redirect"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS for secure web and WebSocket traffic"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH administrative access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "shoppin-server-sg"
  }
}

# 5. IAM Role & Instance Profile for EC2
resource "aws_iam_role" "instance_role" {
  name = "shoppin-ec2-instance-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

# Attach AWS Systems Manager for secure console access without open ports
resource "aws_iam_role_policy_attachment" "ssm_policy" {
  role       = aws_iam_role.instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Grant read/write access to S3 backup bucket
resource "aws_iam_role_policy" "s3_backup_policy" {
  name = "shoppin-s3-backup-policy"
  role = aws_iam_role.instance_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.db_backups.arn,
          "${aws_s3_bucket.db_backups.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "instance_profile" {
  name = "shoppin-instance-profile"
  role = aws_iam_role.instance_role.name
}

# 6. Latest Ubuntu 24.04 LTS Noble AMI for ARM64 Graviton
data "aws_ami" "ubuntu_arm64" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# 7. EC2 Instance: t4g.small (ARM64 Graviton2)
resource "aws_instance" "server" {
  ami                  = data.aws_ami.ubuntu_arm64.id
  instance_type        = var.instance_type
  subnet_id            = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.server_sg.id]
  iam_instance_profile = aws_iam_instance_profile.instance_profile.name

  root_block_device {
    volume_size           = var.root_volume_size_gb
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = false
    tags = {
      Name = "shoppin-root-disk"
    }
  }

  user_data = <<-EOF
              #!/bin/bash
              curl -fsSL https://raw.githubusercontent.com/mklopot/shoppin/v2-django/scripts/setup-ec2.sh | bash
              EOF

  tags = {
    Name = "shoppin-production-server"
  }
}

# 8. Elastic IP
resource "aws_eip" "server_eip" {
  instance = aws_instance.server.id
  domain   = "vpc"
  tags = {
    Name = "shoppin-server-eip"
  }
}
