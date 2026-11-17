from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.container import Container
from src.modules.auth.application.use_cases.auth_use_case import AuthUseCase
from src.modules.auth.domain.errors import AuthenticationError
from src.modules.auth.presentation.dto.auth import CreateStaffRequest, LoginRequest, RefreshRequest, TokenResponse, UserResponse
from src.common.errors import (
    PermissionDeniedError,
    UnauthorizedError,
)
from src.common.presentation.rate_limit import enforce_rate_limit, rate_limit

router = APIRouter(prefix="/auth")
bearer_scheme = HTTPBearer(auto_error=False)


@inject
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_use_case: AuthUseCase = Depends(Provide[Container.auth_use_case]),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()
    return await auth_use_case.authenticate_access_token(credentials.credentials)


def require_role(*allowed_roles: str):
    async def role_dependency(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in allowed_roles:
            raise PermissionDeniedError()
        return current_user
    return role_dependency


@router.post(
    "/guest",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("guest_ip", default_limit=10))],
)
@inject
async def guest_session(
    auth_use_case: AuthUseCase = Depends(Provide[Container.auth_use_case]),
) -> TokenResponse:
    return TokenResponse(**await auth_use_case.create_guest_session())


@router.post("/staff", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@inject
async def create_staff(
    request: CreateStaffRequest,
    current_admin: dict = Depends(require_role("admin")),
    auth_use_case: AuthUseCase = Depends(Provide[Container.auth_use_case]),
) -> UserResponse:
    user = await auth_use_case.create_staff(
        request.email, request.display_name, request.password, current_admin
    )
    return UserResponse(**user)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("login_ip", default_limit=10))],
)
@inject
async def login(
    request: LoginRequest,
    http_request: Request,
    auth_use_case: AuthUseCase = Depends(Provide[Container.auth_use_case]),
) -> TokenResponse:
    # Per-account limit slows credential stuffing that rotates IP addresses.
    await enforce_rate_limit(
        http_request, "login_email", default_limit=5,
        key=request.email.strip().lower(), hash_key=True,
    )
    return TokenResponse(**await auth_use_case.login(request.email, request.password))


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("refresh_ip", default_limit=30))],
)
@inject
async def refresh(
    request: RefreshRequest,
    auth_use_case: AuthUseCase = Depends(Provide[Container.auth_use_case]),
) -> TokenResponse:
    return TokenResponse(**await auth_use_case.refresh(request.refresh_token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def logout(
    request: RefreshRequest,
    auth_use_case: AuthUseCase = Depends(Provide[Container.auth_use_case]),
) -> None:
    try:
        await auth_use_case.logout(request.refresh_token)
    except AuthenticationError:
        # Logout is idempotent and must not reveal token validity.
        return None


@router.get("/me", response_model=UserResponse)
async def me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    return UserResponse(**current_user)
