import multiprocessing
import os

# 绑定
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Worker
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.environ.get("GUNICORN_WORKERS", min(multiprocessing.cpu_count() * 2 + 1, 8)))
threads = 2

# 超时
timeout = 60
graceful_timeout = 30
keepalive = 5

# 日志
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sμs'

# 进程
daemon = False
pidfile = None
user = None
group = None
