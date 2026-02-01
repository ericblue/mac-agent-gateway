"""FastAPI application entry point for Mac Agent Gateway."""

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from mag import __version__
from mag.config import Capabilities, get_capabilities, get_settings
from mag.routers import messages, reminders

# Access logger for HTTP requests (separate from app logger)
access_logger = logging.getLogger("mag.access")


def setup_logging(level: str = "INFO") -> None:
    """Configure logging with a consistent format and optional file output."""
    settings = get_settings()
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Always add stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter(log_format, date_format))
    stdout_handler.setLevel(log_level)
    root_logger.addHandler(stdout_handler)

    # Add file handlers if log_dir is configured
    if settings.log_dir:
        log_dir = Path(settings.log_dir).expanduser().resolve()
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        # Main application log
        app_log_path = log_dir / "mag.log"
        app_handler = RotatingFileHandler(
            app_log_path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
        )
        app_handler.setFormatter(logging.Formatter(log_format, date_format))
        app_handler.setLevel(log_level)
        root_logger.addHandler(app_handler)

        # Set secure permissions on log file
        if app_log_path.exists():
            os.chmod(app_log_path, 0o600)

        # Separate access log for HTTP requests
        if settings.log_access:
            access_log_path = log_dir / "access.log"
            access_handler = RotatingFileHandler(
                access_log_path,
                maxBytes=settings.log_max_bytes,
                backupCount=settings.log_backup_count,
            )
            access_format = "%(asctime)s %(message)s"
            access_handler.setFormatter(logging.Formatter(access_format, date_format))
            access_handler.setLevel(logging.INFO)
            access_logger.addHandler(access_handler)
            access_logger.setLevel(logging.INFO)

            # Set secure permissions on access log
            if access_log_path.exists():
                os.chmod(access_log_path, 0o600)


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Middleware to log HTTP requests for audit trail.
    
    Logs: timestamp, method, path, status code, duration, client IP.
    Does NOT log request/response bodies or sensitive headers.
    """

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if not settings.log_access:
            return await call_next(request)

        start_time = time.time()
        
        # Get client IP (consider X-Forwarded-For for proxied requests)
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        response = await call_next(request)

        duration_ms = (time.time() - start_time) * 1000

        # Log format: IP METHOD PATH STATUS DURATION_MS
        # Note: We don't log query params as they may contain sensitive data
        access_logger.info(
            '%s %s %s %d %.1fms',
            client_ip,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )

        return response


logger = logging.getLogger(__name__)

# Paths for static files and templates
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(
    title="Mac Agent Gateway",
    description="Local macOS HTTP API gateway for Apple Reminders and Messages",
    version=__version__,
    docs_url=None,  # Disable default, we'll serve custom
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Security: Rate limiting to prevent abuse
# Uses IP-based limiting; in production with proxies, configure X-Forwarded-For
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security: Access logging middleware for audit trail
app.add_middleware(AccessLogMiddleware)

# Security: Add CORS middleware with restrictive defaults
# Only allow localhost origins to prevent cross-origin attacks
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8123",
        "http://127.0.0.1:8123",
        "http://localhost:3000",  # Common dev server port
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)

app.include_router(reminders.router, prefix="/v1", tags=["reminders"])
app.include_router(messages.router, prefix="/v1", tags=["messages"])


# Placeholder values that should block startup
_BLOCKED_API_KEYS = {
    "your-secret-api-key-here",
    "your-secret-api-key",
    "your-api-key",
    "your-key",
    "changeme",
    "change-me",
    "secret",
    "password",
    "test-key",
    "demo-key",
    "example",
}


def _validate_api_key(api_key: str) -> tuple[list[str], list[str]]:
    """Validate API key security.
    
    Returns:
        (errors, warnings) - errors block startup, warnings are logged
    """
    errors = []
    warnings = []
    
    # Check for blocked placeholder values (critical - blocks startup)
    if api_key.lower() in _BLOCKED_API_KEYS:
        errors.append(f"API key is a blocked placeholder value: '{api_key}'")
    
    # Security: Block very short keys (minimum 16 characters required)
    min_required = 16
    if len(api_key) < min_required:
        errors.append(f"API key is too short ({len(api_key)} chars, minimum {min_required} required)")
    
    # Check recommended length (32 characters recommended)
    recommended_length = 32
    if len(api_key) >= min_required and len(api_key) < recommended_length:
        warnings.append(f"API key is short ({len(api_key)} chars, recommend {recommended_length}+)")
    
    # Check for sufficient complexity (mix of character types)
    has_upper = any(c.isupper() for c in api_key)
    has_lower = any(c.islower() for c in api_key)
    has_digit = any(c.isdigit() for c in api_key)
    char_types = sum([has_upper, has_lower, has_digit])
    if char_types < 2:
        warnings.append("API key lacks complexity (use mix of letters and numbers)")
    
    return errors, warnings


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize logging and log startup info."""
    settings = get_settings()
    setup_logging(settings.log_level)
    
    # Validate API key security
    errors, warnings = _validate_api_key(settings.api_key)
    
    if errors:
        logger.error("=" * 60)
        logger.error("API KEY SECURITY ERROR - CANNOT START")
        for error in errors:
            logger.error("  - %s", error)
        logger.error("")
        logger.error("To fix:")
        logger.error("  1. Generate a secure key: make generate-api-key")
        logger.error("  2. Update MAG_API_KEY in your .env file")
        logger.error("=" * 60)
        os._exit(1)  # Hard exit to avoid uvicorn traceback noise
    
    logger.info("Mac Agent Gateway v%s started", __version__)
    logger.info("Listening on %s:%d", settings.host, settings.port)

    # Log file logging status
    if settings.log_dir:
        log_dir = Path(settings.log_dir).expanduser().resolve()
        logger.info("Logging to directory: %s", log_dir)
        if settings.log_access:
            logger.info("Access logging enabled: %s/access.log", log_dir)
    
    if warnings:
        logger.warning("=" * 60)
        logger.warning("API KEY SECURITY WARNINGS:")
        for warning in warnings:
            logger.warning("  - %s", warning)
        logger.warning("Generate a secure key with: make generate-api-key")
        logger.warning("=" * 60)
    
    # Log capability status
    caps = get_capabilities()
    disabled = []
    if not caps.messages.send:
        disabled.append("messages.send")
    if not caps.messages.read:
        disabled.append("messages.read")
    if not caps.reminders.write:
        disabled.append("reminders.write")
    if disabled:
        logger.info("Disabled capabilities: %s", ", ".join(disabled))
    
    # Log send allowlist if configured
    if caps.messages.send_allowlist:
        logger.info("Send allowlist: %s", ", ".join(caps.messages.send_allowlist))
    
    # Log PII filter status
    if settings.pii_filter:
        logger.info("PII filter enabled: %s", settings.pii_filter)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    """Render the index page."""
    return templates.TemplateResponse("index.html", {"request": request, "version": __version__})


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html() -> HTMLResponse:
    """Serve Swagger UI with API key persistence via localStorage."""
    # Build custom Swagger UI HTML with persistAuthorization enabled
    swagger_ui_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mac Agent Gateway - API Docs</title>
        <link rel="stylesheet" type="text/css"
            href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
        <style>
            html { box-sizing: border-box; overflow-y: scroll; }
            *, *:before, *:after { box-sizing: inherit; }
            body { margin: 0; background: #fafafa; }
        </style>
    </head>
    <body>
        <div id="swagger-ui"></div>
        <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
        <script>
            window.onload = function() {
                window.ui = SwaggerUIBundle({
                    url: "/openapi.json",
                    dom_id: '#swagger-ui',
                    presets: [
                        SwaggerUIBundle.presets.apis,
                        SwaggerUIBundle.SwaggerUIStandalonePreset
                    ],
                    layout: "BaseLayout",
                    deepLinking: true,
                    persistAuthorization: false  // Security: Don't persist API key in localStorage
                });
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=swagger_ui_html)


@app.get("/health", tags=["system"])
async def health_check() -> dict:
    """Health check endpoint. No authentication required."""
    return {"status": "ok", "version": __version__}


@app.get("/v1/capabilities", response_model=Capabilities, tags=["system"])
async def get_capabilities_endpoint() -> Capabilities:
    """Get available capabilities.

    Returns what operations are enabled on this gateway.
    Use this to discover what actions are allowed before attempting them.
    
    Note: The send_allowlist is redacted for privacy. Authenticate to see full details.
    """
    caps = get_capabilities()
    # Redact send_allowlist for unauthenticated requests to prevent information disclosure
    # Return boolean indicator instead of actual phone numbers/emails
    caps.messages.send_allowlist_active = bool(caps.messages.send_allowlist)
    caps.messages.send_allowlist = None
    return caps


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler for unhandled errors.
    
    Security: We intentionally do NOT include exception details in the response
    to prevent information disclosure. Details are logged server-side only.
    """
    logger.exception(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


def run() -> None:
    """Run the application with uvicorn."""
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Starting Mac Agent Gateway v%s on %s:%d", __version__, settings.host, settings.port)
    uvicorn.run(
        "mag.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
