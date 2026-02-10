import logging
import os
from datetime import datetime

def setup_logger(level=logging.DEBUG):
    """
    Configure global logger: output to both console and file named with current timestamp.
    """
    # 1. Create log directory (if not exists)
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 2. Generate filename: format is logs/2023-10-27_14-30-05.log
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = os.path.join(log_dir, f"{timestamp}.log")

    # 3. Define log format
    log_format = logging.Formatter("%(asctime)s [%(name)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    # 4. Get root logger object
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 5. Clear existing handlers (prevent duplicate printing)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 6. Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)

    # 7. Create file handler
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    logging.info(f"Log system initialized. File saved to: {log_filename}")

def get_logger(name: str):
    """
    Get a logger with a name, convenient for tracking which module generated the log
    """
    return logging.getLogger(name)