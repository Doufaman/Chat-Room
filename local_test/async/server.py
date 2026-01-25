import asyncio

async def handle_client(reader, writer):
    data = await reader.read(100)
    message = data.decode()
    #calculate the client's number
    number = int(message)
    response = number*number

    writer.write(str(response).encode())
    await writer.drain()

    writer.close()
    await writer.wait_closed()

async def main():
    server = await asyncio.start_server(
        handle_client, '127.0.0.1', 8888)
    print('Server started on ')
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
