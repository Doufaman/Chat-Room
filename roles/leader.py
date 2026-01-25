import threading
import time

from .base import Role

class Leader(Role):
    def __init__(self, network_manager):
        super().__init__()
        self.network_manager = network_manager
        self._running = True
        self.known_servers = set()

        self.setup()

    def setup(self):
        print("[Leader] Setting up leader role...")

    def handle_messages(self, msg_type, ip_sender):
        if msg_type == "WHO_IS_LEADER":
            print('receive message')
            self.network_manager.send_broadcast(ip_sender,"I_AM_LEADER", 'imformation','')

    def start(self):
        pass

    def run(self):
        pass
    

