import os
import json
from dotenv import load_dotenv
from src.utils.logger import get_logger

load_dotenv()
logger = get_logger(__name__)


def get_aws_secrets():
    """Get secrets from AWS Secrets Manager."""
    try:
        import boto3
        from botocore.exceptions import ClientError

        secrets_client = boto3.client("secretsmanager", region_name="us-east-1")

        def get_secret(secret_name: str) -> str:
            """Retrieve a secret string from AWS Secrets Manager."""
            try:
                response = secrets_client.get_secret_value(SecretId=secret_name)
                return response.get("SecretString", "")
            except ClientError as e:
                raise RuntimeError(
                    f"Unable to retrieve secret '{secret_name}': {e.response['Error']['Message']}"
                )
            except Exception as e:
                raise RuntimeError(
                    f"Unexpected error retrieving secret '{secret_name}': {str(e)}"
                )

        # Get all secrets
        aws_config = {
            "OPENAI_API_KEY": get_secret("OPENAI_API_KEY"),
            "INTELLIGENCE_API_SECRET": get_secret("INTELLIGENCE_API_SECRET"),
            "TWILIO_ACCOUNT_SID": get_secret("TWILIO_ACCOUNT_SID"),
            "TWILIO_AUTH_TOKEN": get_secret("TWILIO_AUTH_TOKEN"),
            "TWILIO_WHATSAPP_FROM": get_secret("TWILIO_WHATSAPP_FROM"),
            "DATABASE_URL": get_secret("DATABASE_URL"),
            "S3_BUCKET_NAME": "theunce-project",
        }
        logger.info("Successfully loaded configuration from AWS Secrets Manager")
        return aws_config

    except Exception as e:
        logger.warning(f"Failed to load secrets from AWS Secrets Manager: {e}")
        return None


def get_config():
    """Get configuration from environment variables or AWS Secrets Manager.
    Falls back to environment variables if AWS Secrets Manager fails."""
    config = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "INTELLIGENCE_API_SECRET": os.getenv("INTELLIGENCE_API_SECRET"),
        "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID"),
        "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN"),
        "TWILIO_WHATSAPP_FROM": os.getenv("TWILIO_WHATSAPP_FROM"),
        "DATABASE_URL": os.getenv("DATABASE_URL"),
        "S3_BUCKET_NAME": "theunce-project",
    }

    # Only use AWS Secrets Manager if not in local environment
    if os.getenv("FLASK_ENV") != "local":
        aws_config = get_aws_secrets()
        if aws_config:
            config.update(aws_config)
        else:
            logger.info("Using environment variables for configuration")
    else:
        logger.info("Running in local environment, using environment variables")

    return config
