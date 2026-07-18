from pydantic import BaseModel, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    workspace_name: str | None = Field(default=None, min_length=2, max_length=120)

    @field_validator("workspace_name", mode="before")
    @classmethod
    def blank_workspace_is_optional(cls, value):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
