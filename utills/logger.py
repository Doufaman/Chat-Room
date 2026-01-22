import logging

def setup_logger(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

def get_logger(name: str):
    return logging.getLogger(name)
