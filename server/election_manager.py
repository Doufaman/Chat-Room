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
        print(f"[Election Manager] Manager starting for server {self.my_id}...")
        # Start independent UDP listener
        threading.Thread(target=self._udp_listener, daemon=True).start()
        # Start state machine (Main Logic)
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
        print(f"[Election Manager] UDP listener started on port {PORT_ELECTION}")
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
            
            # Debug: log received messages
            if msg_type in [TYPE_ELECTION, TYPE_ANSWER, TYPE_COORDINATOR]:
                print(f"[{self.state}] UDP received {msg_type} from {sender_id}")
            
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
        
        # Debug: show current state when handling message
        with self.lock:
            current_state = self.state
        
        # Only log non-heartbeat messages to reduce noise
        if msg_type != TYPE_HEARTBEAT:
            print(f"[Election Manager] Handling {msg_type} from {sender_id} (my state: {current_state})")

        if msg_type == TYPE_ELECTION:
            # Someone lower wants to be leader - bully them back
            print(f"[Election Manager] Received ELECTION from {sender_id} at {sender_ip}. Sending ANSWER.")
            self._send_to_ip(sender_ip, TYPE_ANSWER, {})
            
            # If I'm not already in election or leader, start election
            # If I'm already leader, the ANSWER is enough (don't restart election)
            with self.lock:
                if self.state != STATE_LEADER and self.state != STATE_ELECTION:
                    self._trigger_election("Challenged by lower node")

        elif msg_type == TYPE_ANSWER:
            # Someone higher is alive
            print(f"[Election Manager] Received ANSWER from {sender_id} at {sender_ip}.")
            with self.lock:
                self.received_answer = True

        elif msg_type == TYPE_COORDINATOR:
            # Someone declared victory
            sender_id = message.get('sender_id')
            print(f"[Election Manager] {sender_id} declared COORDINATOR from {sender_ip}.")
            
            with self.lock:
                old_state = self.state
                # If sender has higher ID, or I'm not leader, accept them as leader
                if sender_id > self.my_id or self.state != STATE_LEADER:
                    self.current_leader_id = sender_id
                    self.leader_ip = sender_ip
                    if self.state != STATE_FOLLOWER:
                        print(f"[Election Manager] Demoting to FOLLOWER. New Leader: {sender_id}")
                        self.state = STATE_FOLLOWER
                        self._notify_state_change_if_changed(old_state)
                    self.election_trigger.set()
                elif sender_id < self.my_id and self.state == STATE_LEADER:
                    # I have higher ID and I'm leader - send COORDINATOR back
                    print(f"[Election Manager] Rejecting lower ID {sender_id}'s COORDINATOR (I am {self.my_id})")
                    self._send_to_ip(sender_ip, TYPE_COORDINATOR, {})
            # Election trigger will interrupt follower loop

        elif msg_type == TYPE_HEARTBEAT:
            # Heartbeat from leader (handled in handle_follower via TCP)
            pass

    # =================================================================
    #  State Machine
    # =================================================================
    def run_state_machine(self):
        """Main state machine loop."""
        # Only trigger election if this is the first server (no leader known)
        if self.current_leader_id is None and self.leader_ip is None:
            print(f"[Election Manager] No existing leader. Waiting for discovery...")
            time.sleep(1.5)  # Wait for potential COORDINATOR messages
            
            # Still no leader after waiting - I must be the first server
            if self.current_leader_id is None:
                print(f"[Election Manager] Still no leader. Starting election as first server.")
                self._trigger_election("First server startup")
        else:
            print(f"[Election Manager] Leader already known (ID={self.current_leader_id}, IP={self.leader_ip}). Skipping election.")

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
        print(f"[Election Manager] Election started. My ID={self.my_id}")
        
        with self.lock:
            self.received_answer = False
            self.election_trigger.clear()
            peers_copy = self.peers.copy()
            # Clear current leader since we're in election
            self.current_leader_id = None
            self.leader_ip = None

        print(f"[Election Manager] Known peers: {peers_copy}")
        
        # 1. Find higher ID peers
        # WARNING: If using UUID strings, comparison is lexicographic, not numeric
        # Consider using numeric IDs or IP-based comparison for Bully algorithm
        higher_peers = {pid: ip for pid, ip in peers_copy.items() if pid > self.my_id}
        
        print(f"[Election Manager] Higher peers: {higher_peers}")
        
        if not higher_peers:
            print("[Election Manager] No higher peers. I am the winner!")
            self._become_leader()
            return

        # 2. Send ELECTION to all higher nodes
        print(f"[Election Manager] Sending ELECTION to {len(higher_peers)} higher peers")
        for peer_id, peer_ip in higher_peers.items():
            self._send_to_ip(peer_ip, TYPE_ELECTION, {})

        # 3. Wait for ANSWER
        print(f"[Election Manager] Waiting {TIMEOUT_ELECTION}s for ANSWER...")
        start_time = time.time()
        while time.time() - start_time < TIMEOUT_ELECTION:
            with self.lock:
                if self.received_answer:
                    print(f"[Election Manager] ANSWER received after {time.time() - start_time:.2f}s")
                    break
                if self.state != STATE_ELECTION:
                    print(f"[Election Manager] State changed to {self.state}, exiting election")
                    return
            time.sleep(0.1)

        # 4. Check results
        with self.lock:
            if self.state != STATE_ELECTION:
                return  # Someone else became leader

            if not self.received_answer:
                # No one replied - I win
                print("[Election Manager] Timeout. No ANSWER received. I am taking over.")
                # DON'T call _become_leader inside lock - it will deadlock
                should_become_leader = True
            else:
                # Received Answer - wait for Coordinator
                print("[Election Manager] Received ANSWER. Waiting for Coordinator...")
                should_become_leader = False
        
        # Call _become_leader OUTSIDE the lock
        if should_become_leader:
            self._become_leader()
            return
        
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

    def handle_follower(self):
        """As follower, connect to leader and monitor heartbeats."""
        # Get latest leader info with lock
        with self.lock:
            leader_id = self.current_leader_id
            leader_ip = self.leader_ip
        
        if not leader_ip or not leader_id:
            print(f"[Follower] No leader known (ID={leader_id}, IP={leader_ip}). Triggering election.")
            self._trigger_election("No leader known")
            return
        
        if leader_id == self.my_id:
            print(f"[Follower] I am the leader. Changing to LEADER state.")
            self.state = STATE_LEADER
            return
        
        print(f"[Follower] Connecting to Leader {leader_id} at {leader_ip}:9004")
        
        PORT_HEARTBEAT = 9004
        sock = None
        try:
            # Connect to leader's TCP heartbeat server
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            sock.connect((leader_ip, PORT_HEARTBEAT))
            print(f"[Follower] Connected to Leader {leader_id} (TCP)")
            
            # Listen for heartbeats
            while self.state == STATE_FOLLOWER and not self.stop_event.is_set():
                sock.settimeout(HEARTBEAT_INTERVAL * 3)  # 3 second timeout
                msg = self.network_manager.receive_TCP_message(sock)
                
                if msg is None:
                    raise Exception("Connection closed by Leader")
                
                m_type, message, _ = msg
                if m_type == TYPE_HEARTBEAT:
                    # Heartbeat contains membership_list (excluding leader)
                    membership_raw = message.get('membership_list', {})
                    if membership_raw:
                        # Update Server's membership
                        if hasattr(self, '_server_ref') and self._server_ref:
                            self._server_ref.update_membership_from_leader(membership_raw, leader_id)
                        
                        # Update election peers
                        with self.lock:
                            self.peers = {}
                            # Add the current leader explicitly
                            self.peers[leader_id] = leader_ip
                            
                            for sid, sip in membership_raw.items():
                                sid_int = int(sid) if isinstance(sid, str) else sid
                                if sid_int != self.my_id:
                                    self.peers[sid_int] = sip
                    
        except Exception as e:
            print(f"[Follower] Leader {leader_id} failed: {e}")
        finally:
            if sock:
                sock.close()
        
        # If we exit the loop and still a follower, leader died
        if self.state == STATE_FOLLOWER and not self.stop_event.is_set():
            # Don't remove leader from peers - we might need to challenge them later
            # with self.lock:
            #     if self.current_leader_id in self.peers:
            #         del self.peers[self.current_leader_id]
            self.current_leader_id = None
            self.leader_ip = None
            self._trigger_election("Leader failed")

    def handle_leader(self):
        """As leader, start TCP server and send heartbeats to followers."""
        print(f"[Leader] I am LEADER. Starting TCP Server on port 9004...")
        self.current_leader_id = self.my_id
        
        PORT_HEARTBEAT = 9004
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        
        try:
            server_sock.bind(('0.0.0.0', PORT_HEARTBEAT))
            server_sock.listen(5)
            server_sock.settimeout(1.0)  # Non-blocking accept
            
            followers = []
            heartbeat_counter = 0
            
            while self.state == STATE_LEADER and not self.stop_event.is_set():
                # A. Accept new followers
                try:
                    conn, addr = server_sock.accept()
                    print(f"[Leader] Follower connected: {addr}")
                    followers.append(conn)
                except socket.timeout:
                    pass  # Just loop to send heartbeats
                
                # B. Send Heartbeats to all (with membership_list)
                # Get membership from server (includes all members)
                full_membership = self._get_full_membership()
                # Exclude myself from the broadcast list
                membership_for_broadcast = {sid: sip for sid, sip in full_membership.items() if sid != self.my_id}
                
                for conn in followers[:]:
                    try:
                        # Send heartbeat with membership_list (excluding leader)
                        self.network_manager.send_TCP_message(conn, TYPE_HEARTBEAT, {'membership_list': membership_for_broadcast})
                    except:
                        # Follower disconnected - remove from Server's membership
                        conn.close()
                        followers.remove(conn)
                        # Notify Server to remove disconnected follower
                        if hasattr(self, '_server_ref') and self._server_ref:
                            # Find which follower disconnected by checking membership
                            # This is handled by Server's connection management
                            pass
                
                # C. Periodically broadcast COORDINATOR via UDP (for new servers joining and split brain resolution)
                heartbeat_counter += 1
                if heartbeat_counter % 5 == 0:  # Every 5 heartbeats (5 seconds)
                    self._send_to_ip('<broadcast>', TYPE_COORDINATOR, {})
                        
                time.sleep(HEARTBEAT_INTERVAL)
                
        except Exception as e:
            print(f"[Leader] Error: {e}")
            self.state = STATE_FOLLOWER  # Demote myself on error
        finally:
            server_sock.close()
            for f in followers:
                try:
                    f.close()
                except:
                    pass
            print("[Leader] TCP Server stopped.")

    # --- Helpers ---
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
        print(f"[{self.state}] Triggering Election: {reason}")
        self.state = STATE_ELECTION
        self.election_trigger.set()  # Wake up any sleeping threads

    def _become_leader(self):
        """Become the leader and broadcast victory."""
        with self.lock:
            self.state = STATE_LEADER
            self.current_leader_id = self.my_id
            self.leader_ip = self.local_ip
            self._notify_state_change()
        
        # Broadcast Victory (retry 3 times) to EVERYONE (Broadcast IP)
        print(f"[Election Manager] Broadcasting COORDINATOR to Network")
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
            print(f"[Election Manager] Notifying role change: {role}, Leader ID: {leader_id}")
            self.on_state_change(role, leader_id)
    
    def _notify_state_change_if_changed(self, old_state):
        """Only notify if state actually changed."""
        if old_state != self.state:
            self._notify_state_change()

