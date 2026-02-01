import threading
import time

from .base import Role
from server.config import TYPE_LEADER, TYPE_FOLLOWER

class Server(Role):
    def __init__(self, server_id, network_manager, identity, leader_address=None):
        super().__init__()
        self.server_id = server_id
        self.network_manager = network_manager
        self._identity = identity
        self.leader_address = leader_address
        self.leader_id = None
        #服务器列表
        self.membership_list = {
            self.server_id: self.network_manager.ip_local
        }

        self.network_manager.set_callback(self.handle_messages)
        self._running = True
        #self.known_servers = set()

    def start(self):
        # 启动网络监听
        self.network_manager.start_listening()
        
        print(f"[Server] Initialized role: {self._identity}, Server ID: {self.server_id}")
        if self._identity == TYPE_LEADER:
            print(f"[{self._identity}] Setting up {self._identity.lower()} role...")
        elif self.leader_address:
            self.register(self.leader_address)

    def register(self, leader_addr):
        print(f"[Follower] Registering with leader at {leader_addr}")
        self.network_manager.send_unicast(
            leader_addr,
            9001,
            "FOLLOWER_REGISTER",
            {"follower_id": self.server_id, "follower_ip": self.network_manager.ip_local}
        )

         
    def handle_messages(self, msg_type, message, ip_sender):
        if self._identity == TYPE_LEADER:
            if msg_type == "WHO_IS_LEADER":
                print(f'[{self._identity}] receive message from new PC {ip_sender}: {msg_type} {message}')
                self.network_manager.send_broadcast(
                    "I_AM_LEADER", 
                    {"leader_id": self.server_id, "leader_ip": self.network_manager.ip_local}
                )
                #print(1)
            # handle follower registration
            elif msg_type == "FOLLOWER_REGISTER":
                follower_id = message.get("follower_id")
                follower_ip = message.get("follower_ip")
                print(f'[{self._identity}] Follower {follower_id} with IP: {follower_ip} registered.')
                self.membership_list[follower_id] = follower_ip
                print(f'[{self._identity}] Current membership list: {self.membership_list}')
                self.network_manager.send_unicast(
                    follower_ip,
                    9001,
                    "REGISTER_ACK",
                    {"leader_id": self.server_id, "membership_list": self.membership_list}
                )
                #print('hhey')
        else:
            if msg_type == "REGISTER_ACK":
                #print('hhey')
                self.leader_id = message.get("leader_id")
                self.membership_list = message.get("membership_list", {})
                print(f'[Follower] Registered with Leader {self.leader_id}. Current membership list: {self.membership_list}')
    
    def change_role(self, new_role, leader_id):
        """Handle role change triggered by ElectionManager."""
        print(f"[Server] Role change: {self._identity} -> {new_role} (Leader ID: {leader_id})")
        old_role = self._identity
        self._identity = new_role
        
        if new_role == TYPE_LEADER:
            print(f"[Server] Becoming LEADER (ID: {self.server_id})")
            self.leader_id = self.server_id
            self.leader_address = self.network_manager.ip_local
            # Leader takes over membership management
            
        elif new_role == TYPE_FOLLOWER:
            print(f"[Server] Becoming FOLLOWER (Leader ID: {leader_id})")
            self.leader_id = leader_id
            # Find leader's IP from membership list
            self.leader_address = self.membership_list.get(leader_id)
            if self.leader_address:
                # Re-register with new leader if needed
                # self.register(self.leader_address)
                pass
    
    def get_membership_list(self):
        """Return current membership list for ElectionManager."""
        return self.membership_list.copy()

    def run(self):
        pass

    def shutdown(self):
        pass
    

