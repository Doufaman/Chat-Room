import threading
import time

from server.membership import LeaderMembershipManager
from .base import Role
from server.fault_detection import Heartbeat

class Leader(Role):
    def __init__(self, server_id, network_manager):
        super().__init__()
        self.server_id = server_id
        self.network_manager = network_manager
        self.membership = LeaderMembershipManager(True)
        self.identity = "LEADER"
        self.heartbeat = Heartbeat(self)
        self.network_manager.set_callback(self.handle_messages)
        self._running = True
        #self.known_servers = set()

    def start(self):
        # 启动网络监听
        self.network_manager.start_listening()
        
        print(f"[Server] Initialized role: {self.identity}, Server ID: {self.server_id}")
        print("[Leader] Setting up leader role...")
         

    def handle_messages(self, msg_type, message, ip_sender):
        if msg_type == "WHO_IS_LEADER":
            print(f'[Leader] receive message from new PC {ip_sender}: {msg_type} {message}')
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
            print(f'[Leader] Follower {follower_id} with IP: {follower_ip} registered.')
            self.membership.add_server(follower_id, follower_ip, load_info)
            group_id, existed_members = self.membership.assign_group(follower_id)

            self.network_manager.send_unicast(
                follower_ip,
                9001,
                "REGISTER_ACK",
                {"leader_id": self.server_id,
                  "group_id": group_id,
                  "members_in_group": existed_members,
                  "membership_list": existed_members}
            )
            # todo: notidy other followers about the new member
            
            #print('hhey')
        # handle heartbeat messages from followers
        elif msg_type == "HEARTBEAT":
            self.heartbeat.handle_heartbeat(message)
        # handle alive probe responses from followers
        elif msg_type == "PROBE_RESPONSE":
            self.heartbeat.handle_probe_response(message)

    def run(self):
        pass

    def shutdown(self):
        pass
    

