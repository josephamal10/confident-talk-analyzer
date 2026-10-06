"""Production server settings, used by the Docker image: gunicorn --config gunicorn.conf.py app:app"""
import logging
import os

bind = f"0.0.0.0:{os.getenv('PORT', '7860')}"
# One worker, so the speech models are loaded once; threads serve requests side by side. An analysis
# streams its progress, holding a thread for its whole run, hence the long timeout.
workers = 1
threads = 8
timeout = 600
accesslog = "-"


def post_worker_init(_worker):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from app import start_model_warm_up

    start_model_warm_up()
