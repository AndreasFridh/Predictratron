from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    entity_id: str | None = Field(default=None, pattern=r"^[a-z_]+\.[a-z0-9_]+$")
    # mean: physical measurement; last: end-of-period reading;
    # change: interval increment of HA's reset-adjusted cumulative statistic.
    statistic: Literal["mean", "last", "change", "sum"] = "mean"
    label: str | None = Field(default=None, max_length=80)
    data_type: Literal["float", "int", "bool"] = "float"


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    source: Literal["ha", "csv", "demo"] = "ha"
    target: Signal
    inputs: list[Signal] = Field(default_factory=list, max_length=16)
    unit: str = Field(default="", max_length=20)
    resolution: Literal["minute", "hour", "day", "week", "custom"] = "hour"
    period_minutes: int = Field(default=60, ge=1, le=525600)
    horizon: int = Field(default=24, ge=1, le=72)
    timezone: str = "Europe/Stockholm"
    calendar: list[Literal["hour", "weekday", "week", "year_day"]] = Field(
        default_factory=lambda: ["hour", "weekday", "week", "year_day"]
    )
    lags: list[int] = Field(default_factory=lambda: [0, 1, 24, 168], max_length=20)
    windows: list[int] = Field(default_factory=lambda: [24, 72, 168], max_length=10)
    use_target_history: bool = True
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)
    auto_update: bool = False
    history_days: int = Field(default=180, ge=7, le=3650)
    retrain_days: int = Field(default=7, ge=1, le=90)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown time zone") from exc
        return value

    @field_validator("lags", "windows")
    @classmethod
    def valid_offsets(cls, values, info):
        lower = 0 if info.field_name == "lags" else 1
        if not values or any(v < lower or v > 8760 for v in values):
            raise ValueError(f"Enter at least one value between {lower} and 8760")
        return sorted(set(values))

    @model_validator(mode="after")
    def valid_signals(self):
        if self.target.data_type == "bool":
            raise ValueError("The ML box predicts numeric targets. Boolean signals are supported as inputs.")
        if self.target.data_type == "int" and any(value is not None and value != round(value) for value in (self.minimum, self.maximum)):
            raise ValueError("Integer output bounds must be whole numbers")
        keys = [s.key for s in self.signals]
        if len(keys) != len(set(keys)) or "timestamp" in keys:
            raise ValueError("Inputs and target need unique names; timestamp is reserved")
        if self.source == "ha" and any(not s.entity_id for s in self.signals):
            raise ValueError("All HA signals need an entity_id")
        if self.source == "ha" and any(s.statistic == "sum" for s in self.signals):
            raise ValueError("Sum applies to CSV interval values. Select meter increment for cumulative HA meters.")
        if self.source == "ha" and self.step_minutes % 5 and any(s.statistic == "change" for s in self.signals):
            raise ValueError("HA meter increments require intervals that are multiples of five minutes.")
        if not self.inputs and not self.calendar and not self.use_target_history:
            raise ValueError("Select inputs, calendar features or target history")
        if self.minimum is not None and self.maximum is not None and self.minimum >= self.maximum:
            raise ValueError("Minimum must be less than maximum")
        if self.source != "ha" and self.auto_update:
            raise ValueError("Automatic collection requires Home Assistant signals")
        return self

    def signature(self):
        """Only settings that affect learned values, not display names."""
        values = self.model_dump()
        values.pop("name")
        values["period_minutes"] = self.step_minutes
        for signal in [values["target"], *values["inputs"]]:
            signal.pop("label", None)
        values["inputs"] = sorted(values["inputs"], key=lambda signal: signal["key"])
        values["calendar"] = sorted(values["calendar"])
        return values

    @property
    def signals(self):
        return [self.target, *self.inputs]

    @property
    def freq(self):
        return f"{self.step_minutes}min"

    @property
    def step_minutes(self):
        return {"minute": 1, "hour": 60, "day": 1440, "week": 10080}.get(self.resolution, self.period_minutes)

    @property
    def step_hours(self):
        return self.step_minutes / 60

    @property
    def anchor(self):
        # Weekly periods end on Monday 00:00 UTC. Other fixed periods use epoch.
        return pd.Timestamp("1970-01-05" if self.step_minutes % 10080 == 0 else "1970-01-01", tz="UTC")

    def floor(self, stamps):
        step = pd.Timedelta(self.freq)
        return self.anchor + ((stamps - self.anchor) // step) * step

    @property
    def warmup(self):
        if not self.inputs and not self.use_target_history:
            return 0
        return max([*self.lags, *self.windows])
