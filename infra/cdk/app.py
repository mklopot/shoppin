#!/usr/bin/env python3
import os

import aws_cdk as cdk
from shoppin_stack import ShoppinStack

app = cdk.App()

account = os.environ.get("CDK_DEFAULT_ACCOUNT")
region = os.environ.get("CDK_DEFAULT_REGION", "us-east-1")

ShoppinStack(
    app,
    "ShoppinStack",
    env=cdk.Environment(account=account, region=region),
    description="Cost-optimized ($15-$20/mo) single-host deployment for Shoppin on AWS",
)

app.synth()
