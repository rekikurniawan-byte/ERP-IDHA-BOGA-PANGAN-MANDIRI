import os

from app import create_app


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


app = create_app()


if __name__ == "__main__":
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "5000"))
    debug = _env_bool("APP_DEBUG", _env_bool("FLASK_DEBUG", False))
    app.run(host=host, port=port, debug=debug)
