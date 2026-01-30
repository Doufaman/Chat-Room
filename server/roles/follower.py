import socket
import threading
import time

from .base import Role

class Follower(Role):
    def __init__(self, server_id, network_manager, leader_address=None):
        super().__init__()
        self.server_id = server_id
        self.network_manager = network_manager
        self._identity = "FOLLOWER"
        self._running = True
        self.known_servers = set()
        self.leader_address = leader_address

        self.start()

    def start(self):
        pass
        # 启动网络监听
        self.network_manager.start_listening()
        print(f"[Server] Initialized role: {self._identity}, Server ID: {self.server_id}")

    def run(self):
        pass

    def shutdown(self):
        pass

