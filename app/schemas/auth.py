from pydantic import BaseModel, EmailStr, field_validator


class OTPRequest(BaseModel):
    email: EmailStr
    name: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v):
        return v.strip() if v else v


class OTPVerify(BaseModel):
    email: EmailStr
    otp: str

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, v):
        v = v.strip()
        if not v.isdigit() or len(v) != 6:
            raise ValueError("OTP must be a 6-digit number")
        return v


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    name: str


class RefreshRequest(BaseModel):
    refresh_token: str


class GoogleAuthRequest(BaseModel):
    id_token: str
