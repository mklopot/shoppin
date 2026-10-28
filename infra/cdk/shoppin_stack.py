"""
Shoppin AWS CDK Stack - Cost-Optimized Single-Host Architecture (~$15-$20/month)
Provisions:
- Cost-effective VPC (Single public subnet, 0 NAT Gateways = $0 NAT fee)
- Elastic IP (Stable public IPv4 for Route 53 A-record)
- EC2 t4g.small (ARM64 Graviton2, 2 vCPU, 2 GB RAM, ~$12.26/month)
- 20 GB gp3 encrypted root volume (~$1.60/month)
- S3 Bucket for automated encrypted database backups (with 30-day lifecycle)
- IAM Instance Profile with AWS Systems Manager (SSM) for secure shell access
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_s3 as s3,
)
from constructs import Construct


class ShoppinStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1. Dedicated S3 Bucket for Automated Nightly Database Backups
        backup_bucket = s3.Bucket(
            self,
            "ShoppinDbBackups",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="PruneOldBackupsAfter30Days",
                    expiration=Duration.days(30),
                )
            ],
        )

        # 2. Cost-Optimized VPC (1 Public Subnet, 0 NAT Gateways)
        # Bypasses the $33/mo AWS NAT Gateway fee by placing instance in public subnet with security group
        vpc = ec2.Vpc(
            self,
            "ShoppinVpc",
            max_azs=1,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
        )

        # 3. Security Group: Allow HTTP (80), HTTPS (443), and SSH (22)
        security_group = ec2.SecurityGroup(
            self,
            "ShoppinSecurityGroup",
            vpc=vpc,
            description="Security group for Shoppin single-host EC2 server",
            allow_all_outbound=True,
        )
        security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(80),
            "Allow inbound HTTP for Let's Encrypt ACME verification and redirect",
        )
        security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(443),
            "Allow inbound HTTPS for secure web and WebSocket traffic",
        )
        security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(22),
            "Allow SSH access (optional; AWS SSM is preferred)",
        )

        # 4. IAM Role for EC2 Instance
        # Grants AWS Systems Manager Session Manager access (SSH without open ports or keys)
        # Grants S3 write permissions to upload database backups
        instance_role = iam.Role(
            self,
            "ShoppinInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
            ],
        )
        backup_bucket.grant_read_write(instance_role)

        # 5. EC2 Instance: t4g.small (ARM64 Graviton2)
        # Ubuntu 24.04 LTS Noble Numbat AMI for ARM64
        machine_image = ec2.MachineImage.from_ssm_parameter(
            "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id",
            os=ec2.OperatingSystemType.LINUX,
        )

        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "curl -fsSL https://raw.githubusercontent.com/mklopot/shoppin/v2-django/scripts/setup-ec2.sh | bash"
        )

        instance = ec2.Instance(
            self,
            "ShoppinServer",
            vpc=vpc,
            instance_type=ec2.InstanceType("t4g.small"),
            machine_image=machine_image,
            security_group=security_group,
            role=instance_role,
            user_data=user_data,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",
                    volume=ec2.BlockDeviceVolume.ebs(
                        volume_size=20,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        encrypted=True,
                        delete_on_termination=False,
                    ),
                )
            ],
        )

        # 6. Elastic IP (Permanent Public IP for DNS A-Record)
        elastic_ip = ec2.CfnEIP(
            self,
            "ShoppinElasticIp",
            domain="vpc",
            instance_id=instance.instance_id,
        )

        # 7. Stack Outputs
        CfnOutput(
            self,
            "PublicIpAddress",
            value=elastic_ip.ref,
            description="Static Public IPv4 address. Point your Route 53 A-record here.",
        )
        CfnOutput(
            self,
            "InstanceId",
            value=instance.instance_id,
            description="EC2 Instance ID for AWS Systems Manager Session access.",
        )
        CfnOutput(
            self,
            "BackupBucketName",
            value=backup_bucket.bucket_name,
            description="S3 Bucket name for automated database backups.",
        )
        CfnOutput(
            self,
            "ConnectViaSSMCommand",
            value=f"aws ssm start-session --target {instance.instance_id}",
            description="Run this command to SSH directly into the instance without keys or open ports.",
        )
