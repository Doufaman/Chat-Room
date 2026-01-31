import threading
import time
import socket
import json
from common.protocol import *
from network.messenger import *

# --- Configuration Constants ---
TIMEOUT_ELECTION = 2.0   # How long to wait for ANSWER
TIMEOUT_COORDINATOR = 4.0 # How long to wait for COORDINATOR after receiving ANSWER
HEARTBEAT_INTERVAL = 1.0 # Leader sends heartbeat every 1s

# --- States of servers ---
STATE_FOLLOWER = "FOLLOWER"
STATE_ELECTION = "ELECTION"
STATE_LEADER = "LEADER"

class ConsensusManager:
    def __init__(self, my_id, config):
        self.my_id = my_id
        self.config = config
        self.peers = config['servers']
        
        # Extract my own config
        my_info = next(s for s in self.peers if s['id'] == self.my_id)
        self.my_udp_port = my_info['udp_port']
        self.my_tcp_port = my_info['tcp_port']
        
        # State Variables
        self.state = STATE_FOLLOWER
        self.current_leader_id = None
        self.stop_event = threading.Event()
        
        # UDP Socket (Always open for Election/Coordination)
        self.udp_sock = create_udp_socket('0.0.0.0', self.my_udp_port)
        
        # Coordination Flags (Thread-Safe)
        self.lock = threading.Lock()
        self.received_answer = False
        self.election_trigger = threading.Event() # Used to break sleep loops

    def start(self):
        print(f"[Consensus] Node {self.my_id} starting...")
        
        # 1. Start the UDP Listener (Background Ear)
        threading.Thread(target=self.udp_listener, daemon=True).start()
        
        # 2. Start the Main State Machine (The Brain)
        threading.Thread(target=self.run_state_machine, daemon=True).start()

    # =================================================================
    #  PART 1: UDP Listener (The "Always-On" Mesh Receiver)
    # =================================================================
    def udp_listener(self):
        print(f"[UDP] Listening on port {self.my_udp_port}")
        while not self.stop_event.is_set():
            msg, addr = receive_udp_message(self.udp_sock)
            if not msg: continue
            
            m_type = msg['type']
            sender = msg['sender']
            
            # Ignore messages from myself
            if sender == self.my_id:
                continue

            if m_type == TYPE_ELECTION:
                # Someone lower than me wants to be leader. 
                # 1. Bully them back (Send ANSWER)
                print(f"[UDP] Received ELECTION from {sender}. Sending ANSWER.")
                self._send_udp_to_id(sender, TYPE_ANSWER)
                
                # 2. If I am not already trying to be leader, I should start an election 
                #    because I am bigger than them!
                if self.state != STATE_LEADER and self.state != STATE_ELECTION:
                    self._trigger_election("Challenged by lower node")

            elif m_type == TYPE_ANSWER:
                # Someone higher is alive.
                print(f"[UDP] Received ANSWER from {sender}.")
                with self.lock:
                    self.received_answer = True

            elif m_type == TYPE_COORDINATOR:
                # Someone declared victory.
                print(f"[UDP] {sender} declared COORDINATOR.")
                with self.lock:
                    self.current_leader_id = sender
                    self.state = STATE_FOLLOWER
                    self.election_trigger.set() # Interrupt any waiting

    # =================================================================
    #  PART 2: State Machine (Follower -> Election -> Leader)
    # =================================================================
    def run_state_machine(self):
        # Wait and listen for existing leader before starting election
        print(f"[Consensus] Waiting for existing leader announcement...")
        discovery_timeout = 3.0  # Wait 3 seconds to discover existing leader
        start_time = time.time()
        
        while time.time() - start_time < discovery_timeout:
            if self.current_leader_id is not None:
                # Leader discovered via UDP COORDINATOR message
                print(f"[Consensus] Discovered existing leader: {self.current_leader_id}")
                break
            time.sleep(0.2)
        
        # If no leader found, start election
        if self.current_leader_id is None:
            print(f"[Consensus] No existing leader found. Starting election...")
            self._trigger_election("Startup - No leader detected")

        while not self.stop_event.is_set():
            if self.state == STATE_FOLLOWER:
                self.handle_follower()
            elif self.state == STATE_ELECTION:
                self.handle_election()
            elif self.state == STATE_LEADER:
                self.handle_leader()
            time.sleep(0.1)

    # --- Role: FOLLOWER ---
    def handle_follower(self):
        leader_id = self.current_leader_id
        
        # If no leader known, start election
        if leader_id is None:
            self._trigger_election("No leader known")
            return

        # Don't connect to myself
        if leader_id == self.my_id:
            self.state = STATE_LEADER
            return

        # 1. Get Leader IP/Port
        leader_info = next(s for s in self.peers if s['id'] == leader_id)
        
        # 2. Retry connection with exponential backoff (leader might be starting TCP server)
        max_retries = 5
        retry_delay = 0.5
        sock = None
        
        for attempt in range(max_retries):
            if self.state != STATE_FOLLOWER:
                return # State changed, abort
                
            try:
                print(f"[Follower] Connecting to Leader {leader_id} (attempt {attempt + 1}/{max_retries})...")
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0) # Connection timeout
                sock.connect((leader_info['host'], leader_info['tcp_port']))
                print(f"[Follower] Connected to Leader {leader_id} (TCP).")
                break # Connection successful
            except (ConnectionRefusedError, socket.timeout, OSError) as e:
                if sock:
                    sock.close()
                    sock = None
                if attempt < max_retries - 1:
                    print(f"[Follower] Connection failed, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2 # Exponential backoff
                else:
                    print(f"[Follower] Leader {leader_id} unreachable after {max_retries} attempts")
                    self.current_leader_id = None
                    self._trigger_election("Leader connection failed")
                    return
        
        if not sock:
            return
            
        try:
            # 3. Listen for Heartbeats loop
            while self.state == STATE_FOLLOWER:
                sock.settimeout(HEARTBEAT_INTERVAL * 3) # Heartbeat timeout
                msg = receive_tcp_message(sock)
                
                if msg is None:
                    raise Exception("Connection closed by Leader")
                
                if msg['type'] == TYPE_HEARTBEAT:
                    # Reset timeout timer implicitly by loop continuing
                    # print(f"[Heartbeat] from Leader {leader_id}")
                    pass
                    
        except Exception as e:
            print(f"[Follower] Leader {leader_id} failed: {e}")
            self.current_leader_id = None
            self._trigger_election("Leader TCP connection failed")
        finally:
            if sock:
                sock.close()

    # --- Role: CANDIDATE (Election) ---
    def handle_election(self):
        print(f"[Election] Started. I am ID={self.my_id}")
        
        with self.lock:
            self.received_answer = False
            self.election_trigger.clear()

        # 1. Find higher nodes
        higher_peers = [p for p in self.peers if p['id'] > self.my_id]
        
        if not higher_peers:
            print("[Election] No higher peers. I am the winner!")
            self._become_leader()
            return

        # 2. Send ELECTION (UDP) to all higher nodes
        for p in higher_peers:
            self._send_udp_to_id(p['id'], TYPE_ELECTION)

        # 3. Wait for ANSWER
        # We wait in small chunks to allow interruption by election_trigger (if Coordinator msg arrives)
        start_time = time.time()
        while time.time() - start_time < TIMEOUT_ELECTION:
            if self.received_answer or self.state != STATE_ELECTION:
                break
            time.sleep(0.1)

        # 4. Check results
        if self.state != STATE_ELECTION:
            return # Someone else became leader via UDP listener

        if not self.received_answer:
            # No one replied. I win.
            print("[Election] Timeout. No ANSWER received. I am taking over.")
            self._become_leader()
        else:
            # Received Answer. Wait for Coordinator message.
            print("[Election] Received ANSWER. Waiting for Coordinator...")
            # Wait for X seconds for the winner to announce themselves
            start_time = time.time()
            while time.time() - start_time < TIMEOUT_COORDINATOR:
                if self.state != STATE_ELECTION: return # Coordinator arrived
                time.sleep(0.1)
            
            # If we waited and no Coordinator arrived, restart election
            print("[Election] Coordinator timeout. Restarting election.")
            self._trigger_election("Coordinator timeout")

    # --- Role: LEADER ---
    def handle_leader(self):
        print(f"[Leader] I am the LEADER (ID={self.my_id}). Starting TCP Server...")
        self.current_leader_id = self.my_id
        
        # 1. Start TCP Server Socket for Heartbeats
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_sock.bind(('0.0.0.0', self.my_tcp_port))
            server_sock.listen(5)
            server_sock.settimeout(1.0) # Non-blocking accept
            
            followers = []
            heartbeat_counter = 0
            
            while self.state == STATE_LEADER:
                # A. Accept new followers
                try:
                    conn, addr = server_sock.accept()
                    print(f"[Leader] Follower connected: {addr}")
                    followers.append(conn)
                except socket.timeout:
                    pass # Just loop to send heartbeats
                
                # B. Send Heartbeats to all
                msg = {'type': TYPE_HEARTBEAT, 'sender': self.my_id}
                
                # Iterate copy of list to remove dead ones safely
                for conn in followers[:]:
                    try:
                        send_tcp_message(conn, msg)
                    except:
                        # Follower disconnected
                        conn.close()
                        followers.remove(conn)
                
                # C. Periodically broadcast COORDINATOR (for new servers joining)
                heartbeat_counter += 1
                if heartbeat_counter % 5 == 0:  # Every 5 heartbeats (5 seconds)
                    for p in self.peers:
                        if p['id'] != self.my_id:
                            self._send_udp_to_id(p['id'], TYPE_COORDINATOR)
                        
                time.sleep(HEARTBEAT_INTERVAL)
                
        except Exception as e:
            print(f"[Leader] Error: {e}")
            self.state = STATE_FOLLOWER # Demote myself on error
        finally:
            server_sock.close()
            print("[Leader] TCP Server stopped.")

    # --- Helpers ---
    def _trigger_election(self, reason):
        print(f"[Consensus] Triggering Election: {reason}")
        self.state = STATE_ELECTION
        
    def _become_leader(self):
        self.state = STATE_LEADER
        self.current_leader_id = self.my_id
        # Broadcast Victory (UDP) - Retry 3 times
        for _ in range(3):
            for p in self.peers:
                if p['id'] != self.my_id:
                    self._send_udp_to_id(p['id'], TYPE_COORDINATOR)
            time.sleep(0.05)

    def _send_udp_to_id(self, target_id, msg_type):
        target = next(p for p in self.peers if p['id'] == target_id)
        msg = {'type': msg_type, 'sender': self.my_id}
        send_udp_message(self.udp_sock, msg, target['host'], target['udp_port'])