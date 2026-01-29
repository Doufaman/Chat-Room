import threading
import time
import socket
import json
from common.protocol import *
from network.network_manager import NetworkManager

# --- Configuration Constants ---
TIMEOUT_ELECTION = 2.0   # How long to wait for ANSWER
TIMEOUT_COORDINATOR = 4.0 # How long to wait for COORDINATOR after receiving ANSWER
HEARTBEAT_INTERVAL = 1.0 # Leader sends heartbeat every 1s

# --- States of servers ---
STATE_FOLLOWER = "FOLLOWER"
STATE_ELECTION = "ELECTION"
STATE_LEADER = "LEADER"

class ConsensusManager:
    """
    Manages leader election using Bully Algorithm.
    Integrated with the existing NetworkManager.
    """
    def __init__(self, my_id, my_ip, peers_config):
        """
        Initialize Consensus Manager
        :param my_id: Server ID
        :param my_ip: Server IP address
        :param peers_config: List of peer server configurations
        """
        self.my_id = my_id
        self.my_ip = my_ip
        self.peers = peers_config  # List of dicts with 'id', 'host', 'tcp_port', 'udp_port'
        
        # Extract my own config
        my_info = next((s for s in self.peers if s['id'] == self.my_id), None)
        if not my_info:
            raise ValueError(f"Server ID {my_id} not found in peers config")
        
        self.my_udp_port = my_info['udp_port']
        self.my_tcp_port = my_info['tcp_port']
        
        # State Variables
        self.state = STATE_FOLLOWER
        self.current_leader_id = None
        self.stop_event = threading.Event()
        
        # UDP Socket for Election/Coordination
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # For macOS/BSD: SO_REUSEPORT is required for multiple processes on same port
        if hasattr(socket, 'SO_REUSEPORT'):
            self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.udp_sock.bind(('0.0.0.0', self.my_udp_port))
        
        # Coordination Flags (Thread-Safe)
        self.lock = threading.Lock()
        self.received_answer = False
        self.election_trigger = threading.Event()

    def start(self):
        """Start the consensus module"""
        print(f"[Consensus] Node {self.my_id} starting...")
        
        # Start UDP listener for election messages
        threading.Thread(target=self.udp_listener, daemon=True).start()
        
        # Start state machine
        threading.Thread(target=self.run_state_machine, daemon=True).start()

    def udp_listener(self):
        """Listen for UDP election/coordination messages"""
        print(f"[UDP] Listening on port {self.my_udp_port}")
        while not self.stop_event.is_set():
            try:
                data, addr = self.udp_sock.recvfrom(4096)
                msg = json.loads(data.decode('utf-8'))
                
                m_type = msg.get('type')
                sender = msg.get('sender')
                
                # Ignore messages from myself
                if sender == self.my_id:
                    continue

                if m_type == TYPE_ELECTION:
                    print(f"[UDP] Received ELECTION from {sender}. Sending ANSWER.")
                    self._send_udp_to_id(sender, TYPE_ANSWER)
                    
                    # If not already in election or leader, start election
                    if self.state != STATE_LEADER and self.state != STATE_ELECTION:
                        self._trigger_election("Challenged by lower node")

                elif m_type == TYPE_ANSWER:
                    print(f"[UDP] Received ANSWER from {sender}.")
                    with self.lock:
                        self.received_answer = True

                elif m_type == TYPE_COORDINATOR:
                    print(f"[UDP] {sender} declared COORDINATOR.")
                    with self.lock:
                        self.current_leader_id = sender
                        self.state = STATE_FOLLOWER
                        self.election_trigger.set()
            except Exception as e:
                if not self.stop_event.is_set():
                    print(f"[UDP] Error: {e}")

    def run_state_machine(self):
        """Main state machine loop"""
        # Wait for existing leader
        print(f"[Consensus] Waiting for existing leader announcement...")
        discovery_timeout = 3.0
        start_time = time.time()
        
        while time.time() - start_time < discovery_timeout:
            if self.current_leader_id is not None:
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

    def handle_follower(self):
        """Follower state: connect to leader and receive heartbeats"""
        leader_id = self.current_leader_id
        
        if leader_id is None:
            self._trigger_election("No leader known")
            return

        if leader_id == self.my_id:
            self.state = STATE_LEADER
            return

        # Get leader info
        leader_info = next((s for s in self.peers if s['id'] == leader_id), None)
        if not leader_info:
            self._trigger_election("Leader info not found")
            return
        
        # Connect to leader with retry
        max_retries = 5
        retry_delay = 0.5
        sock = None
        
        for attempt in range(max_retries):
            if self.state != STATE_FOLLOWER:
                return
                
            try:
                print(f"[Follower] Connecting to Leader {leader_id} (attempt {attempt + 1}/{max_retries})...")
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect((leader_info['host'], leader_info['tcp_port']))
                print(f"[Follower] Connected to Leader {leader_id} (TCP).")
                break
            except (ConnectionRefusedError, socket.timeout, OSError) as e:
                if sock:
                    sock.close()
                    sock = None
                if attempt < max_retries - 1:
                    print(f"[Follower] Connection failed, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    print(f"[Follower] Leader {leader_id} unreachable after {max_retries} attempts")
                    self.current_leader_id = None
                    self._trigger_election("Leader connection failed")
                    return
        
        if not sock:
            return
            
        try:
            while self.state == STATE_FOLLOWER:
                sock.settimeout(HEARTBEAT_INTERVAL * 3)
                msg = self._receive_tcp_message(sock)
                
                if msg is None:
                    raise Exception("Connection closed by Leader")
                
                if msg.get('type') == TYPE_HEARTBEAT:
                    pass  # Heartbeat received
                    
        except Exception as e:
            print(f"[Follower] Leader {leader_id} failed: {e}")
            self.current_leader_id = None
            self._trigger_election("Leader TCP connection failed")
        finally:
            if sock:
                sock.close()

    def handle_election(self):
        """Election state: run Bully algorithm"""
        print(f"[Election] Started. I am ID={self.my_id}")
        
        with self.lock:
            self.received_answer = False
            self.election_trigger.clear()

        # Find higher nodes
        higher_peers = [p for p in self.peers if p['id'] > self.my_id]
        
        if not higher_peers:
            print("[Election] No higher peers. I am the winner!")
            self._become_leader()
            return

        # Send ELECTION to all higher nodes
        for p in higher_peers:
            self._send_udp_to_id(p['id'], TYPE_ELECTION)

        # Wait for ANSWER
        start_time = time.time()
        while time.time() - start_time < TIMEOUT_ELECTION:
            if self.received_answer or self.state != STATE_ELECTION:
                break
            time.sleep(0.1)

        # Check results
        if self.state != STATE_ELECTION:
            return

        if not self.received_answer:
            print("[Election] Timeout. No ANSWER received. I am taking over.")
            self._become_leader()
        else:
            print("[Election] Received ANSWER. Waiting for Coordinator...")
            start_time = time.time()
            while time.time() - start_time < TIMEOUT_COORDINATOR:
                if self.state != STATE_ELECTION:
                    return
                time.sleep(0.1)
            
            print("[Election] Coordinator timeout. Restarting election.")
            self._trigger_election("Coordinator timeout")

    def handle_leader(self):
        """Leader state: accept followers and send heartbeats"""
        print(f"[Leader] I am the LEADER (ID={self.my_id}). Starting TCP Server...")
        self.current_leader_id = self.my_id
        
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_sock.bind(('0.0.0.0', self.my_tcp_port))
            server_sock.listen(5)
            server_sock.settimeout(1.0)
            
            followers = []
            heartbeat_counter = 0
            
            while self.state == STATE_LEADER:
                # Accept new followers
                try:
                    conn, addr = server_sock.accept()
                    print(f"[Leader] Follower connected: {addr}")
                    followers.append(conn)
                except socket.timeout:
                    pass
                
                # Send heartbeats
                msg = {'type': TYPE_HEARTBEAT, 'sender': self.my_id}
                
                for conn in followers[:]:
                    try:
                        self._send_tcp_message(conn, msg)
                    except:
                        conn.close()
                        followers.remove(conn)
                
                # Periodically broadcast COORDINATOR
                heartbeat_counter += 1
                if heartbeat_counter % 5 == 0:
                    for p in self.peers:
                        if p['id'] != self.my_id:
                            self._send_udp_to_id(p['id'], TYPE_COORDINATOR)
                        
                time.sleep(HEARTBEAT_INTERVAL)
                
        except Exception as e:
            print(f"[Leader] Error: {e}")
            self.state = STATE_FOLLOWER
        finally:
            server_sock.close()
            print("[Leader] TCP Server stopped.")

    def _trigger_election(self, reason):
        """Trigger a new election"""
        print(f"[Consensus] Triggering Election: {reason}")
        self.state = STATE_ELECTION
        
    def _become_leader(self):
        """Become the leader and broadcast victory"""
        self.state = STATE_LEADER
        self.current_leader_id = self.my_id
        # Broadcast victory
        for _ in range(3):
            for p in self.peers:
                if p['id'] != self.my_id:
                    self._send_udp_to_id(p['id'], TYPE_COORDINATOR)
            time.sleep(0.05)

    def _send_udp_to_id(self, target_id, msg_type):
        """Send UDP message to a peer"""
        target = next((p for p in self.peers if p['id'] == target_id), None)
        if target:
            msg = {'type': msg_type, 'sender': self.my_id}
            data = json.dumps(msg).encode('utf-8')
            self.udp_sock.sendto(data, (target['host'], target['udp_port']))

    def _send_tcp_message(self, sock, message):
        """Send TCP message with length prefix"""
        import struct
        HEADER_FORMAT = '!I'
        pkg_body = json.dumps(message).encode('utf-8')
        pkg_header = struct.pack(HEADER_FORMAT, len(pkg_body))
        sock.sendall(pkg_header + pkg_body)

    def _receive_tcp_message(self, sock):
        """Receive TCP message with length prefix"""
        import struct
        HEADER_FORMAT = '!I'
        HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
        
        header = self._read_exact(sock, HEADER_SIZE)
        if not header:
            return None
        
        body_len = struct.unpack(HEADER_FORMAT, header)[0]
        body = self._read_exact(sock, body_len)
        if not body:
            return None
        
        return json.loads(body.decode('utf-8'))

    def _read_exact(self, sock, n):
        """Read exactly n bytes from socket"""
        data = bytearray()
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:
                return None
            data.extend(packet)
        return bytes(data)

    def stop(self):
        """Stop the consensus module"""
        self.stop_event.set()
        self.udp_sock.close()
