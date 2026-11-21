from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class ClaimInput(Input):
    code: str = Field(min_length=2, max_length=50)
    hive_ids: list[int] = Field(min_length=1, max_length=200)
    note: str = Field(default='', max_length=300)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator('code')
    @classmethod
    def code_required(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('批次编号不能为空')
        return value


class ReadingInput(Input):
    hive_id: int
    weight_kg: float | None = Field(default=None, gt=0, le=100)
    temperature: float | None = Field(default=None, ge=-10, le=50)
    activity: float | None = Field(default=None, ge=0, le=500)
    feed_left: float | None = Field(default=None, ge=0, le=20)
    queen_seen: bool | None = None
    colony_frames: int | None = Field(default=None, ge=0, le=20)
    note: str = Field(default='', max_length=300)
    client_reading_id: str | None = Field(default=None, min_length=8, max_length=64)
    correct_reading_id: int | None = None


class ReceiveInput(Input):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=64)


class SealInput(Input):
    reason: str = Field(min_length=5, max_length=400)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator('reason')
    @classmethod
    def reason_required(cls, value):
        value = value.strip()
        if len(value) < 5:
            raise ValueError('封存依据至少5字')
        return value


class CancelInput(Input):
    reason: str = Field(min_length=5, max_length=400)

    @field_validator('reason')
    @classmethod
    def reason_required(cls, value):
        value = value.strip()
        if len(value) < 5:
            raise ValueError('取消依据至少5字')
        return value
