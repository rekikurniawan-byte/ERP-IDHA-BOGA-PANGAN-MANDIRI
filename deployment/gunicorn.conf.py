# Gunicorn config example for PT Idha Boga Pangan Mandiri production.
# Run from project root after setting .env.production environment variables.

bind = "127.0.0.1:8000"
workers = 2
threads = 2
timeout = 120
graceful_timeout = 30
keepalive = 5
worker_class = "gthread"
wsgi_app = "run:app"
accesslog = "/var/log/idha-boga/gunicorn-access.log"
errorlog = "/var/log/idha-boga/gunicorn-error.log"
loglevel = "info"
capture_output = True
proc_name = "idha-boga"
