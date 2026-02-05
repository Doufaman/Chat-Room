import threading
import time

from .base import Role
from server.config import TYPE_LEADER, TYPE_FOLLOWER, HEARTBEAT_INTERVAL
from server.heartbeat import Heartbeat

class Server(Role):
    def __init__(self, server_id, network_manager, identity, leader_address=None):
        super().__init__()
        self.server_id = server_id
        self.network_manager = network_manager
        self.membership_manager = None  
        if identity == TYPE_LEADER:
            from server.membership import LeaderMembershipManager
            self.membership_manager = LeaderMembershipManager(True)
        else:
            from server.membership import BaseMembershipManger
            self.membership_manager = BaseMembershipManger(False)
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

        # start heartbeat manager
        self.heartbeat = Heartbeat(self, interval=HEARTBEAT_INTERVAL)
        self.heartbeat.start()

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
                # Ensure follower_id is integer
                follower_id = int(follower_id) if isinstance(follower_id, str) else follower_id
                print(f'[{self._identity}] Follower {follower_id} with IP: {follower_ip} registered.')
                self.membership_list[follower_id] = follower_ip
                print(f'[{self._identity}] Current membership list: {self.membership_list}')
                
                # Send membership excluding self (leader should not include itself for followers)
                membership_for_follower = {sid: sip for sid, sip in self.membership_list.items() if sid != self.server_id}
                
                self.network_manager.send_unicast(
                    follower_ip,
                    9001,
                    "REGISTER_ACK",
                    {"leader_id": self.server_id, "membership_list": membership_for_follower}
                )
                #print('hhey')
        else:
            if msg_type == "REGISTER_ACK":
                #print('hhey')
                self.leader_id = message.get("leader_id")
                membership_raw = message.get("membership_list", {})
                # Ensure all server_ids are integers
                self.membership_list = {}
                for sid, sip in membership_raw.items():
                    sid_int = int(sid) if isinstance(sid, str) else sid
                    self.membership_list[sid_int] = sip
                print(f'[Follower] Registered with Leader {self.leader_id}. Current membership list: {self.membership_list}')
    
    def change_role(self, new_role, leader_id):
        """Handle role change triggered by ElectionManager."""
        # Only log if role actually changes
        if self._identity == new_role:
            print(f"[Server] Role confirmed: {new_role} (Leader ID: {leader_id})")
            # Still update leader info even if role doesn't change
            if new_role == TYPE_FOLLOWER and leader_id != self.leader_id:
                self.leader_id = leader_id
                leader_ip = self.membership_list.get(leader_id)
                if leader_ip:
                    self.leader_address = leader_ip
            return
        
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
            leader_ip = self.membership_list.get(leader_id)
            if leader_ip:
                self.leader_address = leader_ip
                print(f"[Server] Leader address set to: {leader_ip}")
            else:
                # Leader not in membership yet - will be set when we receive heartbeat
                print(f"[Server] Leader {leader_id} not in membership list yet")
    
    def get_membership_list(self):
        """Return current membership list for ElectionManager."""
        return self.membership_list.copy()
    
    def update_membership_from_leader(self, membership_dict, leader_id):
        """Update membership list from leader's heartbeat (Follower only)."""
        # Convert all IDs to int
        self.membership_list = {}
        for sid, sip in membership_dict.items():
            sid_int = int(sid) if isinstance(sid, str) else sid
            self.membership_list[sid_int] = sip
        # Add leader (not included in broadcast)
        if leader_id not in self.membership_list:
            self.membership_list[leader_id] = self.leader_address
        # Add myself
        if self.server_id not in self.membership_list:
            self.membership_list[self.server_id] = self.network_manager.ip_local

    def run(self):
        pass

    def shutdown(self):
        pass
    

