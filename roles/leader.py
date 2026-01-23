import socket
import threading
import time

from .base import Role

class Leader(Role):
    def __init__(self, network):
        self.network = network
        self._running = True
        self.known_servers = set()

    def setup(self):
        # 绑定真正的业务回调
        self.nm.on_message_received = self.handle_messages

    def handle_messages(self, msg_type, addr, data):
        if data == "WHO_IS_LEADER":
            # 立即回传身份宣告
            self.nm.send_broadcast(f"I_AM_LEADER:{self.nm.host_ip}")

    def start(self):
        pass

    def run(self):
        pass
    

