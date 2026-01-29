# config.py

# ==================================================
# General
# ==================================================

DEBUG = True

# ==================================================
# Network / Communication
# ==================================================

# Server configuration for consensus (Bully algorithm)
# Each server needs: id, host, tcp_port (for consensus heartbeat), udp_port (for election)
SERVERS = [
    {"id": 1, "host": "127.0.0.1", "tcp_port": 5001, "udp_port": 6001},
    {"id": 2, "host": "127.0.0.1", "tcp_port": 5002, "udp_port": 6002},
    {"id": 3, "host": "127.0.0.1", "tcp_port": 5003, "udp_port": 6003},
    {"id": 4, "host": "127.0.0.1", "tcp_port": 5004, "udp_port": 6004},
    {"id": 5, "host": "127.0.0.1", "tcp_port": 5005, "udp_port": 6005}
]

# Client connection port base
CLIENT_PORT_BASE = 8000  # Server 1 -> 8001, Server 2 -> 8002, etc.



# ==================================================
# Heartbeat / Fault Tolerance
# ==================================================



# ==================================================
# Group / Replication
# ==================================================

MAX_SERVERS_PER_GROUP = 3


# ==================================================
# Load Balancing
# ==================================================

'''LOAD_WEIGHT_CLIENTS = 1.0
LOAD_WEIGHT_CPU = 1.0'''

# ==================================================
# Chatroom
# ==================================================

MAX_CLIENTS_PER_CHATROOM = 50
DEFAFULT_CHATROOM_1 = "chatroom_1"
DEFAFULT_CHATROOM_2 = "chatroom_2"
DEFAFULT_CHATROOM_3 = "chatroom_3"  
