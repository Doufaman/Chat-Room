"""
Implementing the Bully Election Algorithm for leader selection among servers.

"""
import threading
import time
from server.config import TYPE_LEADER, TYPE_FOLLOWER
from network.network_manager import create_udp_socket, send_udp_message, receive_udp_message, PORT_ELECTION


# --- Message Types for Election ---
TYPE_ELECTION = 'ELECTION'
TYPE_ANSWER = 'ANSWER'
TYPE_COORDINATOR = 'COORDINATOR'

# --- Configuration Constants ---
TIMEOUT_ELECTION = 2.0   # How long to wait for ANSWER
TIMEOUT_COORDINATOR = 4.0 # How long to wait for COORDINATOR after receiving ANSWER

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
        if msg_type not in [TYPE_ELECTION, TYPE_ANSWER, TYPE_COORDINATOR]:
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
        print(f"[{self._get_identity()}] Election triggered: {reason}")
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

