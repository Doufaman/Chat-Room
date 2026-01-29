import time
import uuid
import sys
import signal
import threading

from utills.logger import setup_logger
import logging

from network.network_manager import NetworkManager

from server.roles.leader import Leader
from server.roles.follower import Follower
from server.dynamic_discovery import dynamic_discovery
from server.consensus import ConsensusManager
from server.config import SERVERS, CLIENT_PORT_BASE

DEBUG = True  # or False

if DEBUG:
    setup_logger(logging.DEBUG)
else:
    setup_logger(logging.INFO)

# Global flag for graceful shutdown
STOP_EVENT = threading.Event()

class StartupEngine:
    def __init__(self, server_id, self_ip):
        """
        Initialize the server
        :param server_id: Unique server ID (integer)
        :param self_ip: IP address of this server
        """
        self.server_id = server_id
        self.self_ip = self_ip
        
        # Calculate client port
        self.client_port = CLIENT_PORT_BASE + server_id
        
        # Core modules
        self.consensus = None
        self.role_instance = None
        self.network_manager = None
        self.chatroom_manager = None  # Shared chatroom manager
    
    def start(self):
        """Start the server with consensus-based leader election"""
        print(f"[Server] Starting Server {self.server_id} at {self.self_ip}")
        
        # 1. Start Chatroom Manager (shared across all roles)
        from server.chatroom_manager import ChatroomManager
        self.chatroom_manager = ChatroomManager(self.server_id, self.client_port)
        threading.Thread(target=self.chatroom_manager.start, daemon=True).start()
        print(f"[Server] ChatroomManager started on port {self.client_port}")
        
        # 2. Start Consensus Module (Bully Algorithm)
        print(f"[Server] Starting Consensus Manager...")
        self.consensus = ConsensusManager(
            my_id=self.server_id,
            my_ip=self.self_ip,
            peers_config=SERVERS
        )
        self.consensus.start()
        
        # 3. Wait for leader election to complete
        print(f"[Server] Waiting for leader election...")
        time.sleep(5)  # Give time for election
        
        # 4. Initialize role based on consensus state
        if self.consensus.state == "LEADER":
            self.become_leader()
        else:
            leader_id = self.consensus.current_leader_id
            self.become_follower(leader_id)
        
        # 5. Monitor for role changes
        self.monitor_role_changes()
    
    def become_follower(self, leader_id):
        """Transition to follower role"""
        print(f"[Server] Becoming FOLLOWER. Leader is Server {leader_id}")
        
        # Initialize network manager
        if self.network_manager is None:
            self.network_manager = NetworkManager(ip_local=self.self_ip)
        
        # Create follower instance with shared chatroom_manager
        self.role_instance = Follower(
            server_id=self.server_id,
            network_manager=self.network_manager,
            consensus_manager=self.consensus,
            leader_address=leader_id,
            chatroom_manager=self.chatroom_manager
        )
        self.role_instance.start()
    
    def become_leader(self):
        """Transition to leader role"""
        print(f"[Server] Becoming LEADER")
        
        # Initialize network manager
        if self.network_manager is None:
            self.network_manager = NetworkManager(ip_local=self.self_ip)
        
        # Create leader instance with shared chatroom_manager
        self.role_instance = Leader(
            server_id=self.server_id,
            network_manager=self.network_manager,
            consensus_manager=self.consensus,
            chatroom_manager=self.chatroom_manager
        )
        self.role_instance.start()
    
    def monitor_role_changes(self):
        """Monitor consensus state and handle role transitions"""
        last_state = self.consensus.state
        
        while not STOP_EVENT.is_set():
            current_state = self.consensus.state
            
            # Detect state change
            if current_state != last_state:
                print(f"[Server] State changed: {last_state} -> {current_state}")
                
                # Shutdown current role
                if self.role_instance:
                    print(f"[Server] Shutting down old role...")
                    self.role_instance.shutdown()
                    # Wait for graceful shutdown
                    time.sleep(1)
                    self.role_instance = None
                
                # Transition to new role
                if current_state == "LEADER":
                    self.become_leader()
                elif current_state == "FOLLOWER":
                    leader_id = self.consensus.current_leader_id
                    if leader_id:
                        self.become_follower(leader_id)
                
                last_state = current_state
            
            time.sleep(1)

def signal_handler(sig, frame):
    """Handle Ctrl+C for graceful shutdown"""
    print("\n[!] Ctrl+C pressed. Shutting down...")
    STOP_EVENT.set()
    sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <server_id>")
        print("Example: python main.py 1")
        print("\nAvailable servers:")
        for server in SERVERS:
            print(f"  Server {server['id']}: {server['host']} (TCP: {server['tcp_port']}, UDP: {server['udp_port']})")
        sys.exit(1)

    server_id = int(sys.argv[1])
    
    # Find server configuration
    server_config = next((s for s in SERVERS if s['id'] == server_id), None)
    if not server_config:
        print(f"[!] Server ID {server_id} not found in configuration")
        sys.exit(1)
    
    self_ip = server_config['host']
    
    # Setup signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start server
    engine = StartupEngine(server_id, self_ip)
    engine.start()

    
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
    MY_IP = input("请输入服务器 IP 地址: ")
    print(f"[Server] Starting server with IP: {MY_IP}")

    startup_engine = StartupEngine(MY_IP)
    startup_engine.start(MY_IP)

    # 保持主线程运行，让后台监听线程继续工作
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Server] Shutting down...")
        # modify: move the start od dynamic_discovery into startupengine
        # if current_server._role_instance:
        #    current_server._role_instance.shutdown()