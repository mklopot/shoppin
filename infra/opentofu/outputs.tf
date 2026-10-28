output "public_ip" {
  description = "Static Public IPv4 address for Route 53 DNS A-record"
  value       = aws_eip.server_eip.public_ip
}

output "instance_id" {
  description = "EC2 Instance ID for AWS Systems Manager Session"
  value       = aws_instance.server.id
}

output "backup_bucket_name" {
  description = "S3 Bucket name for automated database backups"
  value       = aws_s3_bucket.db_backups.bucket_name
}

output "ssm_connect_command" {
  description = "Command to connect securely via AWS SSM without SSH keys or open port 22"
  value       = "aws ssm start-session --target ${aws_instance.server.id}"
}
