from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import List, Optional
from datetime import datetime

from app.core.database import get_session
from app.core.security import get_current_user
from app.models.cloud_provider import CloudProvider
from app.schemas.cloud_provider_schema import CloudProviderResponse, CloudProviderCreate
from app.core.cloud_validators import validate_cloud_provider
from app.core.crypto import encrypt_secret

router = APIRouter(prefix="/cloud-providers", tags=["Cloud Providers"])

@router.get("", response_model=List[CloudProviderResponse])
async def list_cloud_providers(
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """List all connected cloud hosting providers for a workspace."""
    query = select(CloudProvider).where(CloudProvider.workspace_id == workspace_id)
    result = await session.execute(query)
    return list(result.scalars().all())

@router.post("", response_model=CloudProviderResponse, status_code=201)
async def connect_cloud_provider(
    data: CloudProviderCreate,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """Connect a new cloud provider (Vercel, AWS, etc.) to the workspace."""
    # 1. Validate the token against the real provider API (use raw token here)
    is_valid = await validate_cloud_provider(data.type, data.access_token, data.secret_key)
    if not is_valid:
        raise HTTPException(
            status_code=400, 
            detail=f"Connection failed: The provided credentials for {data.type.upper()} are invalid or expired."
        )

    # 2. Encrypt sensitive fields before saving
    encrypted_data = data.model_dump()
    if encrypted_data.get('access_token'):
        encrypted_data['access_token'] = encrypt_secret(encrypted_data['access_token'])
    if encrypted_data.get('secret_key'):
        encrypted_data['secret_key'] = encrypt_secret(encrypted_data['secret_key'])

    # 3. Create the provider record
    provider = CloudProvider(**encrypted_data)
    provider.status = "active"
    provider.last_validated_at = datetime.utcnow()
    
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return provider

@router.delete("/{provider_id}", status_code=204)
async def disconnect_cloud_provider(
    provider_id: str,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """Disconnect a cloud provider."""
    provider = await session.get(CloudProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    await session.delete(provider)
    await session.commit()
    return None
