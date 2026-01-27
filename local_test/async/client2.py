import asyncio
import sys


async def tcp_client(client_id, number):
    """单个客户端连接"""
    # 1. 建立连接
    reader, writer = await asyncio.open_connection('127.0.0.1', 8888)

    message = str(number)
    message = input(f'Client {client_id} 输入要发送的数字: ')
    print(f'[Client {client_id}] 发送: {message}')

    # 2. 发送数据
    writer.write(message.encode())
    await writer.drain()

    # 3. 等待接收结果
    data = await reader.read(100)
    print(f'[Client {client_id}] 收到: {data.decode()}')

    # 4. 关闭
    writer.close()
    await writer.wait_closed()


if __name__ == '__main__':
    # 从命令行获取客户端ID (可选)
    client_id = sys.argv[1] if len(sys.argv) > 1 else 'B'
    
    # 发送多个请求
    async def run_client():
        tasks = [tcp_client(client_id, i) for i in range(1, 6)]
        await asyncio.gather(*tasks)
    
    asyncio.run(run_client())

