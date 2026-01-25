import socket

def start_client():
    # 1. Create UDP Socket
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # We allow the OS to pick a random port for us (Standard behavior)
    
    # 2. Ask user for the Target Server IP
    server_ip = input("Enter Server IP (e.g., 192.168.1.5): ")
    server_port = 6000 # Must match the server.py port

    print(f"Ready to send to {server_ip}:{server_port}. Type 'quit' to exit.")

    while True:
        # 3. Get User Input
        msg = input("You: ")
        if msg.lower() == 'quit':
            break

        # 4. Send Message (Encode string to bytes)
        client_socket.sendto(msg.encode('utf-8'), (server_ip, server_port))
        
        # 5. (Optional) Wait for a reply with a timeout
        # If the server doesn't reply in 2 seconds, we move on (UDP is unreliable!)
        client_socket.settimeout(2)
        try:
            reply, server_addr = client_socket.recvfrom(1024)
            print(f"Server replied: {reply.decode('utf-8')}")
        except socket.timeout:
            print("No reply from server (Packet lost or Server busy)")

    client_socket.close()

if __name__ == "__main__":
    start_client()