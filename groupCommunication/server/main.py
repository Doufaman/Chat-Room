import threading 
import socket
import queue
import sys 
import os
import json
import signal


# Get the absolute path of the directory containing this script
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (which should maintain 'network' folder)
parent_dir = os.path.dirname(current_dir)   
sys.path.append(parent_dir)

from network.messenger import send_tcp_message, receive_tcp_message
from common.vector_clock import VectorClock
from common.protocol import TYPE_JOIN, TYPE_CHAT, TYPE_LEAVE, TYPE_UPDATE, safe_print
from server.consensus import ConsensusManager

# Global flag for graceful shutdown
STOP_EVENT = threading.Event()

class ChatServer:
    """the class for chat server with consensus-based leader election"""
    def __init__(self, my_id, config, consensus_mgr): 
        self.my_id = my_id
        self.config = config
        self.consensus = consensus_mgr
        
        # Calculate my port for Clients (Base + ID)
        # e.g., Base 8000, ID 1 -> Port 8001
        self.client_port = config.get('client_port_base', 6000) + self.my_id
        self.host = '0.0.0.0'
        
        self.clients = []  
        self.msg_queue = queue.Queue()
        self.lock = threading.Lock()

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.vector_clock = VectorClock()  #the server's vector clock

    def start(self):
        """start the server to accept clients"""
        try:
            self.server_socket.bind((self.host, self.client_port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0) # Non-blocking accept for graceful shutdown
            print(f"[*] Chat Server {self.my_id} listening for CLIENTS on port {self.client_port}")
            print(f"[*] Consensus Module running in background...")

            #starting the multicast thread
            threading.Thread(target=self.multicast_thread, daemon=True).start()

            #the main thread to accept clients
            while not STOP_EVENT.is_set():
                try:
                    client_socket, client_address = self.server_socket.accept()
                    print(f"[+] Client connected from {client_address}")

                    with self.lock:
                       self.clients.append(client_socket)
                    
                    #create a unique thread for the client 
                    threading.Thread(target=self.unique_client_thread, args=(client_socket, client_address), daemon=True).start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if not STOP_EVENT.is_set():
                        print(f"[!] Accept error: {e}")

        except KeyboardInterrupt:
            print("\n[!] Server is shutting down.")
            STOP_EVENT.set()
        finally:
            self.server_socket.close()
            print("[*] Server stopped.")

    def unique_client_thread(self, client_socket, client_address):
        """this thread recieves messages from a unique client and puts them into the message queue"""
        try:
            while True:
                message = receive_tcp_message(client_socket)
                if message is None:
                    print(f"Connection closed by {client_address}")
                    break
                print(f"Received from {client_address}: {message}")
                
                # FIX: Update vector clock BEFORE putting to queue
                # Use lock to protect shared vector_clock state
                if message['type'] == TYPE_JOIN: 
                    with self.lock:
                        self.vector_clock.add_entry(message['sender'])
                        self.vector_clock.merge(message['vector_clock'])
                        print(f" DEBUG: (Server) Added {message['sender']}. New Clock: {self.vector_clock.clock}")

                with self.lock:
                    self.vector_clock.merge(message['vector_clock']) # Update server's vector clock

                self.msg_queue.put((client_socket, message))

        finally:
            with self.lock:
                if client_socket in self.clients:
                    self.clients.remove(client_socket)
            client_socket.close()

    def get_leader_info(self):
        """Get current leader information"""
        leader_id = self.consensus.current_leader_id
        if leader_id is None:
            return "No leader elected yet"
        elif leader_id == self.my_id:
            return f"I am the leader (Server {self.my_id})"
        else:
            return f"Current leader is Server {leader_id}"

    def multicast_thread(self):
        """this thread multicasts messages from the message queue to all clients except the sender"""
        while True:
            sender_socket, message = self.msg_queue.get()
            with self.lock:
                # Use a snapshot of clients list to be safe
                for client in list(self.clients):
                    try:
                            if message['type'] == TYPE_JOIN:
                                # FIX: Create a COPY of the message to avoid modifying the original dict in the queue
                                # sends the current vector clock of server to all clients (Sync point)
                                join_msg = message.copy()
                                join_msg['vector_clock'] = self.vector_clock.copy()
                                send_tcp_message(client, join_msg)
                            else:
                                if client != sender_socket:
                                    send_tcp_message(client, message)
                    except Exception as e:
                            print(f"Error while sending to a client: {e}")

            self.msg_queue.task_done()

    def remove_client(self, client_socket):
        """remove a client from the clients list"""
        with self.lock:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
                client_socket.close()
   
def signal_handler(sig, frame):
    """Handle Ctrl+C for graceful shutdown"""
    print("\n[!] Ctrl+C pressed. Exiting...")
    STOP_EVENT.set()
    sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python server/main.py <server_id>")
        print("Example: python server/main.py 1")
        sys.exit(1)

    my_id = int(sys.argv[1])
    
    # 1. Load Configuration
    config_path = os.path.join(parent_dir, 'config.json')
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        print(f"[*] Loaded config from {config_path}")
    except FileNotFoundError:
        print(f"[!] config.json not found at {config_path}")
        sys.exit(1)

    # 2. Start Consensus Module (Background)
    # This handles the UDP Election and TCP Heartbeats with other servers
    print(f"[*] Starting Consensus Manager for Server {my_id}...")
    consensus = ConsensusManager(my_id, config)
    consensus.start()

    # 3. Start Chat Service (Foreground)
    # This handles the Clients
    chat_server = ChatServer(my_id, config, consensus)
    
    # Handle Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    chat_server.start()



