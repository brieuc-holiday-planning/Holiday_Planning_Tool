from .base import *  # noqa: F401,F403

DEBUG = False
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

if not SECRET_KEY or SECRET_KEY.startswith("django-insecure"):  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be set to a real secret in production.")

# WhiteNoise (see base MIDDLEWARE) serves STATIC_ROOT; this adds gzip/brotli
# copies and content-hashed filenames at collectstatic time so responses can
# be cached hard.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Standard hardening. Each is env-overridable so the prod settings can still
# be exercised locally over plain HTTP (see `./app.sh prod`), but every
# default here is the safe one.
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SESSION_COOKIE_SECURE = env.bool("DJANGO_SECURE_COOKIES", default=True)  # noqa: F405
CSRF_COOKIE_SECURE = env.bool("DJANGO_SECURE_COOKIES", default=True)  # noqa: F405
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=31536000)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Behind a TLS-terminating proxy (Heroku/Render/nginx), this is how Django
# knows the original request was HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Must list the site's real origin(s), e.g. https://holidays.example.com,
# or POSTs will fail CSRF verification behind a proxy.
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405
