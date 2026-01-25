import socket

client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_address = '127.0.0.1' 
server_port = 10001
buffer_size = 4096
client_socket.connect((server_address, server_port))
while True:
    message = input("Enter message to send to server (or 'exit' to quit): ")
    if message.lower() == 'exit':
        break
    client_socket.sendall(message.encode())
    print('Sent to server:', message)
    data = client_socket.recv(buffer_size)
    print('Received from server:', data.decode())

client_socket.close()
print('Socket closed')