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

SERVER_HOST = '0.0.0.0'
SERVER_PORT = 6000

TEST_DELAY = False  #Set to True to enable random delay for testing

class ChatClient:
    """client for chat room"""
    def __init__(self, userid):
        self.userid = userid
        self.vector_clock = VectorClock(client_id=userid)
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.hold_back_queue = []
        self.lock = threading.Lock()

    def join_server(self, server_host=SERVER_HOST, server_port=SERVER_PORT):
        """connect to the server"""
        self.client_socket.connect((server_host, server_port))
        print(f"Client {self.userid} connected to server at {server_host}:{server_port}")

        join_msg = set_message(TYPE_JOIN, self.userid, self.vector_clock, '{} joined the chat.'.format(self.userid))
        send_message(self.client_socket, join_msg)

        receiving_thread = threading.Thread(target=self.receive_messages, daemon=True).start()
        self.main_thread()

    def main_thread(self):
        """this main thread sending messages to server"""
        try:
            # First time prompt 
            sys.stdout.write("Enter Message: ") 
            sys.stdout.flush()

            while True:
                # We can't use input() because it conflicts with safe_print
                # Instead, use sys.stdin which is also blocking
                user_input = sys.stdin.readline().strip() 
                
                # Move cursor up one line to overwrite the input we just typed to keep interface clean (Optional)
                # sys.stdout.write("\033[F") 

                if user_input:
                    with self.lock:
                        self.vector_clock.increment()
                        
                    chat_msg = set_message(TYPE_CHAT, self.userid, self.vector_clock, user_input)
                    send_message(self.client_socket, chat_msg)
                
                # Re-print prompt after sending
                sys.stdout.write("Enter Message: ")
                sys.stdout.flush() 

        except KeyboardInterrupt:
            print("Client is shutting down.")
        finally:
            self.client_socket.close()

    def receive_messages(self):
        """this thread receives messages from server"""
        while True:
                message = receive_message(self.client_socket)
                if message is None:
                    print("Connection closed by the server.")
                    break

                sender = message['sender']
                received_clock = message['vector_clock']

                if message['type'] == TYPE_JOIN:
                    safe_print(f"{sender} has joined the chat.")

                else:    
                    with self.lock:
                        # For a newly joined client, it should firstly gets the latest vector clock from others
                        if message['type'] == TYPE_JOIN:
                            self.vector_clock.merge(received_clock)

                        if self.vector_clock.is_deliveravle(received_clock, sender):
                            self.vector_clock.merge(received_clock)
                            self.deliver(message)
                            self.check_buffer()

                        else:
                            print(f"Message from {sender} is not deliverable, added to hold-back queue.")
                            self.hold_back_queue.append(message)

    def check_buffer(self):
        """scan the hold-back queue to see if any message is now deliverable"""
        while True:
            progress_made = False
            for message in self.hold_back_queue:
                sender = message['sender']
                received_clock = message['vector_clock']

                if self.vector_clock.is_deliveravle(received_clock, sender):
                    self.vector_clock.merge(received_clock)
                    self.deliver(message)
                    self.hold_back_queue.remove(message)
                    progress_made = True
                    break

                if not progress_made:
                    break

    def deliver(self, message):
        """deliver the message to the application layer (print it out)"""
        self.vector_clock.merge(message['vector_clock'])
        safe_print(f"{message['sender']} said: {message['content']}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python main.py <user_id>")
        sys.exit(1)

    user_id = sys.argv[1]
    client = ChatClient(user_id)
    client.join_server()
                        