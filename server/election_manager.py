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
HEARTBEAT_TIMEOUT = 6.0  # Follower waits 6s for heartbeat (more tolerant to network delays)
MAX_RECONNECT_ATTEMPTS = 3  # Retry connection before triggering election

# --- States for Election Process ---
STATE_FOLLOWER = "FOLLOWER"
STATE_ELECTION = "ELECTION"
STATE_LEADER = "LEADER"


class ElectionManager:
    """
    Manages Bully Algorithm-based leader election.
    """
    
    def __init__(self, server_id, network_manager, on_state_change=None, initial_state=None):
        """
        Args:
            server_id: Unique ID of this server (used for comparison in Bully algorithm)
            network_manager: Instance of NetworkManager for communication
            on_state_change: Callback function(new_state, leader_id) when role changes
            initial_state: Initial state (STATE_LEADER or STATE_FOLLOWER), defaults to FOLLOWER
        """
        self.my_id = server_id
        self.network_manager = network_manager  # Only for IP info
        self.on_state_change = on_state_change
        
        # Create independent UDP socket for election messages
        self.udp_socket = create_udp_socket('0.0.0.0', PORT_ELECTION)
        # Enable Broadcast
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.local_ip = network_manager.ip_local
        
        # State Variables
        self.state = initial_state if initial_state else STATE_FOLLOWER
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
        
        # Track if this server joined as Follower (should not self-elect initially)
        self.joined_as_follower = (initial_state == STATE_FOLLOWER)
        
        # WARNING: Do NOT set callback here - it will override Server's callback
        # Instead, Server should call handle_election_messages manually

    def set_peers(self, peers_dict):
        """Update the list of known peer servers (called by Server on registration)."""
        with self.lock:
            self.peers = peers_dict.copy()
            self.peers.pop(self.my_id, None)
    
    def update_peers_from_server(self):
        """Update peers from Server's membership list (for Leader to initialize)."""
        if hasattr(self, '_server_ref') and self._server_ref:
            membership = self._server_ref.get_membership_list()
            with self.lock:
                self.peers = {}
                for sid, sip in membership.items():
                    sid_int = int(sid) if isinstance(sid, str) else sid
                    if sid_int != self.my_id:
                        self.peers[sid_int] = sip

    def start(self):
        """Start the election manager's state machine in a background thread."""
        print(f"[{self._get_identity()}] Election Manager starting")
        threading.Thread(target=self._udp_listener, daemon=True).start()
        threading.Thread(target=self.run_state_machine, daemon=True).start()

    def stop(self):
        """Stop the election manager."""
        self.stop_event.set()
        if self.udp_socket:
            self.udp_socket.close()

    # =================================================================
    #  UDP Listener (Independent from NetworkManager)
    # =================================================================
    def _udp_listener(self):
        """Listen for election messages on dedicated UDP port."""
        print(f"[{self._get_identity()}] UDP listener started")
        while not self.stop_event.is_set():
            message, addr = receive_udp_message(self.udp_socket)
            if not message:
                continue
            
            msg_type = message.get('msg_type')
            msg_body = message.get('message', {})
            sender_ip = message.get('sender_ip')
            sender_id = msg_body.get('sender_id')
            
            # Ignore my own messages first (before logging)
            if sender_id == self.my_id:
                continue
            
            # Only log important messages (COORDINATOR)
            if msg_type == TYPE_COORDINATOR:
                print(f"[{self._get_identity()}] Received COORDINATOR from {sender_id}")
            
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
            print(f"[{self._get_identity()}] Challenged by {sender_id}, sending ANSWER")
            self._send_to_ip(sender_ip, TYPE_ANSWER, {})
            
            with self.lock:
                if self.state != STATE_LEADER and self.state != STATE_ELECTION:
                    self._trigger_election("Challenged by lower node")

        elif msg_type == TYPE_ANSWER:
            with self.lock:
                self.received_answer = True

        elif msg_type == TYPE_COORDINATOR:
            sender_id = message.get('sender_id')
            
            with self.lock:
                old_state = self.state
                if sender_id > self.my_id or self.state != STATE_LEADER:
                    self.current_leader_id = sender_id
                    self.leader_ip = sender_ip
                    if self.state != STATE_FOLLOWER:
                        print(f"[{self._get_identity()}] Demoting to Follower, new Leader: {sender_id}")
                        self.state = STATE_FOLLOWER
                        self._notify_state_change_if_changed(old_state)
                    self.election_trigger.set()
                elif sender_id < self.my_id and self.state == STATE_LEADER:
                    print(f"[{self._get_identity()}] Rejecting lower ID {sender_id}'s claim")
                    self._send_to_ip(sender_ip, TYPE_COORDINATOR, {})

        elif msg_type == TYPE_HEARTBEAT:
            pass

    # =================================================================
    #  State Machine
    # =================================================================
    def run_state_machine(self):
        """Main state machine loop."""
        # Only trigger initial election if this is the first server (not a joiner)
        if not self.joined_as_follower:
            if self.current_leader_id is None and self.leader_ip is None:
                time.sleep(1.5)
                if self.current_leader_id is None:
                    print(f"[{self._get_identity()}] First server, starting election")
                    self._trigger_election("First server startup")
        else:
            # Joined as Follower - leader info should be set by main_server.py
            print(f"[{self._get_identity()}] Joined as Follower, waiting for Leader connection")

        while not self.stop_event.is_set():
            state = self.state  # Local copy
            
            if state == STATE_FOLLOWER:
                self.handle_follower()
            elif state == STATE_ELECTION:
                self.handle_election()
            elif state == STATE_LEADER:
                self.handle_leader()
            
            time.sleep(0.1)

    # --- Election Logic ---
    def handle_election(self):
        """Handle CANDIDATE state - run Bully election."""
        print(f"[{self._get_identity()}] Election started")
        
        with self.lock:
            self.received_answer = False
            self.election_trigger.clear()
            peers_copy = self.peers.copy()
            self.current_leader_id = None
            self.leader_ip = None
        
        higher_peers = {pid: ip for pid, ip in peers_copy.items() if pid > self.my_id}
        
        if not higher_peers:
            print(f"[{self._get_identity()}] No higher peers, becoming Leader")
            self._become_leader()
            return

        print(f"[{self._get_identity()}] Challenging {len(higher_peers)} higher peers")
        for peer_id, peer_ip in higher_peers.items():
            self._send_to_ip(peer_ip, TYPE_ELECTION, {})

        start_time = time.time()
        while time.time() - start_time < TIMEOUT_ELECTION:
            with self.lock:
                if self.received_answer:
                    break
                if self.state != STATE_ELECTION:
                    return
            time.sleep(0.1)

        with self.lock:
            if self.state != STATE_ELECTION:
                return

            if not self.received_answer:
                should_become_leader = True
            else:
                should_become_leader = False
        
        if should_become_leader:
            print(f"[{self._get_identity()}] No response, becoming Leader")
            self._become_leader()
            return
        
        # Wait for Coordinator
        start_time = time.time()
        while time.time() - start_time < TIMEOUT_COORDINATOR:
            with self.lock:
                if self.state != STATE_ELECTION:
                    return
            time.sleep(0.1)
        
        print(f"[{self._get_identity()}] Coordinator timeout, restarting election")
        self._trigger_election("Coordinator timeout")

    def handle_follower(self):
        """As follower, connect to leader and monitor heartbeats."""
        with self.lock:
            leader_id = self.current_leader_id
            leader_ip = self.leader_ip
        
        # If no leader info and this server joined as follower, wait for leader info
        if not leader_ip or not leader_id:
            if self.joined_as_follower:
                print(f"[{self._get_identity()}] Waiting for Leader info to be set...")
                time.sleep(1.0)
                return
            else:
                # Not a follower joiner - should elect if no leader
                self._trigger_election("No leader known")
                return
        
        if leader_id == self.my_id:
            self.state = STATE_LEADER
            return
        
        # Retry connection before giving up
        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            if attempt > 0:
                print(f"[{self._get_identity()}] Reconnecting to Leader {leader_id} (attempt {attempt + 1}/{MAX_RECONNECT_ATTEMPTS})")
                time.sleep(1.0)  # Wait before retry
            else:
                print(f"[{self._get_identity()}] Connecting to Leader {leader_id}")
            
            PORT_HEARTBEAT = 9004
            sock = None
            connection_successful = False
            
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                sock.connect((leader_ip, PORT_HEARTBEAT))
                connection_successful = True
                print(f"[{self._get_identity()}] Connected to Leader {leader_id}")
                
                # Monitor heartbeats
                consecutive_timeouts = 0
                max_consecutive_timeouts = 2
                
                while self.state == STATE_FOLLOWER and not self.stop_event.is_set():
                    sock.settimeout(HEARTBEAT_TIMEOUT)
                    try:
                        msg = self.network_manager.receive_TCP_message(sock)
                        
                        if msg is None:
                            print(f"[{self._get_identity()}] Leader closed connection")
                            raise Exception("Connection closed by leader")
                        
                        m_type, message, _ = msg
                        if m_type == TYPE_HEARTBEAT:
                            consecutive_timeouts = 0  # Reset timeout counter
                            membership_raw = message.get('membership_list', {})
                            if membership_raw:
                                if hasattr(self, '_server_ref') and self._server_ref:
                                    self._server_ref.update_membership_from_leader(membership_raw, leader_id)
                                
                                with self.lock:
                                    self.peers = {}
                                    self.peers[leader_id] = leader_ip
                                    
                                    for sid, sip in membership_raw.items():
                                        sid_int = int(sid) if isinstance(sid, str) else sid
                                        if sid_int != self.my_id:
                                            self.peers[sid_int] = sip
                    
                    except socket.timeout:
                        consecutive_timeouts += 1
                        print(f"[{self._get_identity()}] Heartbeat timeout ({consecutive_timeouts}/{max_consecutive_timeouts})")
                        if consecutive_timeouts >= max_consecutive_timeouts:
                            print(f"[{self._get_identity()}] Too many consecutive timeouts")
                            raise Exception("Heartbeat timeout")
                        
            except Exception as e:
                print(f"[{self._get_identity()}] Leader connection error: {e}")
                if sock:
                    sock.close()
                
                # If connection was successful but lost later, break retry loop and trigger election
                if connection_successful:
                    print(f"[{self._get_identity()}] Lost connection to leader")
                    break
                # Otherwise, continue retry loop
                continue
            
            finally:
                if sock:
                    sock.close()
            
            # If we reach here with successful connection, it means we broke out of heartbeat loop
            # Could be state change or connection loss
            if connection_successful:
                break
        
        # Only trigger election if still in FOLLOWER state and not stopping
        if self.state == STATE_FOLLOWER and not self.stop_event.is_set():
            print(f"[{self._get_identity()}] All connection attempts failed, triggering election")
            self.current_leader_id = None
            self.leader_ip = None
            self._trigger_election("Leader failed")

    def handle_leader(self):
        """As leader, start TCP server and send heartbeats to followers."""
        print(f"[{self._get_identity()}] Starting heartbeat server")
        self.current_leader_id = self.my_id
        
        PORT_HEARTBEAT = 9004
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        
        try:
            server_sock.bind(('0.0.0.0', PORT_HEARTBEAT))
            server_sock.listen(5)
            server_sock.settimeout(1.0)
            
            followers = []
            heartbeat_counter = 0
            
            while self.state == STATE_LEADER and not self.stop_event.is_set():
                try:
                    conn, addr = server_sock.accept()
                    print(f"[{self._get_identity()}] Follower connected: {addr[0]}")
                    followers.append(conn)
                except socket.timeout:
                    pass
                
                full_membership = self._get_full_membership()
                membership_for_broadcast = {sid: sip for sid, sip in full_membership.items() if sid != self.my_id}
                
                for conn in followers[:]:
                    try:
                        self.network_manager.send_TCP_message(conn, TYPE_HEARTBEAT, {'membership_list': membership_for_broadcast})
                    except:
                        conn.close()
                        followers.remove(conn)
                
                heartbeat_counter += 1
                if heartbeat_counter % 5 == 0:
                    self._send_to_ip('<broadcast>', TYPE_COORDINATOR, {})
                        
                time.sleep(HEARTBEAT_INTERVAL)
                
        except Exception as e:
            print(f"[{self._get_identity()}] Error: {e}")
            self.state = STATE_FOLLOWER
        finally:
            server_sock.close()
            for f in followers:
                try:
                    f.close()
                except:
                    pass

    # --- Helpers ---
    def _get_identity(self):
        """Get current identity string for logging."""
        role = "Leader" if self.state == STATE_LEADER else "Follower" if self.state == STATE_FOLLOWER else "Election"
        return f"I'm {role} - ({self.my_id}, {self.local_ip})"
    
    def _get_full_membership(self):
        """Get full membership list including leader (for broadcast purposes)."""
        # This will be set by Server through set_server_reference
        if hasattr(self, '_server_ref') and self._server_ref:
            return self._server_ref.get_membership_list()
        return {self.my_id: self.local_ip}
    
    def set_server_reference(self, server):
        """Set reference to Server instance for accessing membership."""
        self._server_ref = server
    
    def _trigger_election(self, reason):
        """Trigger a new election."""
        print(f"[{self._get_identity()}] Election triggered: {reason}")
        self.state = STATE_ELECTION
        self.election_trigger.set()

    def _become_leader(self):
        """Become the leader and broadcast victory."""
        with self.lock:
            self.state = STATE_LEADER
            self.current_leader_id = self.my_id
            self.leader_ip = self.local_ip
            self._notify_state_change()
        
        print(f"[{self._get_identity()}] Broadcasting victory")
        for _ in range(3):
            self._send_to_ip('<broadcast>', TYPE_COORDINATOR, {})
            time.sleep(0.1)

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
            leader_id = self.current_leader_id if self.current_leader_id else self.my_id
            self.on_state_change(role, leader_id)
    
    def _notify_state_change_if_changed(self, old_state):
        """Only notify if state actually changed."""
        if old_state != self.state:
            self._notify_state_change()

