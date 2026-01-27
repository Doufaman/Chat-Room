import socket

server_address = '127.0.0.1'
server_port = 10001
buffer_size = 1024

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.bind((server_address, server_port))
server_socket.listen(1)
print('Server is listening on {}:{}'.format(server_address, server_port))

conn, addr = server_socket.accept()  # Accept a connection (blocking call)

with conn:
    print('Connected by', addr)
    while True:
        data = conn.recv(buffer_size)
        if not data:
            break
        print('Received from client:', data.decode())
        message = 'Hi client! Nice to connect with you!'
        conn.sendall(message.encode())
        print('Replied to client:', message)

