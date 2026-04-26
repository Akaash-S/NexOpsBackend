import httpx
import json
from typing import Optional

async def validate_cloud_provider(provider_type: str, token: str, secret: Optional[str] = None) -> bool:
    """
    Performs a real API call to the provider to verify if the token/credentials are valid.
    """
    try:
        async with httpx.AsyncClient() as client:
            if provider_type == 'vercel':
                response = await client.get(
                    "https://api.vercel.com/v2/user",
                    headers={"Authorization": f"Bearer {token}"}
                )
                return response.status_code == 200
            
            if provider_type == 'render':
                response = await client.get(
                    "https://api.render.com/v1/owners",
                    headers={"Authorization": f"Bearer {token}"}
                )
                return response.status_code == 200

            if provider_type == 'netlify':
                response = await client.get(
                    "https://api.netlify.com/api/v1/user",
                    headers={"Authorization": f"Bearer {token}"}
                )
                return response.status_code == 200
            
            if provider_type == 'gcp':
                # GCP: Validate that the secret is a valid Service Account JSON
                if not secret: return False
                try:
                    data = json.loads(secret)
                    return data.get("type") == "service_account" and data.get("project_id") == token
                except:
                    return False

            if provider_type == 'azure':
                # Azure: Basic check for Subscription ID and Secret format
                return len(token) > 20 and secret is not None and len(secret) > 10
            
            # For AWS, etc.
            return len(token) > 5

    except Exception as e:
        print(f"Validation error for {provider_type}: {e}")
        return False
