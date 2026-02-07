import logging
import os
from datetime import datetime

def setup_logger(level=logging.DEBUG):
    """
    配置全局日志：同时输出到控制台和以当前时间命名的文件。
    """
    # 1. 创建日志目录（如果不存在）
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 2. 生成文件名：格式为 logs/2023-10-27_14-30-05.log
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = os.path.join(log_dir, f"{timestamp}.log")

    # 3. 定义日志格式
    log_format = logging.Formatter("%(asctime)s [%(name)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    # 4. 获取根日志记录器对象
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 5. 清除现有的 Handler（防止重复打印）
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 6. 创建“控制台”处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)

    # 7. 创建“文件”处理器
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    logging.info(f"日志系统初始化完成。文件保存至: {log_filename}")

def get_logger(name: str):
    """
    获取带名字的 logger，方便追踪是哪个模块产生的日志
    """
    return logging.getLogger(name)