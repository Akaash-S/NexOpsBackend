import httpx
import logging
from typing import Dict, Any

logger = logging.getLogger("nexops.pagerduty")


class PagerDutyService:
    BASE_URL = "https://api.pagerduty.com"

    @classmethod
    def _get_headers(cls, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Token token={token}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json"
        }

    @classmethod
    async def validate_token(cls, token: str) -> bool:
        """
        Validate the PagerDuty API token by checking access to the services list.
        """
        logger.info("Validating PagerDuty API token...")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{cls.BASE_URL}/services",
                    headers=cls._get_headers(token),
                    params={"limit": 1},
                    timeout=10.0
                )
                logger.info(f"PagerDuty validation response status: {response.status_code}")
                if response.status_code == 200:
                    return True
                else:
                    logger.warning(f"PagerDuty token validation failed with status: {response.status_code}, response: {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Error during PagerDuty token validation: {e}")
            return False

    @classmethod
    async def create_webhook_subscription(cls, token: str, webhook_url: str) -> Dict[str, Any]:
        """
        Create an account-level webhook subscription on PagerDuty.
        """
        logger.info(f"Registering PagerDuty webhook subscription for URL: {webhook_url}")
        payload = {
            "webhook_subscription": {
                "type": "webhook_subscription",
                "active": True,
                "description": "NexOps Webhook Integration",
                "delivery_method": {
                    "type": "http_delivery_method",
                    "url": webhook_url
                },
                "events": [
                    "incident.triggered",
                    "incident.acknowledged",
                    "incident.resolved"
                ],
                "filter": {
                    "type": "account_reference"
                }
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{cls.BASE_URL}/webhook_subscriptions",
                    headers=cls._get_headers(token),
                    json=payload,
                    timeout=15.0
                )
                logger.info(f"PagerDuty webhook creation status: {response.status_code}")
                if response.status_code in (200, 201):
                    data = response.json()
                    subscription = data.get("webhook_subscription", {})
                    logger.info(f"Successfully created PagerDuty webhook subscription (ID: {subscription.get('id')})")
                    return subscription
                else:
                    logger.error(f"Failed to create PagerDuty webhook subscription. Status: {response.status_code}, Response: {response.text}")
                    raise Exception(f"Failed to register PagerDuty webhook. Status code: {response.status_code}. Response: {response.text}")
        except Exception as e:
            logger.error(f"Error creating PagerDuty webhook subscription: {e}")
            raise

    @classmethod
    async def delete_webhook_subscription(cls, token: str, subscription_id: str) -> bool:
        """
        Delete a webhook subscription on PagerDuty. Best-effort deletion.
        """
        logger.info(f"Deleting PagerDuty webhook subscription (ID: {subscription_id})...")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{cls.BASE_URL}/webhook_subscriptions/{subscription_id}",
                    headers=cls._get_headers(token),
                    timeout=10.0
                )
                logger.info(f"PagerDuty webhook deletion response status: {response.status_code}")
                if response.status_code in (200, 204):
                    logger.info("Successfully deleted PagerDuty webhook subscription")
                    return True
                else:
                    logger.warning(f"PagerDuty webhook subscription deletion returned status {response.status_code}: {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Error deleting PagerDuty webhook subscription: {e}")
            return False


pagerduty_service = PagerDutyService()
