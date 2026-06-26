"""
Cloud Provider Model
Tracks external hosting and infrastructure connections (AWS, Vercel, etc.)
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, JSON, Column
from app.core.crypto import decrypt_secret


class CloudProvider(SQLModel, table=True):
    __tablename__ = "cloud_providers"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    workspace_id: str = Field(index=True)
    
    name: str = Field(max_length=100) # User-defined name (e.g. "Main Vercel Account")
    type: str = Field(index=True) # vercel | aws | netlify | render | railway
    
    # Credentials (should be encrypted in production, stored as masked strings for now)
    access_token: Optional[str] = Field(default=None)
    secret_key: Optional[str] = Field(default=None)
    account_id: Optional[str] = Field(default=None)
    
    # Configuration / Metadata
    config: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    
    status: str = Field(default="active") # active | disconnected | error
    last_validated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def decrypted_access_token(self) -> Optional[str]:
        return decrypt_secret(self.access_token) if self.access_token else None

    @property
    def decrypted_secret_key(self) -> Optional[str]:
        return decrypt_secret(self.secret_key) if self.secret_key else None
