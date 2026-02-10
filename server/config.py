# config.py

# ==================================================
# General
# ==================================================

TYPE_LEADER = "LEADER"
TYPE_FOLLOWER = "FOLLOWER"

DEBUG = True
ACTIVE = "ACTIVE"
SUSPECT = "SUSPECT"
DEAD = "DEAD"

# ==================================================
# Network / Communication
# ==================================================



# ==================================================
# Heartbeat / Fault Tolerance
# ==================================================

HEARTBEAT_INTERVAL = 3  # seconds
HEARTBEAT_LEADER_TIMEOUT = 15  # seconds 
HEARTBEAT_SERVER_TIMEOUT = 18  # seconds


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
