from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, AliasChoices


class BaseDataModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    timestamp: datetime = Field(validation_alias=AliasChoices("timestamp", "E", "T", "t"))

    @field_validator("timestamp", mode="before")
    @classmethod
    def coerce_to_utc_datetime(cls, v: Any) -> datetime:
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc)
        
        if isinstance(v, (int, float)):
            # Distinguish between seconds and milliseconds
            # A timestamp in ms for year 2000 is 946_684_800_000
            if v > 1e11:
                return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(v, tz=timezone.utc)
            
        if isinstance(v, str):
            try:
                # Try fromtimestamp if it's a numeric string
                float_v = float(v)
                if float_v > 1e11:
                    return datetime.fromtimestamp(float_v / 1000.0, tz=timezone.utc)
                return datetime.fromtimestamp(float_v, tz=timezone.utc)
            except ValueError:
                # Isoformat
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
                
        raise ValueError(f"Cannot parse timestamp from {v}")
