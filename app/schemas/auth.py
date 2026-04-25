from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)  # email or username
    password: str = Field(min_length=8, max_length=72)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10)
    new_password: str = Field(min_length=8, max_length=72)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    id: int
    username: str | None = None
    full_name: str
    email: str
    role: str
    bio: str | None = None
    batch_year: int | None = None
    avatar_base64: str | None = None
    banner_base64: str | None = None

    model_config = {"from_attributes": True}


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminOtpRequest(BaseModel):
    email: EmailStr
    otp: str


class UpdateProfileRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    username: str | None = Field(default=None, min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9_]+$")
    bio: str | None = Field(default=None, max_length=500)
    avatar_base64: str | None = Field(default=None, max_length=300000)
    banner_base64: str | None = Field(default=None, max_length=450000)


class UsernameCheckRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9_]+$")


class SendOtpRequest(BaseModel):
    email: EmailStr
    purpose: str = Field(default="verify", pattern=r"^(verify|reset|admin)$")


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6)


class ResetPasswordWithOtpRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=72)
