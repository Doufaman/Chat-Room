import time
import uuid
import threading

from utills.logger import setup_logger
import logging

from network.network_manager import NetworkManager

from server.roles.server import Server
# from server.roles.leader import Leader
# from server.roles.follower import Follower
from server.dynamic_discovery import dynamic_discovery
from server.election_manager import ElectionManager
from server.chatroom_manager import ChatroomManager
from server.config import TYPE_FOLLOWER, TYPE_LEADER
from utills.ip_validator import prompt_valid_ip

DEBUG = False  # or False

if DEBUG:
    setup_logger(logging.DEBUG)
else:
    setup_logger(logging.INFO)

class StartupEngine:
    def __init__(self,
                 self_ip,
                 #config
                 ):
        # create unique server ID
        self.self_ip = self_ip
        
        #self.server_id = str(uuid.uuid4())
        self.server_id = uuid.uuid4().int % (10**9)  # using 9-digit number to identify server

        # --- Core modules ---
        # self.comm = Communication(config)
        # self.discovery = Discovery(self.comm)
        # self.membership = MembershipManager()
        # self.heartbeat = HeartbeatManager(self)
        # self.election = ElectionManager(self)
        # self.recovery = RecoveryManager(self)
        # self.chat = ChatroomManager(self)

    def start(self, self_ip):     
        # 1. Start communication
        # self.comm.start()
        
        # 2. Enter discovery
        current_identity, leader_address = dynamic_discovery(ip_local = self_ip) # Use current IP for dynamic discovery

        # Create corresponding network manager
        #network_manager, leader_address = NetworkManager(ip_local=self_ip)
        network_manager = NetworkManager(ip_local=self_ip, server_id=self.server_id)

        # Merged leader and follower server class
        server = Server(self.server_id, network_manager, identity=current_identity, leader_address=leader_address)
        server.start()

        # # ------------------------------------------------#
        # # The following part starts chatroom manager and election manager:  #
        # # ------------------------------------------------#
        # chatroom_manager = ChatroomManager(self.server_id, self_ip, membership_manager=server.membership_manager)
        # # Create a default chat room
        # chatroom_manager.create_room("General")

        # # Create ElectionManager with state change callback
        # def on_election_state_change(new_role, leader_id):
        #     """Callback when election changes role."""
        #     server.change_role(new_role, leader_id)
        #     # When becoming Leader, start discovery listener
        #     if new_role == TYPE_LEADER:
        #         chatroom_manager.start_discovery_listener()
        #     else:
        #         chatroom_manager.stop_discovery_listener()
        
        # # Map Server identity to ElectionManager state
        # from server.election_manager import STATE_LEADER, STATE_FOLLOWER
        # initial_election_state = STATE_LEADER if current_identity == TYPE_LEADER else STATE_FOLLOWER
        
        # election_manager = ElectionManager(
        #     self.server_id, 
        #     network_manager, 
        #     on_state_change=on_election_state_change,
        #     initial_state=initial_election_state
        # )
        
        # # Set server reference for membership access
        # election_manager.set_server_reference(server)
        
        # # === Set chatroom callbacks (the ONLY coupling point) ===
        # election_manager.set_chatroom_callbacks(
        #     get_info_callback=chatroom_manager.get_server_chat_info,
        #     on_list_updated_callback=chatroom_manager.update_all_servers_chatrooms
        # )
        
        # # If starting as Leader, start discovery listener immediately
        # if current_identity == TYPE_LEADER:
        #     chatroom_manager.start_discovery_listener()
        
        # # Set initial leader info if follower
        # if current_identity == TYPE_FOLLOWER and leader_address:
        #     election_manager.leader_ip = leader_address
        #     # Get leader_id from server's membership list after registration
        #     # Give server time to register and get membership
        #     time.sleep(0.5)
        #     membership = server.get_membership_list()
        #     # Find leader_id by matching IP
        #     for sid, sip in membership.items():
        #         if sip == leader_address:
        #             election_manager.current_leader_id = sid
        #             print(f"[StartupEngine] Initial leader set to ID={sid}, IP={leader_address}")
        #             # Initialize peers from membership (excluding leader and self)
        #             election_manager.update_peers_from_server()
        #             break
        # else:
        #     # Leader: initialize peers from membership
        #     time.sleep(0.5)
        #     election_manager.update_peers_from_server()
        
        # election_manager.start()
        
        # # if current_identity == "follower":
        #     Follower(self.server_id, network_manager, leader_address).start()
        # else:
        #     Leader(self.server_id, network_manager).start()

    
    # --------------------
    # State transitions
    # --------------------
    
    def become_follower(self, leader_addr):
        self.state = "FOLLOWER"
        self.leader_addr = leader_addr
        
        # Register to leader: must carry current load_info and address information (?)
        self.comm.send(leader_addr, {
            "type": "JOIN_SERVER",
            "server_id": self.server_id
        })
        
        # Start follower heartbeat
        self.heartbeat.start_follower_heartbeat()
    
    def become_leader(self):
        self.state = "LEADER"
        self.leader_addr = self.get_own_address()
        
        # Initialize membership
        self.membership.add_server(self.server_id, self.leader_addr)
        
        # Start leader heartbeat and timeout detection
        self.heartbeat.start_leader_heartbeat()
        self.heartbeat.start_timeout_checker()
    
    def become_candidate(self):
        self.state = "CANDIDATE"
        
        # Stop normal heartbeat
        self.heartbeat.stop()
        
        # Start election
        self.election.start_election()
    
    # --------------------
    # Helper methods
    # --------------------
    
    def get_own_address(self):
        """Get the address of this server"""
        # Implementation depends on actual network configuration
        # Returning a placeholder here
        return f"server_{self.server_id}_addr"
    
    # --------------------
    # Event handlers
    # --------------------
    
    def handle_events(self):
        msg = self.comm.receive()
        
        if msg["type"] == "HEARTBEAT": 
            self.heartbeat.handle_heartbeat(msg)
        
        elif msg["type"] == "HEARTBEAT_TIMEOUT":
            if self.state == "FOLLOWER":
                self.become_candidate()
        
        elif msg["type"] == "ELECTION":
            self.election.handle_election(msg)
        
        elif msg["type"] == "COORDINATOR":
            self.become_follower(msg["leader_addr"])
        
        elif msg["type"] == "JOIN_SERVER" and self.state == "LEADER":
            """
            1. membership.add_server
            2. membership.asiign_group
            3. inform related data to this server
            """
            self.membership.add_server(
                msg["server_id"], msg["addr"]
            )
        
        elif msg["type"] == "CLIENT_JOIN":
            self.chat.handle_client_join(msg)
        
        elif msg["type"] == "SERVER_CRASH" and self.state == "LEADER":
            self.recovery.handle_server_crash(msg["server_id"])

# modify1: move startup code into main.py
if __name__ == '__main__':
    # MY_IP = input("Please enter server IP address: ")
    MY_IP = prompt_valid_ip()  # For MACOS system test
    print(f"[Server] Starting server with IP: {MY_IP}")

    startup_engine = StartupEngine(MY_IP)
    startup_engine.start(MY_IP)

    # Keep main thread running, allow background listener threads to continue
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Server] Shutting down...")
        # modify: move the start od dynamic_discovery into startupengine
        # if current_server._role_instance:
        #    current_server._role_instance.shutdown()