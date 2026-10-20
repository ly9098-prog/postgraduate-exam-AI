"""Fresh-interpreter cloud profile probes with synthetic configuration only."""


VALID_CLOUD_PROBE = """
import os
import sys

# Must be set before any imports
os.environ["APP_ENV"] = "production"
os.environ["DEPLOYMENT_PROFILE"] = "cloud_api"
os.environ["PROCESS_ROLE"] = "worker"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@localhost:5432/db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["APP_SECRET"] = "a" * 32
os.environ["CORS_ORIGINS"] = '["https://example.com"]'
os.environ["ALLOWED_HOSTS"] = '["example.com"]'
os.environ["PUBLIC_BASE_URL"] = "https://example.com"
os.environ["WECHAT_APP_ID"] = "wx-test-app-id"
os.environ["WECHAT_APP_SECRET"] = "wx-test-app-secret"
os.environ["STAGING_STORAGE_DIR"] = os.environ["ISOLATION_TEST_ROOT"]
os.environ["WORKER_SCRATCH_DIR"] = os.path.join(os.environ["ISOLATION_TEST_ROOT"], "scratch")
# Cloud OCR config
os.environ["OCR_ENABLED"] = "true"
os.environ["OCR_USE_GPU"] = "false"
os.environ["OCR_EXECUTION_BACKEND"] = "paddlex_http"
os.environ["OCR_REMOTE_URL"] = "https://ocr.example.com/api"
os.environ["OCR_REMOTE_TOKEN"] = "test-token-123"
os.environ["VECTOR_ENABLED"] = "false"

# Cloud-appropriate PDF settings (must pass production validator)
os.environ["PDF_RENDER_PAGE_WINDOW"] = "1"
os.environ["PDF_MAX_RENDER_PAGES_CONCURRENT"] = "1"
os.environ["PDF_MAX_PAGES"] = "30"
os.environ["PDF_MAX_FILE_SIZE_BYTES"] = str(5 * 1024 * 1024)

# Wipe any cached modules from parent process
for mod in list(sys.modules.keys()):
    if "paddle" in mod or "ocr" in mod:
        del sys.modules[mod]

# Now import app core
from app.core.config import settings
from app.core.deployment_profile import detect_deployment_profile, DeploymentProfile
from app.services.production_config_validator import validate_production_config

# Verify profile
profile = detect_deployment_profile()
assert profile == DeploymentProfile.CLOUD_API, f"Expected CLOUD_API, got {profile}"

# Sync validation must pass for valid cloud config
validate_production_config()

# Check no paddle/paddleocr modules loaded
banned = [m for m in sys.modules if m.startswith(("paddle", "paddleocr"))]
if banned:
    print(f"BANNED_MODULES_LOADED: {banned}", file=sys.stderr)
    sys.exit(1)

print("SUCCESS: No local OCR modules loaded in cloud_api subprocess")
sys.exit(0)
"""


INVALID_LOCAL_BACKEND_PROBE = """
import os, sys
os.environ["APP_ENV"] = "production"
os.environ["DEPLOYMENT_PROFILE"] = "cloud_api"
os.environ["PROCESS_ROLE"] = "worker"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@localhost:5432/db"
os.environ["APP_SECRET"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
os.environ["CORS_ORIGINS"] = '["https://example.com"]'
os.environ["ALLOWED_HOSTS"] = '["example.com"]'
os.environ["PUBLIC_BASE_URL"] = "https://example.com"
os.environ["WECHAT_APP_ID"] = "wx-test-app-id"
os.environ["WECHAT_APP_SECRET"] = "wx-test-app-secret"
os.environ["STAGING_STORAGE_DIR"] = os.environ["ISOLATION_TEST_ROOT"]
os.environ["VECTOR_ENABLED"] = "false"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["OCR_ENABLED"] = "true"
os.environ["OCR_USE_GPU"] = "true"  # must be rejected
os.environ["OCR_EXECUTION_BACKEND"] = "local_process"  # must be rejected
os.environ["OCR_REMOTE_URL"] = "https://ocr.example.com/api"
os.environ["OCR_REMOTE_TOKEN"] = "test-token-123"
for mod in list(sys.modules.keys()):
    if "paddle" in mod or "ocr" in mod:
        del sys.modules[mod]
try:
    from app.services.production_config_validator import validate_production_config
    validate_production_config()
    print("VALIDATION_PASSED_UNEXPECTEDLY")
    sys.exit(2)
except SystemError as e:
    error_text = str(e)
    if "GPU" in error_text and "local_process" in error_text:
        print("CORRECTLY_REJECTED")
        sys.exit(0)
    else:
        print(f"UNEXPECTED_ERROR: {error_text}")
        sys.exit(3)
"""


HTTP_IMPORT_PROBE = VALID_CLOUD_PROBE.replace(
    'os.environ["PROCESS_ROLE"] = "worker"',
    'os.environ["PROCESS_ROLE"] = "web"',
).replace(
    "validate_production_config()\n",
    "validate_production_config()\n"
    "from app import main\n"
    "assert main._production_mode is True\n"
    "assert main.settings.PROCESS_ROLE == 'web'\n"
    "assert main.app.openapi()['paths']\n"
    "print('HTTP_IMPORT_OK')\n",
)


LOCAL_IMPORT_PROBE = """
import os, sys
os.environ["APP_ENV"] = "development"
os.environ["DEPLOYMENT_PROFILE"] = "local_import"
os.environ["PROCESS_ROLE"] = "all"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test_isolation.db"
os.environ["APP_SECRET"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
os.environ["CORS_ORIGINS"] = '["https://example.com"]'
os.environ["STAGING_STORAGE_DIR"] = os.environ["ISOLATION_TEST_ROOT"]
os.environ["VECTOR_ENABLED"] = "false"
os.environ["OCR_ENABLED"] = "true"
os.environ["OCR_USE_GPU"] = "false"
os.environ["OCR_EXECUTION_BACKEND"] = "local_process"
os.environ["REDIS_URL"] = ""
for mod in list(sys.modules.keys()):
    if "paddle" in mod or "ocr" in mod:
        del sys.modules[mod]
from app.core.deployment_profile import detect_deployment_profile, DeploymentProfile
profile = detect_deployment_profile()
assert profile == DeploymentProfile.LOCAL_IMPORT, f"Expected LOCAL_IMPORT, got {profile}"
# local_import should validate without error for local_process backend
from app.services.production_config_validator import validate_production_config
validate_production_config()
print("LOCAL_IMPORT_OK")
sys.exit(0)
"""
