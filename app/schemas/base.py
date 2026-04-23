"""
Base Schema
Provides automated camelCase alias generation for all Pydantic schemas.
"""

from pydantic import BaseModel, ConfigDict


def to_camel(string: str) -> str:
    """Convert snake_case to camelCase."""
    words = string.split("_")
    return words[0] + "".join(word.capitalize() for word in words[1:])


class BaseSchema(BaseModel):
    """
    Base schema that automatically converts snake_case fields to camelCase
    when exporting to JSON, while allowing population by either name.
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
