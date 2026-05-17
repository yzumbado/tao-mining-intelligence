"""TAO Mining Intelligence Pipeline - Lambda source package."""

import os

if os.environ.get("PIPELINE_ENV") == "aws":
    import src.lambda_patch  # noqa: F401
