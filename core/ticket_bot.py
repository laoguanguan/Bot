

# 必须 import 才能使用 utils 中的函数！
from utils.logger import setup_logger

class TicketBot:
    def __init__(self):
        setup_logger()  # 调用导入的函数