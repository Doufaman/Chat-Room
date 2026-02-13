import socket


def broadcast(ip, port, broadcast_announcement):
    # Create a UDP socket
    broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Enable permission to send to broadcast addresses
    broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    # Send the broadcast announcement
    broadcast_socket.sendto(str.encode(broadcast_announcement), (ip, port))
    broadcast_socket.close()


if __name__ == '__main__':
    # Broadcast address and port (example for a /24 network)
    BROADCAST_IP = "192.168.0.255"
    BROADCAST_PORT = 5972

    # Local host information
    my_host = socket.gethostname()
    my_ip = socket.gethostbyname(my_host)

    # Compose broadcast announcement
    announcement = my_ip + ' sent a broadcast'
    # Send the broadcast announcement
    broadcast(BROADCAST_IP, BROADCAST_PORT, announcement)

