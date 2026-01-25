import threading 
import socket
import queue
import sys 
import os


# Get the absolute path of the directory containing this script
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (which should maintain 'network' folder)
parent_dir = os.path.dirname(current_dir)   
sys.path.append(parent_dir)

from network.messenger import send_message, receive_message
from common.vector_clock import VectorClock
from common.protocol import TYPE_JOIN, TYPE_CHAT, TYPE_LEAVE, TYPE_UPDATE, safe_print

class ChatServer:
    """the class for chat server(currently it's statistical server for testing)"""
    def __init__(self, host = '0.0.0.0', port = 6000): 
        self.host = host
        self.port = port
        
        self.clients = []  
        self.msg_queue = queue.Queue()
        self.lock = threading.Lock()

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.vector_clock = VectorClock("chatting group TEST SERVER")  #the server's vector clock

    def start(self):
        """start the server to accept clients"""
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            print(f"Server started at {self.host}:{self.port}")

            #starting the multicast thread
            threading.Thread(target=self.multicast_thread, daemon=True).start()

            #the main thread to accept clients
            while True:
                client_socket, client_address = self.server_socket.accept()
                print(f"New connection from {client_address}")

                with self.lock:
                   self.clients.append(client_socket)
                
                #create a unique thread for the client 
                threading.Thread(target=self.unique_client_thread, args=(client_socket, client_address), daemon=True).start()

        except KeyboardInterrupt:
            print("Server is shutting down.")
        finally:
            self.server_socket.close()

    def unique_client_thread(self, client_socket, client_address):
        """this thread recieves messages from a unique client and puts them into the message queue"""
        try:
            while True:
                message = receive_message(client_socket)
                if message is None:
                    print(f"Connection closed by {client_address}")
                    break
                print(f"Received from {client_address}: {message}")
                
                # FIX: Update vector clock BEFORE putting to queue
                # Use lock to protect shared vector_clock state
                if message['type'] == TYPE_JOIN: 
                    with self.lock:
                        self.vector_clock.add_entry(message['sender'])

                self.msg_queue.put((client_socket, message))

        finally:
            with self.lock:
                if client_socket in self.clients:
                    self.clients.remove(client_socket)
            client_socket.close()

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
                            send_message(client, join_msg)
                        else:
                            if client != sender_socket:
                                send_message(client, message)
                    except Exception as e:
                            print(f"Error while sending to a client: {e}")

            self.msg_queue.task_done()

    def remove_client(self, client_socket):
        """remove a client from the clients list"""
        with self.lock:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
                client_socket.close()
   
if __name__ == "__main__":
    server = ChatServer()
    server.start()



