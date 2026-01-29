import socket
import threading
import time

from .base import Role

class Follower(Role):
    def __init__(self, server_id, network_manager, leader_address=None):
        super().__init__()
        self.server_id = server_id
        self.network_manager = network_manager
        self.identity = "FOLLOWER"
        self._running = True
        self.membership_list = {}
        self.leader_address = leader_address
        self.leader_latest_heartbeat = time.time()

        self.network_manager.set_callback(self.handle_messages)

        self.start()

    def start(self):
        pass
        # 启动网络监听
        self.network_manager.start_listening()
        print(f"[Server] Initialized role: {self.identity}, Server ID: {self.server_id}")

        if self.leader_address:
            self.register(self.leader_address)

    def register(self, leader_addr):
        print(f"[Follower] Registering with leader at {leader_addr}")
        self.network_manager.send_unicast(
            leader_addr,
            9001,
            "FOLLOWER_REGISTER",
            {"follower_id": self.server_id, "follower_ip": self.network_manager.ip_local}
        )
        #print(1)

    def handle_messages(self, msg_type, message, ip_sender):
        if msg_type == "REGISTER_ACK":
            #print('hhey')
            leader_id = message.get("leader_id")
            self.membership_list = message.get("membership_list", {})
            print(f'[Follower] Registered with Leader {leader_id}. Current membership list: {self.membership_list}')

    def run(self):
        pass

    def shutdown(self):
        pass

