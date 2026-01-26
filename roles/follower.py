import socket
import threading
import time

from .base import Role

class Follower(Role):
    def __init__(self, network_manager):
        super().__init__()
        self.network_manager = network_manager
        self._running = True
        self.known_servers = set()

        self.start()

    def start(self):
        pass

    def run(self):
        pass

    def shutdown(self):
        pass

