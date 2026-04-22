"""
Automation Rule Routes
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from sqlmodel import select
from datetime import datetime

from app.core.database import get_session
from app.models.rule import Rule
from app.schemas.rule_schema import RuleCreate, RuleUpdate, RuleResponse

router = APIRouter(prefix="/rules", tags=["Automation Rules"])


@router.get("", response_model=List[RuleResponse])
async def list_rules(
    is_active: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List all automation rules."""
    query = select(Rule)
    if is_active is not None:
        query = query.where(Rule.is_active == is_active)
    query = query.order_by(Rule.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


@router.post("", response_model=RuleResponse, status_code=201)
async def create_rule(
    data: RuleCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new automation rule."""
    rule = Rule(
        name=data.name,
        description=data.description,
        condition_type=data.condition_type,
        condition_config=data.condition_config,
        action_type=data.action_type,
        action_config=data.action_config,
        is_active=data.is_active,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: str,
    data: RuleUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update a rule's configuration or toggle its state."""
    rule = await session.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(rule, key, value)

    rule.updated_at = datetime.utcnow()
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete an automation rule."""
    rule = await session.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await session.delete(rule)
    await session.commit()
