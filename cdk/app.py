#!/usr/bin/env python3
"""CDK app entry point for TAO Mining Intelligence Pipeline."""

import aws_cdk as cdk

from stacks.pipeline_stack import TaoPipelineStack

app = cdk.App()
TaoPipelineStack(app, "TaoPipeline", env=cdk.Environment(region="us-east-1"))
app.synth()
