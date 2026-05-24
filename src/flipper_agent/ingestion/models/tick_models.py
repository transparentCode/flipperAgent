from typing import Literal, Any
from pydantic import Field, AliasChoices, model_validator
from .base_models import BaseDataModel


class OHLCVRecord(BaseDataModel):
    symbol: str = Field(validation_alias=AliasChoices("symbol", "s", "sym"))
    open: float = Field(gt=0, validation_alias=AliasChoices("open", "o"))
    high: float = Field(gt=0, validation_alias=AliasChoices("high", "h"))
    low: float = Field(gt=0, validation_alias=AliasChoices("low", "l"))
    close: float = Field(gt=0, validation_alias=AliasChoices("close", "c"))
    volume: float = Field(ge=0, validation_alias=AliasChoices("volume", "v", "vol"))

    @model_validator(mode="after")
    def check_high_low(self) -> "OHLCVRecord":
        if self.high < self.low:
            raise ValueError("High must be greater than or equal to Low")
        return self


class TickRecord(BaseDataModel):
    symbol: str = Field(validation_alias=AliasChoices("symbol", "s", "sym"))
    price: float = Field(gt=0, validation_alias=AliasChoices("price", "p", "c"))
    size: float = Field(gt=0, validation_alias=AliasChoices("size", "volume", "v", "q"))
    side: Literal['buy', 'sell', 'unknown'] = Field(default='unknown')

    @model_validator(mode="before")
    @classmethod
    def map_side(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Binance uses 'm' boolean for is_buyer_maker
            if "m" in data:
                data["side"] = "sell" if data["m"] else "buy"
            # Some feeds might provide 'S' or 'side' directly
            side_val = data.get("side") or data.get("S")
            if side_val:
                if isinstance(side_val, str):
                    if side_val.lower() in ["buy", "1", "b"]:
                        data["side"] = "buy"
                    elif side_val.lower() in ["sell", "-1", "s"]:
                        data["side"] = "sell"
        return data


class OIRecord(BaseDataModel):
    symbol: str = Field(validation_alias=AliasChoices("symbol", "s", "sym"))
    open_interest: float = Field(ge=0, validation_alias=AliasChoices("open_interest", "openInterest", "oi"))
