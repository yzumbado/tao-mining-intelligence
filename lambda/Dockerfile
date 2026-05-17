FROM public.ecr.aws/lambda/python:3.12

# Install system dependencies for substrate-interface (bittensor dependency)
RUN dnf install -y gcc python3-devel libffi-devel openssl-devel && \
    dnf clean all

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ${LAMBDA_TASK_ROOT}/src/

# Copy Jinja2 templates for site generation
COPY templates/ ${LAMBDA_TASK_ROOT}/templates/

# Default handler (overridden per Lambda in CDK)
CMD ["collector.handler.handle"]
