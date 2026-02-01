"""
Implementing the Bully Election Algorithm for leader selection among servers.

"""
import threading
import time
from server.config import TYPE_LEADER, TYPE_FOLLOWER


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
        self.network_manager = network_manager
        self.on_state_change = on_state_change
        
        # State Variables
        self.state = STATE_FOLLOWER
        self.current_leader_id = None
        self.stop_event = threading.Event()
        
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
        print(f"[BullyElection] Manager starting for server {self.my_id}...")
        threading.Thread(target=self.run_state_machine, daemon=True).start()

    def stop(self):
        """Stop the election manager."""
        self.stop_event.set()

    # =================================================================
    #  Message Handler (Called by NetworkManager)
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
            print(f"[BullyElection] Received ELECTION from {sender_id}. Sending ANSWER.")
            self._send_to_ip(sender_ip, TYPE_ANSWER, {})
            
            # If I'm not already in election or leader, start election
            with self.lock:
                if self.state != STATE_LEADER and self.state != STATE_ELECTION:
                    self._trigger_election("Challenged by lower node")

        elif msg_type == TYPE_ANSWER:
            # Someone higher is alive
            print(f"[BullyElection] Received ANSWER from {sender_id}.")
            with self.lock:
                self.received_answer = True

        elif msg_type == TYPE_COORDINATOR:
            # Someone declared victory
            print(f"[BullyElection] {sender_id} declared COORDINATOR.")
            with self.lock:
                self.current_leader_id = sender_id
                if self.state != STATE_LEADER:  # Don't demote myself
                    self.state = STATE_FOLLOWER
                    self._notify_state_change()
                self.election_trigger.set()

        elif msg_type == TYPE_HEARTBEAT:
            # Heartbeat from leader (handled elsewhere)
            pass

    # =================================================================
    #  State Machine
    # =================================================================
    def run_state_machine(self):
        """Main state machine loop."""
        # Wait briefly for discovery
        print(f"[BullyElection] Waiting for existing leader announcement...")
        time.sleep(1.0)
        
        # If no leader found after discovery, start election
        if self.current_leader_id is None:
            print(f"[BullyElection] No existing leader found. Starting election...")
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
        print(f"[BullyElection] Election started. My ID={self.my_id}")
        
        with self.lock:
            self.received_answer = False
            self.election_trigger.clear()
            peers_copy = self.peers.copy()

        # 1. Find higher ID peers
        # WARNING: If using UUID strings, comparison is lexicographic, not numeric
        # Consider using numeric IDs or IP-based comparison for Bully algorithm
        higher_peers = {pid: ip for pid, ip in peers_copy.items() if pid > self.my_id}
        
        if not higher_peers:
            print("[BullyElection] No higher peers. I am the winner!")
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
                print("[BullyElection] Timeout. No ANSWER received. I am taking over.")
                self._become_leader()
            else:
                # Received Answer - wait for Coordinator
                print("[BullyElection] Received ANSWER. Waiting for Coordinator...")
        
        # Wait for Coordinator message
        start_time = time.time()
        while time.time() - start_time < TIMEOUT_COORDINATOR:
            with self.lock:
                if self.state != STATE_ELECTION:
                    return  # Coordinator arrived
            time.sleep(0.1)
        
        # Coordinator timeout - restart election
        print("[BullyElection] Coordinator timeout. Restarting election.")
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
        print(f"[BullyElection] Triggering Election: {reason}")
        with self.lock:
            self.state = STATE_ELECTION

    def _become_leader(self):
        """Become the leader and broadcast victory."""
        with self.lock:
            self.state = STATE_LEADER
            self.current_leader_id = self.my_id
            self._notify_state_change()
        
        # Broadcast Victory (retry 3 times)
        peers_copy = self.peers.copy()
        for _ in range(3):
            for peer_id, peer_ip in peers_copy.items():
                self._send_to_ip(peer_ip, TYPE_COORDINATOR, {})
            time.sleep(0.05)

    def _send_to_ip(self, target_ip, msg_type, extra_data):
        """Send election message to a specific IP."""
        message = {
            'sender_id': self.my_id,
            **extra_data
        }
        # Use broadcast for simplicity (can be optimized to unicast)
        self.network_manager.send_broadcast(msg_type, message)

    def _notify_state_change(self):
        """Notify callback about state change."""
        if self.on_state_change:
            role = TYPE_LEADER if self.state == STATE_LEADER else TYPE_FOLLOWER
            self.on_state_change(role, self.current_leader_id)

