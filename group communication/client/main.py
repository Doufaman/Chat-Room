#This file is to run clients 
import socket 
import sys
import os
import threading
import time 
import random

# Adjust the path to include the parent directory for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from network.messenger import send_message, receive_message
from common.protocol import set_message, TYPE_JOIN, TYPE_CHAT, TYPE_LEAVE, safe_print
from common.vector_clock import VectorClock

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 6000

class ChatClient:
    """client for chat room"""
    def __init__(self, userid):
        self.userid = userid
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.vector_clock = VectorClock(userid)
        self.msg_queue = [] # Hold-back queue for Causal Ordering
        self.lock = threading.Lock() # Mutex for vector_clock and msg_queue

    def join_server(self, server_host=SERVER_HOST, server_port=SERVER_PORT):
        try:
            self.client_socket.connect((server_host, server_port))
            print(f"Client {self.userid} connected to server at {server_host}:{server_port}")
            
            # Send JOIN message
            # Note: Initial clock {Me: 0} is sufficient
            msg = set_message(TYPE_JOIN, self.userid, self.vector_clock, f"NOTE: {self.userid} joined the chat.")
            send_message(self.client_socket, msg)
            
            # Start receiving thread
            threading.Thread(target=self.receive_messages, daemon=True).start()
            
            # Start main loop
            self.main_thread()
            
        except Exception as e:
            print(f"Error connecting to server: {e}")
            self.client_socket.close()

    def receive_messages(self):
        """Receives messages from server, handles logic in lock, delivers outside lock"""
        try:
            while True:
                message = receive_message(self.client_socket)
                if message is None:
                    safe_print("Connection closed by the server.")
                    os._exit(0) # Force exit

                sender = message['sender']
                received_clock = message['vector_clock']
                msg_type = message['type']
                
                # --- CRITICAL SECTION START ---
                messages_to_deliver = []
                
                with self.lock:
                    # 1. Handle JOIN: Update membership immediately
                    if msg_type == TYPE_JOIN:
                        self.vector_clock.add_entry(sender)
                        self.vector_clock.merge(received_clock)
                        # Debug print to confirm update
                        #safe_print(f" DEBUG: Added {sender}. New Clock: {self.vector_clock.clock}")
                        
                        # JOIN implies delivery immediately, no causal check needed usually
                        messages_to_deliver.append(message)
                        
                        # IMPORTANT: A JOIN might satisfy dependencies for held-back messages!
                        # So we check the buffer now.
                        messages_to_deliver.extend(self._check_buffer_locked())

                    # 2. Handle CHAT: Causal Ordering Check
                    elif msg_type == TYPE_CHAT:
                        if self.vector_clock.is_deliveravle(received_clock, sender):
                            self.vector_clock.merge(received_clock)
                            messages_to_deliver.append(message)
                            # Check if this delivery unlocks others
                            messages_to_deliver.extend(self._check_buffer_locked())
                        else:
                            # print(f" DEBUG: Hold back msg from {sender}. My: {self.vector_clock.clock} vs Msg: {received_clock}")
                            self.hold_back_queue.append(message) # Add to buffer

                # --- CRITICAL SECTION END ---

                # 3. Deliver (Print) OUTSIDE the lock
                # This prevents deadlock if safe_print blocks on I/O
                for msg in messages_to_deliver:
                    self.deliver(msg)
                    
        except Exception as e:
            safe_print(f"Error in receive_thread: {e}")

    def _check_buffer_locked(self):
        """Helper to scan hold-back queue. Must be called inside `with self.lock`"""
        deliverable = []
        # Use queue copy to allow modification during iteration if needed, 
        # though here we rebuild the queue or remove carefully.
        # Simple algorithm: repeatedly scan until no progress.
        
        while True:
            progress = False
            # Iterate a copy of the list so we can modify the original
            for i, message in enumerate(list(self.hold_back_queue)):
                sender = message['sender']
                received_clock = message['vector_clock']
                
                if self.vector_clock.is_deliveravle(received_clock, sender):
                    self.vector_clock.merge(received_clock)
                    deliverable.append(message)
                    self.hold_back_queue.remove(message)
                    progress = True
                    break # Restart scan to maintain order logic safely
            
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
        safe_print(f"Welcome {self.userid}! Type your messages below.")
        
        while True:
            try:
                # Use sys.stdin to correspond with safe_print's raw stdout manipulation
                sys.stdout.write("Your message: ")
                sys.stdout.flush()
                
                line = sys.stdin.readline()
                if not line:
                    break
                
                content = line.strip()
                if not content:
                    continue

                # --- CRITICAL SECTION START ---
                # Only lock for Clock Update
                with self.lock:
                    self.vector_clock.increment()
                    # Deep copy the clock state to ensure thread safety during sending
                    # Assuming .clock is a dict
                    clock_snapshot = self.vector_clock.clock.copy() 
                    # If VectorClock.copy() returns object, use that. 
                    # Based on errors, passing raw dict is safest for set_message
                # --- CRITICAL SECTION END ---

                # Send OUTSIDE the lock
                # Construct message with the SNAPSHOT of the clock
                # create a dummy object or modify set_message to accept dict if needed
                # Ideally: set_message calls .copy(), so we pass a temp object or ensure it works.
                
                # To be safe: pass the object, but we already released lock. 
                # Wait, if we pass self.vector_clock now, it might change!
                # Hack: Update the clock used in message manually
                msg = set_message(TYPE_CHAT, self.userid, self.vector_clock, content)
                # OOPS: set_message calls vector_clock.copy(). 
                # To be strict, we should force it to use our snapshot.
                msg['vector_clock'] = clock_snapshot # Override with the locked snapshot
                
                send_message(self.client_socket, msg)
                
            except KeyboardInterrupt:
                safe_print("\nExiting...")
                self.client_socket.close()
                break
            except Exception as e:
                safe_print(f"Error sending: {e}")

    # Compatibility: Add missing attribute if older code uses it
    @property
    def hold_back_queue(self):
        if not hasattr(self, 'msg_queue'):
            self.msg_queue = []
        return self.msg_queue
    
    @hold_back_queue.setter
    def hold_back_queue(self, val):
        self.msg_queue = val

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python main.py <userid>")
        sys.exit(1)
    
    userid = sys.argv[1]
    client = ChatClient(userid)
    client.join_server()
