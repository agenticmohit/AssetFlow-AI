from fastapi import APIRouter, Depends, Response, status

from assetflow.api.dependencies import Config, get_auth_service
from assetflow.schemas.auth import LoginRequest, SignupRequest, TokenResponse
from assetflow.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])


def set_session(response: Response, token: str, settings: Config) -> None:
    response.set_cookie(
        "assetflow_session",
        token,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        max_age=settings.access_token_ttl_minutes * 60,
        path="/",
    )


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(
    data: SignupRequest,
    response: Response,
    settings: Config,
    service: AuthService = Depends(get_auth_service),
):
    _, token = service.signup(data)
    set_session(response, token, settings)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    response: Response,
    settings: Config,
    service: AuthService = Depends(get_auth_service),
):
    _, token = service.login(data.email, data.password)
    set_session(response, token, settings)
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie("assetflow_session")
