#This file is to handle TCP packeg sticking problem and provide message transmission functions
import socket 
import struct 
import sys
import os

# Get the absolute path of the directory containing this script
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (which should contain 'common')
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from common.protocol import encode_message, decode_message


"""Define the header to prevent packet sticking problem"""
HEADER_FORMAT = '!I'  
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

def send_message(socket, message):
    """send the serialized message to the socket with length prefix"""
    try:
        pkg_body = encode_message(message)
        pkg_header = struct.pack(HEADER_FORMAT, len(pkg_body))
        pkg = pkg_header + pkg_body
        socket.sendall(pkg)
    except Exception as e:
        print("Error captured, while sending message:", e)
        raise e

def receive_message(socket):
    """receive the serialized message from the socket"""
    try:
        pkg_header = read_by_length(socket, HEADER_SIZE)
        if not pkg_header:
            return None #connection closed
        body_len = struct.unpack(HEADER_FORMAT, pkg_header)[0]
        pkg_body = read_by_length(socket, body_len)
        if not pkg_body:
            return None #connection closed
        return decode_message(pkg_body)
    except Exception as e:
        print("Error captured, while receiving message:", e)
        raise e

def read_by_length(socket, n):
    """Helper function to receive n bytes from the socket"""
    data = bytearray()
    while len(data) < n:
        try:
            packet = socket.recv(n - len(data))
            if not packet:
                return None
            data.extend(packet)
        except OSError:
            return None
    return data
        
        