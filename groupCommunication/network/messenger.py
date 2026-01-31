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

#for UDP socket communication:
def create_udp_socket(bind_ip, bind_port):
    """create and bind a UDP socket"""
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_socket.bind((bind_ip, bind_port))
    return udp_socket

def send_udp_message(udp_socket, message, dest_ip, dest_port):
    """send the serialized message to the UDP socket"""
    try:
        pkg = encode_message(message)
        udp_socket.sendto(pkg, (dest_ip, dest_port))
    except Exception as e:
        print("Error captured, while sending UDP message:", e)
        raise e
    
def receive_udp_message(udp_socket, buffer_size=4096):
    """receive the serialized message from the UDP socket"""
    try:
        pkg, addr = udp_socket.recvfrom(buffer_size)
        message = decode_message(pkg)
        return message, addr
    except Exception as e:
        print("Error captured, while receiving UDP message:", e)
        raise e

#for TCP socket communication:
"""Define the header to prevent packet sticking problem"""
HEADER_FORMAT = '!I'  
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

def send_tcp_message(socket, message):
    """send the serialized message to the socket with length prefix"""
    try:
        pkg_body = encode_message(message)
        pkg_header = struct.pack(HEADER_FORMAT, len(pkg_body))
        pkg = pkg_header + pkg_body
        socket.sendall(pkg)
    except Exception as e:
        print("Error captured, while sending message:", e)
        raise e

def receive_tcp_message(socket):
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
        
        