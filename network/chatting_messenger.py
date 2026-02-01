"""
Manage the message coding, transmission between clients and server for chatting.
This is separate from network_manager which handles server-to-server communication.
"""
import socket
import struct
import json
import sys
import os

# ============================================================
#  Message Types for Chat
# ============================================================
TYPE_JOIN = 'JOIN'
TYPE_CHAT = 'CHAT'
TYPE_LEAVE = 'LEAVE'
TYPE_UPDATE = 'UPDATE'  # When there is a new member, update vector clocks

# ============================================================
#  Message Encoding/Decoding
# ============================================================

def encode_message(message):
    """Encode message dict to JSON bytes"""
    return json.dumps(message, ensure_ascii=False).encode('utf-8')

def decode_message(message_bytes):
    """Decode JSON bytes to message dict"""
    return json.loads(message_bytes.decode('utf-8'))

def create_chat_message(msg_type, sender, vector_clock, content=None):
    """
    Create a chat message in standard format.
    
    Args:
        msg_type: TYPE_JOIN, TYPE_CHAT, TYPE_LEAVE, TYPE_UPDATE
        sender: User ID of the sender
        vector_clock: VectorClock object or dict
        content: Message content (string or dict)
    
    Returns:
        dict: Formatted message
    """
    # Handle VectorClock object or dict
    if hasattr(vector_clock, 'copy'):
        vc = vector_clock.copy()
    else:
        vc = vector_clock if vector_clock else {}
    
    return {
        'type': msg_type,
        'sender': sender,
        'vector_clock': vc,
        'content': content if content else ''
    }

# ============================================================
#  TCP Communication (with length prefix to prevent sticking)
# ============================================================

HEADER_FORMAT = '!I'  # 4-byte unsigned integer for message length
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

def send_tcp_message(sock, message):
    """
    Send a message through TCP socket with length prefix.
    
    Args:
        sock: TCP socket
        message: dict to send
    """
    try:
        pkg_body = encode_message(message)
        pkg_header = struct.pack(HEADER_FORMAT, len(pkg_body))
        pkg = pkg_header + pkg_body
        sock.sendall(pkg)
    except Exception as e:
        raise ConnectionError(f"Failed to send TCP message: {e}")

def receive_tcp_message(sock):
    """
    Receive a message from TCP socket with length prefix.
    
    Args:
        sock: TCP socket
    
    Returns:
        dict: Received message, or None if connection closed
    """
    try:
        # Read header (4 bytes)
        pkg_header = _read_exact(sock, HEADER_SIZE)
        if not pkg_header:
            return None  # Connection closed
        
        # Unpack message length
        body_len = struct.unpack(HEADER_FORMAT, pkg_header)[0]
        
        # Read message body
        pkg_body = _read_exact(sock, body_len)
        if not pkg_body:
            return None  # Connection closed
        
        return decode_message(pkg_body)
    except Exception as e:
        raise ConnectionError(f"Failed to receive TCP message: {e}")

def _read_exact(sock, n):
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

# ============================================================
#  Utility Functions
# ============================================================

def safe_print(content):
    """
    Safely print a message without disrupting user's input line.
    Works on Windows and Unix-like systems.
    """
    # Clear the current line
    if os.name == 'nt':
        # Windows: Move to start, overwrite with spaces, move back
        sys.stdout.write('\r' + ' ' * 80 + '\r')
    else:
        # macOS/Linux: Move to start, clear line
        sys.stdout.write('\r\033[K')
    
    # Print the message
    print(content)
    
    # Restore the input prompt
    sys.stdout.write("Your message: ")
    sys.stdout.flush()


