import threading 
import socket
import queue
import json
import struct
from utills.logger import get_logger
from common.vector_clock import VectorClock
from common.protocol import TYPE_JOIN, TYPE_CHAT, TYPE_LEAVE, TYPE_UPDATE, encode_message, decode_message

logger = get_logger("chatroom")

HEADER_FORMAT = '!I'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

class ChatroomManager:
    """
    Manages chatrooms and client connections.
    Handles causal ordering with vector clocks.
    """
    def __init__(self, server_id, client_port, host='0.0.0.0'):
        self.server_id = server_id
        self.client_port = client_port
        self.host = host
        
        self.clients = []  # List of connected client sockets
        self.msg_queue = queue.Queue()  # Message queue for multicast
        self.lock = threading.Lock()
        
        # Server's vector clock for tracking client states
        self.vector_clock = VectorClock()
        
        # TCP server socket for clients
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # For macOS/BSD: SO_REUSEPORT allows multiple servers on same port
        if hasattr(socket, 'SO_REUSEPORT'):
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        
        self.stop_event = threading.Event()

    def start(self):
        """Start the chatroom server"""
        try:
            self.server_socket.bind((self.host, self.client_port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)
            logger.info(f"ChatroomManager listening on port {self.client_port}")
            
            # Start multicast thread
            threading.Thread(target=self.multicast_thread, daemon=True).start()
            
            # Accept clients loop
            while not self.stop_event.is_set():
                try:
                    client_socket, client_address = self.server_socket.accept()
                    logger.info(f"Client connected from {client_address}")
                    
                    with self.lock:
                        self.clients.append(client_socket)
                    
                    # Handle client in separate thread
                    threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, client_address),
                        daemon=True
                    ).start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if not self.stop_event.is_set():
                        logger.error(f"Accept error: {e}")
        
        except Exception as e:
            logger.error(f"ChatroomManager error: {e}")
        finally:
            self.server_socket.close()
            logger.info("ChatroomManager stopped")

    def handle_client(self, client_socket, client_address):
        """Handle messages from a single client"""
        try:
            while not self.stop_event.is_set():
                message = self._receive_tcp_message(client_socket)
                if message is None:
                    logger.info(f"Connection closed by {client_address}")
                    break
                
                logger.debug(f"Received from {client_address}: {message}")
                
                # Update vector clock
                if message['type'] == TYPE_JOIN:
                    with self.lock:
                        self.vector_clock.add_entry(message['sender'])
                        self.vector_clock.merge(message['vector_clock'])
                        logger.info(f"Client {message['sender']} joined. Clock: {self.vector_clock.clock}")
                
                with self.lock:
                    self.vector_clock.merge(message['vector_clock'])
                
                # Put message in queue for multicast
                self.msg_queue.put((client_socket, message))
        
        except Exception as e:
            logger.error(f"Client handler error: {e}")
        finally:
            with self.lock:
                if client_socket in self.clients:
                    self.clients.remove(client_socket)
            client_socket.close()

    def multicast_thread(self):
        """Multicast messages to all clients except sender"""
        while not self.stop_event.is_set():
            try:
                sender_socket, message = self.msg_queue.get(timeout=1.0)
                
                with self.lock:
                    for client in list(self.clients):
                        try:
                            if message['type'] == TYPE_JOIN:
                                # Send JOIN to all clients with server's vector clock
                                join_msg = message.copy()
                                join_msg['vector_clock'] = self.vector_clock.copy()
                                self._send_tcp_message(client, join_msg)
                            else:
                                # Send to all except sender
                                if client != sender_socket:
                                    self._send_tcp_message(client, message)
                        except Exception as e:
                            logger.error(f"Error sending to client: {e}")
                
                self.msg_queue.task_done()
            except queue.Empty:
                continue

    def remove_client(self, client_socket):
        """Remove a client from the clients list"""
        with self.lock:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
                client_socket.close()

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

    def stop(self):
        """Stop the chatroom manager"""
        self.stop_event.set()
        
        # Close all client connections
        with self.lock:
            for client in list(self.clients):
                try:
                    client.close()
                except:
                    pass
            self.clients.clear()
        
        # Close server socket
        try:
            self.server_socket.close()
        except:
            pass
        
        logger.info("ChatroomManager stopped")
