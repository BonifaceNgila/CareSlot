from datetime import datetime
from pydantic import BaseModel, Field, field_validator

class Booking(BaseModel):
    doctor_id: int = Field(gt=0)
    patient_id: int = Field(gt=0)
    starts_at: datetime

class Reschedule(BaseModel):
    starts_at: datetime

class Cancellation(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("A cancellation reason is required")
        return value
