import threading
import time

from .base import Role

class Leader(Role):
    def __init__(self, network_manager):
        super().__init__()
        self.network_manager = network_manager
        self.network_manager.set_callback(self.handle_messages)
        self._running = True
        #self.known_servers = set()

        self.start()

    def start(self):
        print("[Leader] Setting up leader role...")

    def handle_messages(self, msg_type, message, ip_sender):
        if msg_type == "WHO_IS_LEADER":
            print(f'[Leader] receive message from new PC {ip_sender}: {msg_type} {message}')
            self.network_manager.send_broadcast("I_AM_LEADER", 'imformation')
            #print(1)

    def run(self):
        pass

    def shutdown(self):
        pass
    

