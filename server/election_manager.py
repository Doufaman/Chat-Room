"""
Implementing the Bully Election Algorithm for leader selection among servers.

"""
import threading
import time
import socket
from server.config import TYPE_LEADER, TYPE_FOLLOWER
from network.network_manager import create_udp_socket, send_udp_message, receive_udp_message, PORT_ELECTION


# --- Message Types for Election ---
TYPE_HEARTBEAT = 'HEARTBEAT'
TYPE_ELECTION = 'ELECTION'
TYPE_ANSWER = 'ANSWER'
TYPE_COORDINATOR = 'COORDINATOR'

# --- Configuration Constants ---
TIMEOUT_ELECTION = 2.0   # How long to wait for ANSWER
TIMEOUT_COORDINATOR = 4.0 # How long to wait for COORDINATOR after receiving ANSWER
HEARTBEAT_INTERVAL = 1.0 # Leader sends heartbeat every 1s

# --- States for Election Process ---
STATE_FOLLOWER = "FOLLOWER"
STATE_ELECTION = "ELECTION"
STATE_LEADER = "LEADER"


class ElectionManager:
    """
    Manages Bully Algorithm-based leader election.
    """
    
    def __init__(self, server_id, network_manager, on_state_change=None):
        """
        Args:
            server_id: Unique ID of this server (used for comparison in Bully algorithm)
            network_manager: Instance of NetworkManager for communication
            on_state_change: Callback function(new_state, leader_id) when role changes
        """
        self.my_id = server_id
        self.network_manager = network_manager  # Only for IP info
        self.on_state_change = on_state_change
        
        # Create independent UDP socket for election messages
        self.udp_socket = create_udp_socket('0.0.0.0', PORT_ELECTION)
        self.local_ip = network_manager.ip_local
        
        # State Variables
        self.state = STATE_FOLLOWER
        self.current_leader_id = None
        self.leader_ip = None  # Leader's IP address
        self.stop_event = threading.Event()
        
        # TCP heartbeat connection to leader
        self.heartbeat_socket = None
        self.heartbeat_thread = None
        
        # Known peers {server_id: ip_address}
        self.peers = {}
        
        # Coordination Flags (Thread-Safe)
        self.lock = threading.Lock()
        self.received_answer = False
        self.election_trigger = threading.Event()
        
        # WARNING: Do NOT set callback here - it will override Server's callback
        # Instead, Server should call handle_election_messages manually

    def set_peers(self, peers_dict):
        """
        Update the list of known peer servers
        """
        with self.lock:
            self.peers = peers_dict.copy()
            # Remove myself
            self.peers.pop(self.my_id, None)

    def start(self):
        """Start the election manager's state machine in a background thread."""
        print(f"[Election Manager] Manager starting for server {self.my_id}...")
        # Start independent UDP listener
        threading.Thread(target=self._udp_listener, daemon=True).start()
        # Start state machine
        threading.Thread(target=self.run_state_machine, daemon=True).start()
        # Start heartbeat monitoring (will connect when leader is known)
        threading.Thread(target=self._heartbeat_monitor, daemon=True).start()

    def stop(self):
        """Stop the election manager."""
        self.stop_event.set()
        self._close_heartbeat_connection()
        if self.udp_socket:
            self.udp_socket.close()

    # =================================================================
    #  UDP Listener (Independent from NetworkManager)
    # =================================================================
    def _udp_listener(self):
        """Listen for election messages on dedicated UDP port."""
        print(f"[Election Manager] UDP listener started on port {PORT_ELECTION}")
        while not self.stop_event.is_set():
            message, addr = receive_udp_message(self.udp_socket)
            if not message:
                continue
            
            msg_type = message.get('msg_type')
            msg_body = message.get('message', {})
            sender_ip = message.get('sender_ip')
            
            # Forward to message handler
            self.handle_election_messages(msg_type, msg_body, sender_ip)

    # =================================================================
    #  Message Handler
    # =================================================================
    def handle_election_messages(self, msg_type, message, sender_ip):
        """
        Handle incoming election-related messages.
        This is called by NetworkManager's callback.
        """
        if msg_type not in [TYPE_ELECTION, TYPE_ANSWER, TYPE_COORDINATOR, TYPE_HEARTBEAT]:
            return  # Not an election message, ignore
        
        sender_id = message.get('sender_id')
        if sender_id == self.my_id:
            return  # Ignore my own messages

        if msg_type == TYPE_ELECTION:
            # Someone lower wants to be leader - bully them back
            print(f"[Election Manager] Received ELECTION from {sender_id}. Sending ANSWER.")
            self._send_to_ip(sender_ip, TYPE_ANSWER, {})
            
            # If I'm not already in election or leader, start election
            with self.lock:
                if self.state != STATE_LEADER and self.state != STATE_ELECTION:
                    self._trigger_election("Challenged by lower node")

        elif msg_type == TYPE_ANSWER:
            # Someone higher is alive
            print(f"[Election Manager] Received ANSWER from {sender_id}.")
            with self.lock:
                self.received_answer = True

        elif msg_type == TYPE_COORDINATOR:
            # Someone declared victory
            sender_id = message.get('sender_id')
            print(f"[Election Manager] {sender_id} declared COORDINATOR from {sender_ip}.")
            with self.lock:
                self.current_leader_id = sender_id
                self.leader_ip = sender_ip  # Update leader IP
                if self.state != STATE_LEADER:  # Don't demote myself
                    self.state = STATE_FOLLOWER
                    self._notify_state_change()
                self.election_trigger.set()
            # Close old heartbeat, monitor will reconnect
            self._close_heartbeat_connection()

        elif msg_type == TYPE_HEARTBEAT:
            # Heartbeat from leader (handled elsewhere)
            pass

    # =================================================================
    #  State Machine
    # =================================================================
    def run_state_machine(self):
        """Main state machine loop."""
        # Wait briefly for discovery
        print(f"[Election Manager] Waiting for existing leader announcement...")
        time.sleep(1.0)
        
        # If no leader found after discovery, start election
        if self.current_leader_id is None:
            print(f"[Election Manager] No existing leader found. Starting election...")
            self._trigger_election("Startup - No leader detected")

        while not self.stop_event.is_set():
            with self.lock:
                current_state = self.state
            
            if current_state == STATE_ELECTION:
                self.handle_election()
            elif current_state == STATE_LEADER:
                self.handle_leader_heartbeat()
            elif current_state == STATE_FOLLOWER:
                self.handle_follower_monitoring()
            
            time.sleep(0.5)

    # --- Election Logic ---
    def handle_election(self):
        """Handle CANDIDATE state - run Bully election."""
        print(f"[Election Manager] Election started. My ID={self.my_id}")
        
        with self.lock:
            self.received_answer = False
            self.election_trigger.clear()
            peers_copy = self.peers.copy()

        # 1. Find higher ID peers
        # WARNING: If using UUID strings, comparison is lexicographic, not numeric
        # Consider using numeric IDs or IP-based comparison for Bully algorithm
        higher_peers = {pid: ip for pid, ip in peers_copy.items() if pid > self.my_id}
        
        if not higher_peers:
            print("[Election Manager] No higher peers. I am the winner!")
            self._become_leader()
            return

        # 2. Send ELECTION to all higher nodes
        for peer_id, peer_ip in higher_peers.items():
            self._send_to_ip(peer_ip, TYPE_ELECTION, {})

        # 3. Wait for ANSWER
        start_time = time.time()
        while time.time() - start_time < TIMEOUT_ELECTION:
            with self.lock:
                if self.received_answer or self.state != STATE_ELECTION:
                    break
            time.sleep(0.1)

        # 4. Check results
        with self.lock:
            if self.state != STATE_ELECTION:
                return  # Someone else became leader

            if not self.received_answer:
                # No one replied - I win
                print("[Election Manager] Timeout. No ANSWER received. I am taking over.")
                self._become_leader()
            else:
                # Received Answer - wait for Coordinator
                print("[Election Manager] Received ANSWER. Waiting for Coordinator...")
        
        # Wait for Coordinator message
        start_time = time.time()
        while time.time() - start_time < TIMEOUT_COORDINATOR:
            with self.lock:
                if self.state != STATE_ELECTION:
                    return  # Coordinator arrived
            time.sleep(0.1)
        
        # Coordinator timeout - restart election
        print("[Election Manager] Coordinator timeout. Restarting election.")
        self._trigger_election("Coordinator timeout")

    def handle_leader_heartbeat(self):
        """As leader, periodically broadcast COORDINATOR messages."""
        with self.lock:
            peers_copy = self.peers.copy()
        
        # Broadcast COORDINATOR to all peers
        for peer_id, peer_ip in peers_copy.items():
            self._send_to_ip(peer_ip, TYPE_COORDINATOR, {})

    def handle_follower_monitoring(self):
        """As follower, monitor leader (basic implementation)."""
        # In a full implementation, this would monitor heartbeats
        # For now, we rely on the election trigger from messages
        pass

    # --- Helpers ---
    def _trigger_election(self, reason):
        """Trigger a new election."""
        print(f"[Election Manager] Triggering Election: {reason}")
        with self.lock:
            self.state = STATE_ELECTION

    # =================================================================
    #  TCP Heartbeat Monitoring (Leader Failure Detection)
    # =================================================================
    
    def _heartbeat_monitor(self):
        """Monitor TCP connection to leader for failure detection."""
        print(f"[Election Manager] Heartbeat monitor started")
        PORT_HEARTBEAT = 9004  # Dedicated port for heartbeat
        
        while not self.stop_event.is_set():
            # Only connect if I'm a follower and leader is known
            if self.state == STATE_FOLLOWER and self.leader_ip and self.leader_ip != self.local_ip:
                try:
                    # Close existing connection if any
                    self._close_heartbeat_connection()
                    
                    # Establish TCP connection to leader
                    print(f"[Election Manager] Connecting to leader at {self.leader_ip}:{PORT_HEARTBEAT}")
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)  # 5 second timeout
                    sock.connect((self.leader_ip, PORT_HEARTBEAT))
                    
                    # Assign to instance variable after successful connection
                    self.heartbeat_socket = sock
                    
                    # Keep connection alive and detect disconnection
                    while not self.stop_event.is_set():
                        try:
                            # Try to receive (this will block until disconnect or timeout)
                            data = self.heartbeat_socket.recv(1)
                            if not data:
                                # Connection closed by leader
                                print(f"[Election Manager] Leader connection closed, triggering election")
                                self._trigger_election("LEADER_DISCONNECTED")
                                break
                        except socket.timeout:
                            # Timeout is OK, just means no data
                            continue
                        except Exception as e:
                            print(f"[Election Manager] Leader connection error: {e}, triggering election")
                            self._trigger_election("LEADER_CONNECTION_ERROR")
                            break
                    
                except Exception as e:
                    print(f"[Election Manager] Failed to connect to leader: {e}")
                    # If can't connect, trigger election after a delay
                    time.sleep(2)
                    if self.state == STATE_FOLLOWER:  # Still follower after delay
                        self._trigger_election("LEADER_UNREACHABLE")
            
            time.sleep(1)  # Check state every second
    
    def _close_heartbeat_connection(self):
        """Close the heartbeat TCP connection."""
        if self.heartbeat_socket:
            try:
                self.heartbeat_socket.close()
            except:
                pass
            self.heartbeat_socket = None
    
    def _update_leader_info(self, leader_id, leader_ip):
        """Update leader information and reset heartbeat connection."""
        with self.lock:
            self.current_leader_id = leader_id
            self.leader_ip = leader_ip
        print(f"[Election Manager] Leader updated: ID={leader_id}, IP={leader_ip}")
        # Close old connection, monitor will establish new one
        self._close_heartbeat_connection()

    def _trigger_election(self, reason):
        """Trigger a new election."""
        print(f"[Election Manager] Triggering Election: {reason}")
        with self.lock:
            self.state = STATE_ELECTION

    def _become_leader(self):
        """Become the leader and broadcast victory."""
        with self.lock:
            self.state = STATE_LEADER
            self.current_leader_id = self.my_id
            self.leader_ip = self.local_ip
            self._notify_state_change()
        
        # Close heartbeat connection (leaders don't monitor)
        self._close_heartbeat_connection()
        
        # Start heartbeat server for followers
        threading.Thread(target=self._start_heartbeat_server, daemon=True).start()
        
        # Broadcast Victory (retry 3 times)
        peers_copy = self.peers.copy()
        for _ in range(3):
            for peer_id, peer_ip in peers_copy.items():
                self._send_to_ip(peer_ip, TYPE_COORDINATOR, {})
            time.sleep(0.05)
    
    def _start_heartbeat_server(self):
        """As leader, listen for follower heartbeat connections."""
        PORT_HEARTBEAT = 9004
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, 'SO_REUSEPORT'):
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            server_socket.bind(('0.0.0.0', PORT_HEARTBEAT))
            server_socket.listen(5)
            server_socket.settimeout(1)  # Allow periodic checks
            
            print(f"[Election Manager] Leader heartbeat server started on port {PORT_HEARTBEAT}")
            
            active_connections = []
            
            while self.state == STATE_LEADER and not self.stop_event.is_set():
                try:
                    conn, addr = server_socket.accept()
                    print(f"[Election Manager] Heartbeat connection from {addr}")
                    active_connections.append(conn)
                    # Keep connection alive (follower will detect disconnect)
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.state == STATE_LEADER:
                        print(f"[Election Manager] Heartbeat server error: {e}")
                    break
            
            # Clean up when no longer leader
            for conn in active_connections:
                try:
                    conn.close()
                except:
                    pass
            server_socket.close()
            print(f"[Election Manager] Leader heartbeat server stopped")
            
        except Exception as e:
            print(f"[Election Manager] Failed to start heartbeat server: {e}")

    def _send_to_ip(self, target_ip, msg_type, extra_data):
        """Send election message to a specific IP via independent UDP socket."""
        message = {
            'msg_type': msg_type,
            'message': {
                'sender_id': self.my_id,
                **extra_data
            },
            'sender_ip': self.local_ip
        }
        send_udp_message(self.udp_socket, message, target_ip, PORT_ELECTION)

    def _notify_state_change(self):
        """Notify callback about state change."""
        if self.on_state_change:
            role = TYPE_LEADER if self.state == STATE_LEADER else TYPE_FOLLOWER
            self.on_state_change(role, self.current_leader_id)

