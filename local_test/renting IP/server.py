import socket

def start_server():
    # 1. Create a UDP Socket
    # AF_INET = IPv4, SOCK_DGRAM = UDP
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # 2. Bind to "0.0.0.0"
    # This means "Listen on ALL network interfaces" (WiFi, Ethernet, Localhost)
    # We choose Port 6000 arbitrarily.
    server_port = 6000
    server_socket.bind(('0.0.0.0', server_port))

    # Helper: Print the local IP so you know what to type in the Client
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print(f"Server is running on Host: {hostname}")
    print(f"Local IP Address: {local_ip}") # <--- Type this into your Client!
    print(f"Listening on Port: {server_port}...\n")

    while True:
        # 3. Receive Data (Buffer size 1024 bytes)
        # This blocks (waits) until data arrives
        message, client_address = server_socket.recvfrom(1024)
        
        # 4. Decode bytes to string
        decoded_msg = message.decode('utf-8')
        
        print(f"Received message from {client_address}: {decoded_msg}")
        
        # Optional: Send a reply back so the client knows we got it
        reply = f"Server received: {decoded_msg}"
        server_socket.sendto(reply.encode('utf-8'), client_address)

if __name__ == "__main__":
    start_server()