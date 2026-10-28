variable "aws_region" {
  description = "AWS region to deploy resources into"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance size (t4g.small is ARM64 Graviton2, 2 vCPU, 2GB RAM for ~$12/mo)"
  type        = string
  default     = "t4g.small"
}

variable "root_volume_size_gb" {
  description = "Size of persistent gp3 root volume in GB"
  type        = number
  default     = 20
}

variable "domain_name" {
  description = "Domain name for the application (e.g. shoppin.app)"
  type        = string
  default     = "shoppin.yourdomain.com"
}
