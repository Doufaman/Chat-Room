import threading
import time

import psutil

from server.fault_detection import HeartbeatMonitor

from .base import Role
from server.config import TYPE_LEADER, TYPE_FOLLOWER, HEARTBEAT_INTERVAL
from server.heartbeat import Heartbeat
from server.membership import MembershipManager

class Server(Role):
    def __init__(self, server_id, network_manager, identity, leader_address=None):
        super().__init__()
        self.server_id = server_id
        self.network_manager = network_manager

        self._identity = identity

        # create membership manager according to identity
        self.membership_manager = MembershipManager(is_leader=(self._identity == TYPE_LEADER))
        self.leader_address = leader_address
        self.leader_id = None
        self.leader_latest_heartbeat = time.time()
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

        # leader role needs to initialize membership management immediately, while follower will initialize later
        if self._identity == TYPE_LEADER:
            print(f"[{self._identity}] Setting up {self._identity.lower()} role...")
            self.membership_manager.initialize_for_leader(True, {
                "server_id": self.server_id,
                "load_info": self.get_current_load(),
                "address": self.network_manager.ip_local
            })  
            # start listening for long-lived TCP connections from followers
            self.network_manager.start_leader_long_lived_listener()
            # start heartbeat manager
            self.heartbeat = Heartbeat(self, interval=HEARTBEAT_INTERVAL)
            self.heartbeat.start()
            # start fault detection monitor
            self.heartbeat_monitor = HeartbeatMonitor(self)
        elif self.leader_address:
            self.register(self.leader_address)



        print(f"[Server] Initialized role: {self._identity}, Server ID: {self.server_id}")
        
            

    def register(self, leader_addr):
        print(f"[Follower] Registering with leader at {leader_addr}")
        self.network_manager.send_unicast(
            leader_addr,
            9001,
            "FOLLOWER_REGISTER",
            {"follower_id": self.server_id, 
             "load_info": self.get_current_load(),
             "follower_ip": self.network_manager.ip_local}
        )

         
    def handle_messages(self, msg_type, message, ip_sender):
        # heartbeat messages
        if msg_type in ("HEARTBEAT", "ARE_YOU_ALIVE", "PROBE_REQUEST", "PROBE_RESPONSE", "I_AM_ALIVE"):
            self.heartbeat.handle_incoming(message, msg_type, sender_addr=ip_sender)
            return
        
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
                load_info = message.get("load_info")
                # Ensure follower_id is integer
                follower_id = int(follower_id) if isinstance(follower_id, str) else follower_id
                print(f'[{self._identity}] Follower {follower_id} with IP: {follower_ip} registered.')
                self.membership_list[follower_id] = follower_ip
                print(f'[{self._identity}] Current membership list: {self.membership_list}')

                            
                self.membership.add_server(follower_id, follower_ip, load_info)
                group_id, existed_members = self.membership.assign_group(follower_id)
               
                # Send membership excluding self (leader should not include itself for followers)
                membership_for_follower = {sid: sip for sid, sip in self.membership_list.items() if sid != self.server_id}
                
                self.network_manager.send_unicast(
                    follower_ip,
                    9001,
                    "REGISTER_ACK",
                    {"leader_id": self.server_id, 
                        "group_id": group_id,
                        "existed_members": existed_members,
                        "membership_list": membership_for_follower}
                )           
                # todo: notidy other followers about the new member
            
                #print('hhey')
        else:
            if msg_type == "REGISTER_ACK":
                #print('hhey')
                self.leader_id = message.get("leader_id")
                membership_raw = message.get("membership_list", {})
                self.membership.set_group_info(message.get("group_id"), message.get("existed_members", {}))
                # start long-lived TCP connection to leader 
                self.network_manager.start_follower_long_lived_connector(self.leader_id, self.leader_address)

                # start heartbeat manager
                self.heartbeat = Heartbeat(self, interval=HEARTBEAT_INTERVAL)
                self.heartbeat.start()
                self.heartbeat_monitor = HeartbeatMonitor(self)

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

    def get_current_load(self):
        """获取当前负载信息"""
        pass
        cpu_percent = psutil.cpu_percent(interval=1)
        memory_percent = psutil.virtual_memory().percent
        memory_available = psutil.virtual_memory().available
        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent
        }
    

