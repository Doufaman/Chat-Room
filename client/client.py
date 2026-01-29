#This file is to run clients 
import socket 
import sys
import os
import threading
import time 
import struct

# Adjust the path to include the parent directory for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from common.protocol import set_client_message, TYPE_JOIN, TYPE_CHAT, TYPE_LEAVE, safe_print, encode_message, decode_message
from common.vector_clock import VectorClock

SERVER_HOST = '127.0.0.1'
CLIENT_PORT_BASE = 8000  # Must match server's client_port_base in config.json

HEADER_FORMAT = '!I'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

class ChatClient:
    """client for chat room"""
    def __init__(self, userid):
        self.userid = userid
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.vector_clock = VectorClock(userid)
        self.msg_queue = []  # Hold-back queue for Causal Ordering
        self.lock = threading.Lock()  # Mutex for vector_clock and msg_queue

    def join_server(self, server_id, server_host=SERVER_HOST):
        """Connect to a specific server by ID"""
        server_port = CLIENT_PORT_BASE + server_id
        try:
            print(f"Client {self.userid} connecting to Server {server_id} at {server_host}:{server_port}...")
            self.client_socket.connect((server_host, server_port))
            print(f"Client {self.userid} connected to Server {server_id}")
            
            # Send JOIN message
            msg = set_client_message(TYPE_JOIN, self.userid, self.vector_clock, f"NOTE: {self.userid} joined the chat.")
            self._send_tcp_message(self.client_socket, msg)
            
            # Start receiving thread
            threading.Thread(target=self.receive_messages, daemon=True).start()
            
            # Start main loop
            self.main_thread()
            
        except Exception as e:
            print(f"Error connecting to server: {e}")
            self.client_socket.close()

    def receive_messages(self):
        """Receives messages from server, handles causal ordering"""
        try:
            while True:
                message = self._receive_tcp_message(self.client_socket)
                if message is None:
                    safe_print("Connection closed by the server.")
                    os._exit(0)

                sender = message['sender']
                received_clock = message['vector_clock']
                msg_type = message['type']
                
                messages_to_deliver = []
                
                with self.lock:
                    # Handle JOIN: Update membership immediately
                    if msg_type == TYPE_JOIN:
                        self.vector_clock.add_entry(sender)
                        self.vector_clock.merge(received_clock)
                        messages_to_deliver.append(message)
                        messages_to_deliver.extend(self._check_buffer_locked())

                    # Handle CHAT: Causal Ordering Check
                    elif msg_type == TYPE_CHAT:
                        if self.vector_clock.is_deliveravle(received_clock, sender):
                            self.vector_clock.merge(received_clock)
                            messages_to_deliver.append(message)
                            messages_to_deliver.extend(self._check_buffer_locked())
                        else:
                            safe_print(f"[DEBUG] Hold back msg from {sender}. My: {self.vector_clock.clock} vs Msg: {received_clock}")
                            self.msg_queue.append(message)

                # Deliver messages outside the lock
                for msg in messages_to_deliver:
                    self.deliver(msg)
                    
        except Exception as e:
            safe_print(f"Error in receive_thread: {e}")

    def _check_buffer_locked(self):
        """Helper to scan hold-back queue. Must be called inside `with self.lock`"""
        deliverable = []
        
        while True:
            progress = False
            for i, message in enumerate(list(self.msg_queue)):
                sender = message['sender']
                received_clock = message['vector_clock']
                
                if self.vector_clock.is_deliveravle(received_clock, sender):
                    self.vector_clock.merge(received_clock)
                    deliverable.append(message)
                    self.msg_queue.remove(message)
                    progress = True
                    break
            
            if not progress:
                break
                
        return deliverable

    def deliver(self, message):
        """Deliver message to UI"""
        if message['type'] == TYPE_JOIN:
            safe_print(f"{message['sender']} has joined the chat.")
        elif message['type'] == TYPE_CHAT:
            safe_print(f"{message['sender']} said: {message['content']}")

    def main_thread(self):
        """Handles user input and sending"""
        safe_print(f"NOTE: Welcome {self.userid}! Type your messages below.")
        
        while True:
            try:
                content = input("Your message: ")
                
                with self.lock:
                    self.vector_clock.increment()
                    clock_snapshot = self.vector_clock.clock.copy()

                msg = set_client_message(TYPE_CHAT, self.userid, self.vector_clock, content)
                msg['vector_clock'] = clock_snapshot
                
                self._send_tcp_message(self.client_socket, msg)
                
            except KeyboardInterrupt:
                safe_print("\nExiting...")
                self.client_socket.close()
                break
            except Exception as e:
                safe_print(f"Error sending: {e}")

    def _send_tcp_message(self, sock, message):
        """Send TCP message with length prefix"""
        pkg_body = encode_message(message)
        pkg_header = struct.pack(HEADER_FORMAT, len(pkg_body))
        sock.sendall(pkg_header + pkg_body)

    def _receive_tcp_message(self, sock):
        """Receive TCP message with length prefix"""
        header = self._read_exact(sock, HEADER_SIZE)
        if not header:
            return None
        
        body_len = struct.unpack(HEADER_FORMAT, header)[0]
        body = self._read_exact(sock, body_len)
        if not body:
            return None
        
        return decode_message(body)

    def _read_exact(self, sock, n):
        """Read exactly n bytes from socket"""
        data = bytearray()
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:
                return None
            data.extend(packet)
        return bytes(data)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python client.py <userid> <server_id>")
        print("Example: python client.py Bob 1")
        print("         (connects to server 1)")
        sys.exit(1)
    
    userid = sys.argv[1]
    server_id = int(sys.argv[2])
    
    client = ChatClient(userid)
    client.join_server(server_id)
