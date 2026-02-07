'''
Implement the following functions:
    send and receive unicast(TCP)
    send and receive broadcast(UDP)
    send and receive multicast(UDP)
'''

import socket
import threading
import json
import struct
import time
from typing import Dict, Optional, Tuple

from utills.logger import get_logger

logger = get_logger("network_manager")

# these ports only uesd for receiving messages
PORT_UNICAST = 9001
PORT_BROADCAST = 9000
PORT_MULTICAST = 9002
PORT_ELECTION = 9003  # Dedicated port for election messages
PORT_LONG_LIVED = 9004  # Dedicated port for long-lived TCP connections (leader <-> followers)

IP_BROADCAST = '255.255.255.255'
IP_MULTICAST = '224.0.0.1'

# independent UDP socket functions 
def create_udp_socket(bind_ip, bind_port):
    """Create and bind a UDP socket."""
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, 'SO_REUSEPORT'):
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    udp_socket.bind((bind_ip, bind_port))
    return udp_socket

def send_udp_message(udp_socket, message_dict, dest_ip, dest_port):
    """Send a dictionary message via UDP socket (JSON encoded)."""
    try:
        pkg = json.dumps(message_dict, ensure_ascii=False).encode('utf-8')
        udp_socket.sendto(pkg, (dest_ip, dest_port))
    except Exception as e:
        print(f"[UDP] Send error: {e}")
        raise e

def receive_udp_message(udp_socket, buffer_size=4096):
    """Receive a JSON message from UDP socket."""
    try:
        pkg, addr = udp_socket.recvfrom(buffer_size)
        message_dict = json.loads(pkg.decode('utf-8'))
        return message_dict, addr
    except Exception as e:
        print(f"[UDP] Receive error: {e}")
        return None, None


class NetworkManager:
    def __init__(self, 
                 ip_local, 
                 port_unicast=PORT_UNICAST, 
                 port_broadcast=PORT_BROADCAST, 
                 ip_multicast= IP_MULTICAST, 
                 port_multicast=PORT_MULTICAST,
                 port_long_lived=PORT_LONG_LIVED,
                 server_id=None
                 ):
        self.server_id = server_id
        
        self.ip_local = ip_local
        self.port_unicast = port_unicast
        self.port_broadcast = port_broadcast
        self.ip_multicast = ip_multicast
        self.port_multicast = port_multicast
        self.port_long_lived = port_long_lived   # for long-lived TCP connections (leader <-> followers)

        # 消息回调映射（业务层通过这个获取数据）
        self.on_message_received = None 

        # long-lived connection registries (server_id -> socket)
        self._conn_lock = threading.RLock()
        self.serverid_to_conn: Dict[int, socket.socket] = {}    # registered by leader after identification
        self.conn_to_addr: Dict[socket.socket, Tuple[str,int]] = {}  # conn -> peer addr
        self.server_sock = None  # TCP server socket for leader to accept long-lived connections
        self._msg_callback = None  # callback for incoming messages from long-lived connections

    def set_callback(self, callback_func):
        """供 RoleManager 或 Leader 调用，设置消息回掉"""
        self._msg_callback = callback_func

    # message encode/decode functions
    def message_encode(self,  
                    message_type,
                    message):
        data = {"msg_type": message_type,
                "message": message,
                "sender_ip": self.ip_local
        }
        data_str = json.dumps(data, ensure_ascii=False)
        return data_str.encode()
    
    def message_decode(self, data):
        data_dic = json.loads(data.decode())
        message_type = data_dic.get("msg_type")
        message = data_dic.get("message")   
        sender_ip = data_dic.get("sender_ip")
        return message_type, message, sender_ip

    # TCP message header to prevent packet sticking problem
    HEADER_FORMAT = '!I'  # 4-byte unsigned integer for message length
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    def send_TCP_message(self, sock, message_type, message):
        """Send TCP message with length prefix to prevent sticking."""
        try:
            pkg_body = self.message_encode(message_type, message)
            pkg_header = struct.pack(self.HEADER_FORMAT, len(pkg_body))
            pkg = pkg_header + pkg_body
            sock.sendall(pkg)
        except Exception as e:
            print(f"[NetworkManager] TCP send error: {e}")
            raise e

    def receive_TCP_message(self, sock):
        """Receive TCP message with length prefix."""
        try:
            # Read header (4 bytes)
            pkg_header = self._read_exact(sock, self.HEADER_SIZE)
            if not pkg_header:
                return None  # Connection closed
            
            # Unpack message length
            body_len = struct.unpack(self.HEADER_FORMAT, pkg_header)[0]
            
            # Read exact message body
            pkg_body = self._read_exact(sock, body_len)
            if not pkg_body:
                return None  # Connection closed
            
            # Decode and return
            return self.message_decode(pkg_body)
        except Exception as e:
            print(f"[NetworkManager] TCP receive error: {e}")
            raise e

    def _read_exact(self, sock, n):
        """Helper to read exactly n bytes from socket."""
        data = bytearray()
        while len(data) < n:
            try:
                packet = sock.recv(n - len(data))
                if not packet:
                    return None  # Connection closed
                data.extend(packet)
            except OSError:
                return None
        return bytes(data)

    # send message functions
    def send_unicast(self, 
                     target_ip,
                     target_port, 
                     message_type,
                     message):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((self.ip_local,0)) # 让系统自动分配端口
                s.connect((target_ip, target_port))
                # Use TCP message with length header to prevent sticking
                self.send_TCP_message(s, message_type, message)
        except Exception as e:
            print(f"[NetworkManager] Unicast send error: {e}")

    def send_broadcast(self, 
                       message_type,
                       message):
        """UDP 广播发送"""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind(('',0)) # 让系统自动分配端口
            if hasattr(socket, 'SO_REUSEPORT'):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            data = self.message_encode(message_type, message)
            s.sendto(data, (IP_BROADCAST, self.port_broadcast))

    #没调好
    def send_multicast(self, message_type,message):
        """UDP 组播发送"""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, 'SO_REUSEPORT'):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            data = self.message_encode(message_type, message)
            s.sendto(data, (self.ip_multicast, self.port_multicast))
    

    # receive message functions
    def start_listening(self):
        threading.Thread(target=self.receive_unicast, daemon=True).start()
        threading.Thread(target=self.receive_broadcast, daemon=True).start()
        #threading.Thread(target=self.receive_multicast, daemon=True).start()

    def receive_unicast(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, 'SO_REUSEPORT'):
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            server.bind((self.ip_local, self.port_unicast)) 
            server.listen(5)
            while True:
                conn, addr = server.accept()
                print(f"[NetworkManager] TCP connection from {addr}")
                # Handle connection in separate thread to support multiple clients
                threading.Thread(target=self._handle_tcp_connection, args=(conn, addr), daemon=True).start()

    def _handle_tcp_connection(self, conn, addr):
        """Handle a single TCP connection."""
        try:
            with conn:
                while True:
                    # Use TCP message receive with length header
                    result = self.receive_TCP_message(conn)
                    if result is None:
                        break  # Connection closed
                    
                    msg_type, message, sender_ip = result
                    if self.on_message_received:
                        self.on_message_received(msg_type, message, sender_ip)
        except Exception as e:
            print(f"[NetworkManager] Connection {addr} error: {e}")

    def receive_broadcast(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, 'SO_REUSEPORT'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            sock.bind(('0.0.0.0', self.port_broadcast))
            #sock.bind((self.ip_local, self.port_broadcast))
            while True:
                data, addr = sock.recvfrom(1024)
                #print(addr)
                #if addr[0] == self.ip_local: # 忽略自己发出的广播
                #    continue
                if data and self.on_message_received:
                    msg_type, message, sender_ip = self.message_decode(data)
                    if sender_ip == self.ip_local:
                        continue
                    # 触发回调
                    self.on_message_received(msg_type, message, sender_ip)

    #先不管multicast
    def receive_multicast(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind((self.host_ip, self.mcast_port))
        mreq = socket.inet_aton(self.mcast_group) + socket.inet_aton(self.host_ip)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        while True:
            data, addr = sock.recvfrom(1024)
            if self.on_message_received:
                self.on_message_received('MULTICAST', addr, data.decode())
    


    # -----------------------
    # Long-lived TCP helpers
    # -----------------------
    def start_leader_long_lived_listener(self):
        logger.debug("Starting leader long-lived connection listener...")
        # 1. create TCP server socket for accepting long-lived connections from followers
        self.server_sock = self.create_tcp_server_socket('0.0.0.0', self.port_long_lived)

        # 2. start ACCEPT thread to accept new long-lived connections from followers
        self.accept_thread = threading.Thread(target=self._listen_for_followers, daemon=True)
        self.accept_thread.start()

        # 3. start MONITOR thread to monitor messages from followers
        self.monitor_thread = threading.Thread(target=self._process_messages, daemon=True)
        self.monitor_thread.start()

        logger.debug("Leader long-lived connection listener started")

    def start_follower_long_lived_connector(self, leader_ip, leader_id):
        """For followers to establish long-lived TCP connection to leader."""
        logger.debug(f"Starting follower long-lived connection to leader at {leader_ip}...")
        try:
            conn = self.connect_tcp(leader_id, leader_ip, self.port_long_lived, timeout=3.0)
            # Send IDENTIFY message with follower's server_id (could be None if not assigned yet)
            identify_msg = {"msg_type": "IDENTIFY", "message": {"server_id": getattr(self, "server_id", None)}}
            self.send_tcp_message(conn, "IDENTIFY", identify_msg["message"])
            logger.debug(f"Follower established long-lived connection to leader at {leader_ip}")
            # start monitoring this connection for incoming messages (e.g., heartbeats, commands)
            threading.Thread(target=self._process_messages, daemon=True).start()
        except Exception as e:
            logger.error(f"Failed to establish long-lived connection to leader at {leader_ip}: {e}")

    def _listen_for_followers(self):
        """Accept loop for long-lived TCP connections from followers. Leader only."""
        print("Leader TCP Accept Thread started...")
        while True:
            try:
                # try non-blocking accept; if we get a connection, perform identification handshake and register
                result = self.accept_nonblocking(self.server_sock)
                if result:
                    conn, addr = result
                    # 接收身份消息
                    msg = self.receive_tcp_message(conn, timeout=1.0)
                    if msg and msg[0] == "IDENTIFY":
                        f_id = msg[1].get("server_id")
                        self.register_connection(conn, server_id=f_id)
                        logger.debug(f"Registered long-lived connection from follower {f_id} at {addr}")
                        # 这里可以触发发送 REGISTER_ACK 的逻辑
                    else:
                        conn.close()
            except Exception as e:
                print(f"Accept 线程异常: {e}")
            time.sleep(0.1) # 避免 CPU 占用过高

    def _process_messages(self):
        """Monitor loop to read messages from all registered follower connections."""
        print("Leader Message Polling Thread 启动...")
        while True:
            # 获取当前所有已注册的连接快照
            with self._conn_lock:
                current_conns = list(self.serverid_to_conn.items())

            for f_id, conn in current_conns:
                try:
                    # 非阻塞读取消息，timeout 设为 0 或极小
                    msg = self.receive_tcp_message(conn, timeout=0.01)
                    if msg:
                        msg_type, payload, _ = msg
                        self._msg_callback(msg_type, payload, f_id) # trigger higher-level callback for processing
                    
                except Exception:
                    # 如果读取失败，说明连接可能断开，进行注销
                    logger.debug(f"Follower {f_id} connection error, unregistering")
                    self.unregister_connection(server_id=f_id)
            
            time.sleep(0.01) # 消息处理循环可以快一点

    def create_tcp_server_socket(self, bind_ip: str, port: int, backlog: int = 5) -> socket.socket:
        """Create a non-blocking TCP server socket ready to accept long-lived connections."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass
        srv.bind((bind_ip, port))
        srv.listen(backlog)
        srv.setblocking(False)
        return srv

    def accept_nonblocking(self, server_sock: socket.socket) -> Optional[Tuple[socket.socket, Tuple[str,int]]]:
        """Non-blocking accept. Caller will perform identification/registration."""
        try:
            conn, addr = server_sock.accept()
            conn.setblocking(False)
            with self._conn_lock:
                self.conn_to_addr[conn] = addr
            return conn, addr
        except BlockingIOError:
            return None
        except Exception as e:
            # swallow to keep accept loop robust
            return None

    def connect_tcp(self, target_server_id, target_ip: str, target_port: int, timeout: float = 5.0, bind_ip: Optional[str] = None) -> socket.socket:
        """Create a long-lived outbound TCP connection (follower -> leader). Returns non-blocking socket."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if bind_ip:
            sock.bind((bind_ip, 0))
        sock.settimeout(timeout)
        sock.connect((target_ip, target_port))
        sock.settimeout(None)
        sock.setblocking(False)
        with self._conn_lock:
            self.conn_to_addr[sock] = (target_ip, target_port)
            self.serverid_to_conn[target_server_id] = sock
        return sock

    # -----------------------
    # Framed JSON send/recv
    # -----------------------
    def send_tcp_msg_to_all_followers(self, msg_type: str, payload: dict):
        """Helper for leader to broadcast a message to all registered followers via long-lived TCP connections."""
        # get all current connections snapshot to avoid holding lock during sends
        with self._conn_lock:
            current_conns = list(self.serverid_to_conn.items())
        for server_id, conn in current_conns:
            try:
                self.send_tcp_message(conn, msg_type, payload)
            except Exception as e:
                logger.debug(f"Failed to send message to follower {server_id}, unregistering: {e}")
                # self.unregister_connection(server_id=server_id)

    def send_tcp_message(self, conn_or_server_id, msg_type: str, payload: dict):
        """
        Send length-prefixed JSON message. Accepts either a socket or registered server_id.
        """
        conn = None
        if isinstance(conn_or_server_id, socket.socket):
            conn = conn_or_server_id
        else:
            # assume server_id
            with self._conn_lock:
                conn = self.serverid_to_conn.get(int(conn_or_server_id))
        if not conn:
            raise RuntimeError("no connection available for send")

        try:
            msg = {"msg_type": msg_type, "message": payload}
            b = json.dumps(msg).encode("utf-8")
            header = struct.pack(">I", len(b))
            conn.sendall(header + b)
        except Exception:
            # on failure unregister to avoid stale entries
            try:
                self.unregister_connection(conn=conn)
            except:
                pass
            raise

    def _recv_exact(self, conn: socket.socket, n: int, timeout: Optional[float] = None) -> Optional[bytes]:
        """Read exactly n bytes or return None on EOF. Caller manages blocking/timeout."""
        data = b""
        start = time.time()
        while len(data) < n:
            try:
                chunk = conn.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except BlockingIOError:
                # non-blocking socket has no data yet
                if timeout is None:
                    time.sleep(0.01)
                    continue
                if time.time() - start > timeout:
                    return None
                time.sleep(0.01)
                continue
            except Exception:
                return None
        return data

    def receive_tcp_message(self, conn: socket.socket, timeout: Optional[float] = None) -> Optional[Tuple[str, dict, Tuple[str,int]]]:
        """
        Receive one framed message. Returns (msg_type, payload_dict, peer_addr) or None on timeout/closed.
        Non-blocking sockets supported with timeout parameter.
        """
        try:
            # read 4 byte header
            header = self._recv_exact(conn, 4, timeout)
            if not header:
                return None
            length = struct.unpack(">I", header)[0]
            body = self._recv_exact(conn, length, timeout)
            if not body:
                return None
            msg = json.loads(body.decode("utf-8"))
            return msg.get("msg_type"), msg.get("message", {}), self.conn_to_addr.get(conn)
        except Exception:
            return None

    # -----------------------
    # Connection registry
    # -----------------------
    def register_connection(self, conn: socket.socket, server_id: Optional[int] = None, ):
        """Register a long-lived connection with optional server_id. Leader calls this after identification."""
        with self._conn_lock:
            if server_id is not None:
                self.serverid_to_conn[int(server_id)] = conn
            self.conn_to_addr[conn] = self.conn_to_addr.get(conn, conn.getpeername())

    def unregister_connection(self, conn: Optional[socket.socket] = None, server_id: Optional[int] = None):
        """Unregister and close a connection by conn or server_id."""
        with self._conn_lock:
            if server_id is not None:
                conn = self.serverid_to_conn.pop(int(server_id), None)
            if conn:
                self.conn_to_addr.pop(conn, None)
                # remove from serverid map if present
                for sid, c in list(self.serverid_to_conn.items()):
                    if c is conn:
                        self.serverid_to_conn.pop(sid, None)
                try:
                    conn.close()
                except:
                    pass

    def get_conn_by_server_id(self, server_id: int) -> Optional[socket.socket]:
        with self._conn_lock:
            return self.serverid_to_conn.get(int(server_id))

    def list_registered_connections(self) -> Dict[int, Tuple[str,int]]:
        """Return mapping server_id -> peer addr for registered connections."""
        with self._conn_lock:
            return {sid: self.conn_to_addr.get(conn) for sid, conn in self.serverid_to_conn.items()}

    def close_all_connections(self):
        with self._conn_lock:
            for conn in list(self.conn_to_addr.keys()):
                try:
                    conn.close()
                except:
                    pass
            self.serverid_to_conn.clear()
            self.conn_to_addr.clear()

