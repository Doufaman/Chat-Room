import threading
import time

from .base import Role

class Leader(Role):
    def __init__(self, server_id, network_manager):
        super().__init__()
        self.server_id = server_id
        self.network_manager = network_manager
        self._identity = "LEADER"
        #服务器列表
        self.menbership_list = {
            self.server_id: self.network_manager.ip_local
        }

        self.network_manager.set_callback(self.handle_messages)
        self._running = True
        #self.known_servers = set()

        self.start()

    def start(self):
        # 启动网络监听
        self.network_manager.start_listening()
        
        print(f"[Server] Initialized role: {self._identity}, Server ID: {self.server_id}")
        print("[Leader] Setting up leader role...")
         

    def handle_messages(self, msg_type, message, ip_sender):
        if msg_type == "WHO_IS_LEADER":
            print(f'[Leader] receive message from new PC {ip_sender}: {msg_type} {message}')
            self.network_manager.send_broadcast(
                "I_AM_LEADER", 
                {"leader_id": self.server_id, "leader_ip": self.network_manager.ip_local}
            )
            #print(1)
        elif msg_type == "FOLLOWER_REGISTER":
            follower_id = message.get("follower_id")
            follower_ip = message.get("follower_ip")
            print(f'[Leader] Follower {follower_id} at {follower_ip} registered.')
            self.menbership_list[follower_id] = follower_ip
            print(f'[Leader] Current membership list: {self.menbership_list}')
            self.network_manager.send_unicast(
                follower_ip,
                9001,
                "REGISTER_ACK",
                {"leader_id": self.server_id, "membership_list": self.menbership_list}
            )

    def run(self):
        pass

    def shutdown(self):
        pass
    

