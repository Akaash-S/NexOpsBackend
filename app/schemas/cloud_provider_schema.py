from typing import Optional, Dict, Any
from datetime import datetime
from .base import BaseSchema

class CloudProviderBase(BaseSchema):
    name: str
    type: str
    workspace_id: str
    status: str = "active"
    config: Dict[str, Any] = {}

class CloudProviderCreate(CloudProviderBase):
    access_token: Optional[str] = None
    secret_key: Optional[str] = None
    account_id: Optional[str] = None

class CloudProviderResponse(CloudProviderBase):
    id: str
    last_validated_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
