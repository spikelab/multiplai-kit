# Authentication Best Practices

Patterns for user authentication, session management, and security in Python/FastAPI applications.

---

## Authentication Approaches

### When to Use What

| Approach | Best For | Complexity |
|----------|----------|------------|
| Session-based | Traditional web apps, SSR, simple setups | Low |
| JWT | APIs, SPAs, mobile apps, microservices | Medium |
| OAuth/OIDC | "Login with Google", enterprise SSO | High |
| API Keys | Service-to-service, developer APIs | Low |

### Decision Flow

1. **Single server, traditional web app?** → Sessions
2. **API consumed by SPA or mobile?** → JWT
3. **Need third-party login?** → OAuth + JWT
4. **Service-to-service?** → API Keys or mutual TLS

---

## Password Handling

**Never store plaintext passwords.** Use bcrypt or argon2.

### Setup

```bash
uv add passlib[bcrypt]
# or for argon2 (more secure, slower)
uv add argon2-cffi
```

### Password Utilities

```python
# src/myapp/core/security.py
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)
```

### Password Validation

```python
# src/myapp/schemas/user.py
from pydantic import BaseModel, field_validator
import re

class UserCreate(BaseModel):
    email: str
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain a digit")
        return v
```

---

## Session-Based Authentication

Simple, stateful authentication using server-side sessions.

### Setup with Starlette Sessions

```bash
uv add itsdangerous
```

```python
# src/myapp/main.py
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=3600 * 24 * 7,  # 1 week
)
```

### Session Auth Flow

```python
# src/myapp/features/auth/router.py
from fastapi import APIRouter, Request, HTTPException
from myapp.core.security import verify_password
from myapp.repositories.user import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login")
async def login(
    request: Request,
    credentials: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    repo = UserRepository(db)
    user = await repo.get_by_email(credentials.email)

    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account disabled")

    # Store user ID in session
    request.session["user_id"] = user.id
    return {"message": "Logged in"}

@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out"}
```

### Session-Based Dependency

```python
# src/myapp/api/deps.py
from fastapi import Depends, HTTPException, Request

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    repo = UserRepository(db)
    user = await repo.get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user

async def get_current_active_user(
    user: User = Depends(get_current_user),
) -> User:
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive user")
    return user
```

---

## JWT Authentication

Stateless authentication using JSON Web Tokens.

### Setup

```bash
uv add pyjwt
```

### JWT Utilities

```python
# src/myapp/core/security.py
from datetime import datetime, timedelta, timezone
import jwt
from myapp.config import settings

ALGORITHM = "HS256"

def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)

def create_refresh_token(data: dict) -> str:
    """Create a JWT refresh token (longer lived)."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=7)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise InvalidTokenError("Token has expired")
    except jwt.InvalidTokenError:
        raise InvalidTokenError("Invalid token")
```

### JWT Auth Endpoints

```python
# src/myapp/features/auth/router.py
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordRequestForm

from myapp.core.security import (
    verify_password,
    create_access_token,
    create_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/token")
async def login_for_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """OAuth2 compatible token endpoint."""
    repo = UserRepository(db)
    user = await repo.get_by_email(form_data.username)

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }

@router.post("/refresh")
async def refresh_token(
    refresh_token: str,
    db: AsyncSession = Depends(get_db),
):
    """Get new access token using refresh token."""
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        user_id = payload.get("sub")
        access_token = create_access_token(data={"sub": user_id})
        return {"access_token": access_token, "token_type": "bearer"}

    except InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=str(e))
```

### JWT Dependency

```python
# src/myapp/api/deps.py
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from myapp.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT and return current user."""
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

    except InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=str(e))

    repo = UserRepository(db)
    user = await repo.get(int(user_id))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user
```

---

## User Model

```python
# src/myapp/models/user.py
from datetime import datetime
from enum import Enum
from sqlalchemy import String, Enum as SQLEnum, func
from sqlalchemy.orm import Mapped, mapped_column

from myapp.database import Base

class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole),
        default=UserRole.USER,
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    is_verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login: Mapped[datetime | None] = mapped_column(default=None)
```

### User Schemas

```python
# src/myapp/schemas/user.py
from datetime import datetime
from pydantic import BaseModel, EmailStr

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str | None
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

class UserUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
```

---

## Role-Based Access Control

### Permission Dependencies

```python
# src/myapp/api/deps.py
from functools import wraps
from fastapi import HTTPException

def require_role(*allowed_roles: UserRole):
    """Dependency factory for role-based access."""
    async def role_checker(
        user: User = Depends(get_current_active_user),
    ) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail="Insufficient permissions",
            )
        return user
    return role_checker

# Usage
@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only endpoint."""
    repo = UserRepository(db)
    user = await repo.get(user_id)
    if user:
        await repo.delete(user)
    return {"message": "User deleted"}
```

### Permission Enum Pattern

```python
# More granular permissions
from enum import Flag, auto

class Permission(Flag):
    READ = auto()
    WRITE = auto()
    DELETE = auto()
    ADMIN = READ | WRITE | DELETE

ROLE_PERMISSIONS = {
    UserRole.USER: Permission.READ,
    UserRole.ADMIN: Permission.ADMIN,
}

def require_permission(permission: Permission):
    async def permission_checker(
        user: User = Depends(get_current_active_user),
    ) -> User:
        user_perms = ROLE_PERMISSIONS.get(user.role, Permission(0))
        if not (user_perms & permission):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return permission_checker
```

---

## OAuth2 / Social Login

For "Login with Google/GitHub/etc."

### Setup with Authlib

```bash
uv add authlib httpx
```

### OAuth Configuration

```python
# src/myapp/core/oauth.py
from authlib.integrations.starlette_client import OAuth
from myapp.config import settings

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

oauth.register(
    name="github",
    client_id=settings.github_client_id,
    client_secret=settings.github_client_secret,
    authorize_url="https://github.com/login/oauth/authorize",
    access_token_url="https://github.com/login/oauth/access_token",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "user:email"},
)
```

### OAuth Routes

```python
# src/myapp/features/auth/oauth_router.py
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from myapp.core.oauth import oauth

router = APIRouter(prefix="/auth", tags=["oauth"])

@router.get("/login/{provider}")
async def oauth_login(request: Request, provider: str):
    """Redirect to OAuth provider."""
    client = oauth.create_client(provider)
    redirect_uri = request.url_for("oauth_callback", provider=provider)
    return await client.authorize_redirect(request, redirect_uri)

@router.get("/callback/{provider}")
async def oauth_callback(
    request: Request,
    provider: str,
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth callback."""
    client = oauth.create_client(provider)
    token = await client.authorize_access_token(request)

    if provider == "google":
        user_info = token.get("userinfo")
    elif provider == "github":
        resp = await client.get("user", token=token)
        user_info = resp.json()

    # Find or create user
    repo = UserRepository(db)
    user = await repo.get_by_email(user_info["email"])

    if not user:
        user = await repo.create(User(
            email=user_info["email"],
            full_name=user_info.get("name"),
            is_verified=True,  # OAuth emails are verified
            hashed_password="",  # No password for OAuth users
        ))

    # Create JWT tokens
    access_token = create_access_token(data={"sub": str(user.id)})

    # Redirect to frontend with token
    return RedirectResponse(
        url=f"{settings.frontend_url}/auth/callback?token={access_token}"
    )
```

---

## API Key Authentication

For service-to-service or developer APIs.

### API Key Model

```python
# src/myapp/models/api_key.py
import secrets
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(default=None)

    user: Mapped["User"] = relationship()

    @staticmethod
    def generate_key() -> tuple[str, str]:
        """Generate a new API key. Returns (raw_key, key_hash)."""
        raw_key = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        return raw_key, key_hash
```

### API Key Dependency

```python
# src/myapp/api/deps.py
from fastapi import Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key_user(
    api_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Authenticate via API key."""
    if not api_key:
        return None

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    result = await db.execute(
        select(APIKey)
        .where(APIKey.key_hash == key_hash, APIKey.is_active == True)
    )
    api_key_obj = result.scalar_one_or_none()

    if not api_key_obj:
        return None

    # Update last used
    api_key_obj.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return api_key_obj.user

async def get_current_user_or_api_key(
    token_user: User | None = Depends(get_current_user_optional),
    api_key_user: User | None = Depends(get_api_key_user),
) -> User:
    """Accept either JWT or API key authentication."""
    user = token_user or api_key_user
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
```

---

## Frontend Integration

### Token Storage (React)

```typescript
// src/lib/auth.ts

// Store tokens securely
export const setTokens = (access: string, refresh: string) => {
  // Access token: memory only (safest) or sessionStorage
  sessionStorage.setItem("access_token", access);
  // Refresh token: httpOnly cookie preferred, or localStorage
  localStorage.setItem("refresh_token", refresh);
};

export const getAccessToken = (): string | null => {
  return sessionStorage.getItem("access_token");
};

export const clearTokens = () => {
  sessionStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
};
```

### Auth Context

```typescript
// src/features/auth/AuthContext.tsx
import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { api } from "@/lib/api";

type User = {
  id: number;
  email: string;
  fullName: string | null;
  role: string;
};

type AuthContextType = {
  user: User | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Check for existing session on mount
    const token = getAccessToken();
    if (token) {
      api.get("/users/me")
        .then((res) => setUser(res.data))
        .catch(() => clearTokens())
        .finally(() => setIsLoading(false));
    } else {
      setIsLoading(false);
    }
  }, []);

  const login = async (email: string, password: string) => {
    const res = await api.post("/auth/token", { username: email, password });
    setTokens(res.data.access_token, res.data.refresh_token);
    const userRes = await api.get("/users/me");
    setUser(userRes.data);
  };

  const logout = () => {
    clearTokens();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
};
```

### Protected Routes

```typescript
// src/components/ProtectedRoute.tsx
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/features/auth/AuthContext";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <div>Loading...</div>;
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
}
```

---

## Security Checklist

### Must Have

- [ ] Hash passwords with bcrypt/argon2
- [ ] Use HTTPS in production
- [ ] Validate and sanitize all inputs
- [ ] Set secure cookie flags (`httpOnly`, `secure`, `sameSite`)
- [ ] Implement rate limiting on auth endpoints
- [ ] Use parameterized queries (SQLAlchemy does this)
- [ ] Keep dependencies updated

### Should Have

- [ ] Implement account lockout after failed attempts
- [ ] Add email verification for new accounts
- [ ] Support password reset flow
- [ ] Log authentication events
- [ ] Implement CSRF protection for session auth
- [ ] Use short-lived access tokens (15-60 min)

### Nice to Have

- [ ] Two-factor authentication (TOTP)
- [ ] Passwordless login options
- [ ] Session management (view/revoke sessions)
- [ ] Audit logging for sensitive operations

---

## Quick Reference

### Dependencies

```bash
# Password hashing
uv add passlib[bcrypt]

# JWT
uv add pyjwt

# OAuth
uv add authlib httpx

# Sessions
uv add itsdangerous
```

### Common Imports

```python
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm, APIKeyHeader
from passlib.context import CryptContext
import jwt
```
