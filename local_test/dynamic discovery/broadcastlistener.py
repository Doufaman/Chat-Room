import socket

# Listening port
BROADCAST_PORT = 5972

# Create a UDP socket
listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Allow multiple listeners (Linux/macOS semantics)
listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

# Bind to all local interfaces to receive broadcast packets
listen_socket.bind(("0.0.0.0", BROADCAST_PORT))

print("Listening to broadcast announcements")

while True:
    data, addr = listen_socket.recvfrom(1024)
    if data:
        print("Received a broadcast announcement:", data.decode())
