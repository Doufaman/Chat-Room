"""
Implementing the Bully Election Algorithm for leader selection among servers.

"""
import threading
import time
import socket
import random
from server.config import TYPE_LEADER, TYPE_FOLLOWER
from network.network_manager import create_udp_socket, send_udp_message, receive_udp_message, PORT_ELECTION
from utills.logger import get_logger

logger = get_logger("election")


# --- Message Types for Election ---
TYPE_ELECTION = 'ELECTION'
TYPE_ANSWER = 'ANSWER'
TYPE_COORDINATOR = 'COORDINATOR'

# --- Configuration Constants ---
TIMEOUT_ELECTION = 5.0   # How long to wait for ANSWER (increased for network delays)
TIMEOUT_COORDINATOR = 8.0 # How long to wait for COORDINATOR after receiving ANSWER

# --- States for Election Process ---
STATE_FOLLOWER = "FOLLOWER"
STATE_ELECTION = "ELECTION"
STATE_LEADER = "LEADER"


class ElectionManager:
    """
    Manages Bully Algorithm-based leader election.

    IMPORTANT:
    - This module is UDP-only (ELECTION/ANSWER/COORDINATOR).
    - Heartbeat / failure detection is owned by `server.fault_detection.HeartbeatMonitor`.
      When the follower suspects leader failure, it should call `trigger_election(...)`.
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
        
        # Known peers {server_id: ip_address}
        self.peers = {}
        
        # Coordination Flags (Thread-Safe)
        self.lock = threading.Lock()
        self.received_answer = False
        self.election_trigger = threading.Event()
        
        # Election timing control (prevent rapid re-elections)
        self.last_election_time = 0
        self.min_election_interval = 2.0  # Minimum time between elections
        
        # Flag to pause heartbeat timeout detection during election
        self.election_in_progress = False
        
        # Track if this server joined as Follower (should not self-elect initially)
        self.joined_as_follower = (initial_state == STATE_FOLLOWER)
        
        # === Chatroom callbacks (decoupled from ChatroomManager) ===
        # Called to get local chatroom info for HEARTBEAT_ACK
        self.get_chatroom_info_callback = None
        # Called when Leader aggregates chatroom info from all servers
        self.on_chatroom_list_updated_callback = None
        
        # WARNING: Do NOT set callback here - it will override Server's callback
        # Instead, Server should call handle_election_messages manually

    def set_peers(self, peers_dict):
        """Update the list of known peer servers (called by Server on registration)."""
        with self.lock:
            self.peers = peers_dict.copy()
            self.peers.pop(self.my_id, None)
    
    def set_chatroom_callbacks(self, get_info_callback, on_list_updated_callback):
        """
        Set chatroom-related callbacks (called by main_server.py).
        
        Args:
            get_info_callback: Function that returns this server's chatroom info dict
            on_list_updated_callback: Function(servers_list) called when Leader aggregates info
        """
        self.get_chatroom_info_callback = get_info_callback
        self.on_chatroom_list_updated_callback = on_list_updated_callback
    
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

    def set_leader(self, leader_id, leader_ip):
        """Set current leader info (usually from discovery/register)."""
        with self.lock:
            self.current_leader_id = int(leader_id) if isinstance(leader_id, str) else leader_id
            self.leader_ip = leader_ip

    def start(self):
        """Start the election manager's state machine in a background thread."""
        logger.info(f"[{self._get_identity()}] Election Manager starting")
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
        logger.info(f"[{self._get_identity()}] UDP listener started on UDP:{PORT_ELECTION}")
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
                logger.info(f"[{self._get_identity()}] Received COORDINATOR from {sender_id} ({sender_ip})")
            
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
        if msg_type not in [TYPE_ELECTION, TYPE_ANSWER, TYPE_COORDINATOR]:
            return  # Not an election message, ignore
        
        sender_id = message.get('sender_id')
        if sender_id == self.my_id:
            return  # Ignore my own messages

        if msg_type == TYPE_ELECTION:
            logger.info(f"[{self._get_identity()}] Challenged by {sender_id}, sending ANSWER to {sender_ip}")
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
                
                # Priority 1: If we're in ELECTION state, accept first COORDINATOR (first-come-first-served)
                # This prevents brain split when multiple nodes start election at similar times
                if self.state == STATE_ELECTION:
                    # Accept the first COORDINATOR that arrives, regardless of ID comparison
                    # This implements "first elected wins" principle
                    logger.info(f"[{self._get_identity()}] In ELECTION, accepting first COORDINATOR from {sender_id}")
                    self.current_leader_id = sender_id
                    self.leader_ip = sender_ip
                    self.state = STATE_FOLLOWER
                    self.election_in_progress = False  # Election completed, resume heartbeat detection
                    self._notify_state_change_if_changed(old_state)
                    self.election_trigger.set()
                    # Reset leader heartbeat timestamp
                    if hasattr(self, '_server_ref') and self._server_ref:
                        self._server_ref.leader_latest_heartbeat = time.time()
                        logger.info(f"[{self._get_identity()}] Reset leader heartbeat timer for new leader {sender_id}")
                        # Trigger immediate connection to new leader
                        self._try_connect_to_new_leader(sender_id, sender_ip)
                
                # Priority 2: If sender has higher ID, always accept
                elif sender_id > self.my_id:
                    self.current_leader_id = sender_id
                    self.leader_ip = sender_ip
                    if self.state != STATE_FOLLOWER:
                        logger.info(f"[{self._get_identity()}] Demoting to Follower, new Leader: {sender_id}")
                        self.state = STATE_FOLLOWER
                        self._notify_state_change_if_changed(old_state)
                    self.election_trigger.set()
                    # Reset leader heartbeat timestamp
                    if hasattr(self, '_server_ref') and self._server_ref:
                        self._server_ref.leader_latest_heartbeat = time.time()
                
                # Priority 3: If we're FOLLOWER and sender has lower/equal ID, accept it (leader is established)
                elif self.state == STATE_FOLLOWER and sender_id <= self.my_id:
                    # If we don't have a leader yet, or this is a re-announcement, accept it
                    if self.current_leader_id is None or self.current_leader_id == sender_id:
                        logger.info(f"[{self._get_identity()}] Accepting COORDINATOR from {sender_id} (no current leader)")
                        self.current_leader_id = sender_id
                        self.leader_ip = sender_ip
                        self.election_trigger.set()
                        if hasattr(self, '_server_ref') and self._server_ref:
                            self._server_ref.leader_latest_heartbeat = time.time()
                    # Otherwise keep current leader (don't switch to lower ID)
                
                # Priority 4: If we're already LEADER and receive lower ID claim, reject it
                elif sender_id < self.my_id and self.state == STATE_LEADER:
                    logger.warning(f"[{self._get_identity()}] Rejecting lower ID {sender_id}'s COORDINATOR (I'm already Leader)")
                    # Re-broadcast our leadership to resolve conflict
                    self._send_to_ip('<broadcast>', TYPE_COORDINATOR, {})

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
                # Leader duties (heartbeats, membership) are handled by other modules.
                # ElectionManager in leader state mostly exists to respond to ELECTION challenges.
                self.handle_leader()
            
            time.sleep(0.1)

    # --- Election Logic ---
    def handle_election(self):
        """Handle CANDIDATE state - run Bully election."""
        # Set flag to pause heartbeat timeout detection
        self.election_in_progress = True
        
        # Add random delay to avoid simultaneous elections
        random_delay = random.uniform(0.1, 0.5)
        time.sleep(random_delay)
        
        logger.info(f"[{self._get_identity()}] Election started; peers={list(self.peers.keys())}")
        
        with self.lock:
            self.received_answer = False
            self.election_trigger.clear()
            peers_copy = self.peers.copy()
            self.current_leader_id = None
            self.leader_ip = None
        
        higher_peers = {pid: ip for pid, ip in peers_copy.items() if pid > self.my_id}
        
        if not higher_peers:
            logger.info(f"[{self._get_identity()}] No higher peers, becoming Leader")
            self._become_leader()
            return

        logger.info(f"[{self._get_identity()}] Challenging higher peers: {list(higher_peers.keys())}")
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
                # State changed (likely received COORDINATOR), abort election
                logger.info(f"[{self._get_identity()}] State changed during election, aborting")
                return

            if not self.received_answer:
                should_become_leader = True
            else:
                should_become_leader = False
        
        if should_become_leader:
            # Double-check: if state changed to FOLLOWER (COORDINATOR arrived), don't become leader
            with self.lock:
                if self.state == STATE_FOLLOWER:
                    logger.info(f"[{self._get_identity()}] COORDINATOR arrived, canceling leadership")
                    return
            
            logger.info(f"[{self._get_identity()}] No ANSWER received, becoming Leader")
            self._become_leader()
            return
        
        # Wait for Coordinator
        start_time = time.time()
        while time.time() - start_time < TIMEOUT_COORDINATOR:
            with self.lock:
                if self.state != STATE_ELECTION:
                    return
            time.sleep(0.1)
        
        logger.warning(f"[{self._get_identity()}] Coordinator timeout, restarting election")
        self._trigger_election("Coordinator timeout")

    def handle_follower(self):
        """
        Follower state:
        - Passive most of the time.
        - HeartbeatMonitor will call `trigger_election(...)` when leader is suspected dead.
        - We keep a small wait here to avoid busy spinning.
        """
        with self.lock:
            leader_id = self.current_leader_id
            leader_ip = self.leader_ip
        
        # If no leader info and this server joined as follower, just wait for discovery/register to set it.
        if not leader_ip or not leader_id:
            if self.joined_as_follower:
                self.election_trigger.wait(timeout=1.0)
                return
            # Not a follower joiner - should elect if no leader
            self._trigger_election("No leader known")
            return

        # If we are the leader, switch state (should be rare; coordinator should set this).
        if leader_id == self.my_id:
            self.state = STATE_LEADER
            return

        # Passive wait until something triggers election or coordinator update.
        self.election_trigger.wait(timeout=1.0)

    def handle_leader(self):
        """Leader state: no-op loop (heartbeats are handled elsewhere)."""
        # Keep leader_id consistent.
        with self.lock:
            self.current_leader_id = self.my_id
            self.leader_ip = self.local_ip
        # Wait until either we are stopped or election is triggered (e.g., challenged).
        self.election_trigger.wait(timeout=1.0)

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
        # Debounce: prevent rapid re-elections
        current_time = time.time()
        if current_time - self.last_election_time < self.min_election_interval:
            logger.info(f"[{self._get_identity()}] Election debounced (too soon): {reason}")
            return
        
        self.last_election_time = current_time
        self.election_in_progress = True  # Pause heartbeat timeout detection
        logger.warning(f"[{self._get_identity()}] Election triggered: {reason}")
        self.state = STATE_ELECTION
        self.election_trigger.set()

    def trigger_election(self, reason="external trigger"):
        """
        Public API for external modules (HeartbeatMonitor / Server) to start election.
        Safe to call multiple times; only meaningful if not already in ELECTION.
        """
        with self.lock:
            if self.state == STATE_ELECTION:
                return
        self._trigger_election(reason)

    def _become_leader(self):
        """Become the leader and broadcast victory."""
        with self.lock:
            self.state = STATE_LEADER
            self.current_leader_id = self.my_id
            self.leader_ip = self.local_ip
            self.election_in_progress = False  # Election completed
            self._notify_state_change()
        
        logger.info(f"[{self._get_identity()}] Broadcasting COORDINATOR (victory)")
        # Send multiple COORDINATOR messages with longer intervals to ensure all nodes receive it
        for i in range(5):
            self._send_to_ip('<broadcast>', TYPE_COORDINATOR, {})
            time.sleep(0.2)  # Slightly longer interval for better delivery

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
        if msg_type != TYPE_ANSWER:
            logger.debug(f"[{self._get_identity()}] UDP send {msg_type} -> {target_ip}:{PORT_ELECTION}")
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
    
    def _try_connect_to_new_leader(self, leader_id, leader_ip):
        """Helper to trigger follower connection to new leader."""
        try:
            if hasattr(self, '_server_ref') and self._server_ref:
                server = self._server_ref
                # Update server's leader info
                server.leader_id = leader_id
                server.leader_address = leader_ip
                # Start connection in background to not block election handling
                threading.Thread(target=self._connect_to_leader_async, 
                               args=(leader_id, leader_ip), daemon=True).start()
        except Exception as e:
            logger.debug(f"Failed to trigger connection to new leader: {e}")
    
    def _connect_to_leader_async(self, leader_id, leader_ip):
        """Async connection to new leader."""
        try:
            # Small delay to let new leader start listener
            time.sleep(0.3)
            if hasattr(self, '_server_ref') and self._server_ref:
                server = self._server_ref
                logger.info(f"[{self._get_identity()}] Connecting to new leader {leader_id} at {leader_ip}")
                server.network_manager.start_follower_long_lived_connector(leader_ip, leader_id)
        except Exception as e:
            logger.debug(f"Failed async connection to leader: {e}")

