from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.container import Container
from src.application.use_cases.auth_use_case import AuthenticationError, AuthUseCase
from src.infrastructure.repositories.auth_repository import DuplicateEmailError
from src.presentation.dto.auth import CreateStaffRequest, LoginRequest, RefreshRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth")
bearer_scheme = HTTPBearer(auto_error=False)


@inject
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_use_case: AuthUseCase = Depends(Provide[Container.auth_use_case]),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        return await auth_use_case.authenticate_access_token(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def require_role(*allowed_roles: str):
    async def role_dependency(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user
    return role_dependency


@router.post("/guest", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
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
    try:
        user = await auth_use_case.create_staff(
            request.email, request.display_name, request.password, current_admin
        )
        return UserResponse(**user)
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/login", response_model=TokenResponse)
@inject
async def login(
    request: LoginRequest,
    auth_use_case: AuthUseCase = Depends(Provide[Container.auth_use_case]),
) -> TokenResponse:
    try:
        return TokenResponse(**await auth_use_case.login(request.email, request.password))
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/refresh", response_model=TokenResponse)
@inject
async def refresh(
    request: RefreshRequest,
    auth_use_case: AuthUseCase = Depends(Provide[Container.auth_use_case]),
) -> TokenResponse:
    try:
        return TokenResponse(**await auth_use_case.refresh(request.refresh_token))
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


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
