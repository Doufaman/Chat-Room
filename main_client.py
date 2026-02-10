"""
Chat Client - 聊天室客户端（纯UDP通信）
功能：
1. 广播查找Leader
2. 从Leader获取聊天室列表
3. 创建/加入/刷新聊天室
4. 加入聊天室后进入聊天模式（TCP）
"""
import socket
import threading
import sys
import os
import json
import time
from utills.logger import get_logger

logger = get_logger("chat_client")

from network.chatting_messenger import (
    send_tcp_message, receive_tcp_message, create_chat_message,
    TYPE_JOIN, TYPE_CHAT, TYPE_LEAVE, TYPE_UPDATE, safe_print
)
from common.vector_clock import VectorClock

# 与服务器一致的广播端口
PORT_BROADCAST = 9000
DISCOVERY_TIMEOUT = 3.0


class ChatClient:
    """纯UDP聊天室客户端"""

    def __init__(self, username):
        self.username = username
        self.leader_ip = None
        self.leader_id = None
        self.chatrooms = []
        self.running = True

        # 用于聊天的状态
        self.chat_socket = None
        self.chat_running = False
        self.vector_clock = VectorClock(username)
        self.lock = threading.Lock()

    # ==========================================
    # UDP 通信工具
    # ==========================================
    def _create_udp_socket(self):
        """创建绑定到广播端口的UDP socket"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(('', PORT_BROADCAST))
        return sock

    def _send_and_receive(self, msg_type, message, expected_response, timeout=3.0, retries=3):
        """
        发送UDP广播并等待指定类型的响应

        Args:
            msg_type: 发送的消息类型
            message: 消息内容字典
            expected_response: 期望的响应消息类型
            timeout: 每次重试的超时时间
            retries: 重试次数

        Returns:
            dict or None: 响应数据或None
        """
        sock = self._create_udp_socket()
        sock.settimeout(timeout)

        request = json.dumps({
            "msg_type": msg_type,
            "message": message,
            "sender_ip": "client"
        }, ensure_ascii=False).encode('utf-8')

        try:
            for attempt in range(retries):
                sock.sendto(request, ('<broadcast>', PORT_BROADCAST))

                deadline = time.time() + timeout
                while time.time() < deadline:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break
                    sock.settimeout(remaining)
                    try:
                        data, addr = sock.recvfrom(65536)
                        resp = json.loads(data.decode('utf-8'))
                        if resp.get('msg_type') == expected_response:
                            return resp
                        # 收到了不相关的广播消息，继续等待
                    except socket.timeout:
                        break
                    except json.JSONDecodeError:
                        continue

            return None
        finally:
            sock.close()

    # ==========================================
    # 核心功能
    # ==========================================
    def find_leader(self):
        """广播查找Leader"""
        print("\n正在查找Leader服务器...")

        resp = self._send_and_receive(
            "WHO_IS_LEADER",
            {"client_name": self.username},
            "I_AM_LEADER",
            timeout=2.0,
            retries=3
        )

        if resp:
            self.leader_ip = resp['message']['leader_ip']
            self.leader_id = resp['message']['leader_id']
            print(f"✓ 找到Leader: {self.leader_ip} (Server ID: {self.leader_id})")
            return True

        print("✗ 未找到Leader服务器，请确保服务器正在运行")
        return False

    def get_chatroom_list(self):
        """从Leader获取聊天室列表（UDP广播）"""
        if not self.leader_ip:
            print("✗ 未连接到Leader")
            return False

        resp = self._send_and_receive(
            "GET_CHATROOM_LIST",
            {},
            "CHATROOM_LIST",
            timeout=3.0,
            retries=2
        )

        if resp:
            self.chatrooms = resp['message'].get('chatrooms', [])
            return True

        print("✗ 获取聊天室列表超时")
        return False

    def display_chatrooms(self):
        """显示可用的聊天室列表"""
        if not self.chatrooms:
            print("\n当前没有可用的聊天室")
            return

        print("\n" + "=" * 70)
        print("可用聊天室列表:")
        print("=" * 70)
        print(f"{'序号':<6} {'聊天室ID':<15} {'名称':<20} {'服务器':<18} {'在线人数':<10}")
        print("-" * 70)

        for idx, room in enumerate(self.chatrooms, 1):
            port = room.get('port', '?')
            clients = room.get('clients_count', 0)
            print(f"{idx:<6} {room['chatroom_id']:<15} {room['name']:<20} "
                  f"{room['server_ip']}:{port:<6} {clients:<10}")

        print("=" * 70)

    def create_chatroom(self):
        """创建新聊天室（UDP广播）"""
        if not self.leader_ip:
            print("✗ 未连接到Leader")
            return False

        room_name = input("\n请输入新聊天室的名称: ").strip()
        if not room_name:
            print("✗ 聊天室名称不能为空")
            return False

        print(f"正在创建聊天室 '{room_name}'...")

        resp = self._send_and_receive(
            "CREATE_CHATROOM",
            {"name": room_name},
            "CHATROOM_CREATED",
            timeout=10.0,
            retries=1
        )

        if resp:
            room_info = resp['message']['chatroom_info']
            print(f"\n✓ 聊天室创建成功!")
            print(f"  聊天室ID: {room_info['chatroom_id']}")
            print(f"  名称: {room_info['name']}")
            print(f"  服务器: {room_info['server_ip']}:{room_info['port']}")
            return True

        print("✗ 创建聊天室超时")
        return False

    def join_chatroom(self):
        """选择并加入聊天室"""
        if not self.chatrooms:
            print("\n当前没有可用的聊天室，请先创建一个")
            return

        self.display_chatrooms()

        try:
            choice = input("\n请输入要加入的聊天室序号 (或直接输入 IP:PORT): ").strip()

            if ':' in choice:
                parts = choice.split(':')
                if len(parts) == 2:
                    server_ip = parts[0]
                    port = int(parts[1])
                else:
                    print("✗ 格式错误，请使用 IP:PORT 格式")
                    return
            else:
                idx = int(choice) - 1
                if 0 <= idx < len(self.chatrooms):
                    room = self.chatrooms[idx]
                    server_ip = room['server_ip']
                    port = room['port']
                else:
                    print("✗ 无效的序号")
                    return

            # 连接到聊天室（TCP长连接用于实际聊天）
            self._connect_and_chat(server_ip, port)

        except ValueError:
            print("✗ 输入格式错误")
        except Exception as e:
            print(f"✗ 加入聊天室失败: {e}")

    # ==========================================
    # 聊天功能（TCP连接到具体chatroom）
    # ==========================================
    def _connect_and_chat(self, server_ip, port):
        """连接到聊天室并开始聊天"""
        print(f"\n正在连接到聊天室 {server_ip}:{port}...")

        try:
            self.chat_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.chat_socket.settimeout(10.0)
            self.chat_socket.connect((server_ip, port))
            self.chat_socket.settimeout(None)
            safe_print(f"✓ 已连接!")

            # 发送JOIN消息
            with self.lock:
                join_msg = create_chat_message(
                    TYPE_JOIN, self.username, self.vector_clock,
                    f"{self.username} joined the chat."
                )
            send_tcp_message(self.chat_socket, join_msg)

            self.chat_running = True

            # 启动接收线程
            recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
            recv_thread.start()

            safe_print(f"\n[Chat] 欢迎 {self.username}! 输入消息开始聊天。")
            safe_print("[Chat] 输入 /quit 离开聊天室。\n")

            # 发送消息循环
            while self.chat_running:
                try:
                    content = input("Your message: ")
                    if content.lower() == '/quit':
                        self._send_leave()
                        break
                    if content.strip():
                        self._send_chat(content)
                except EOFError:
                    break

        except Exception as e:
            safe_print(f"✗ 连接失败: {e}")
        finally:
            self.chat_running = False
            if self.chat_socket:
                self.chat_socket.close()
                self.chat_socket = None
            safe_print("[Chat] 已断开连接")

    def _send_chat(self, content):
        """发送聊天消息"""
        with self.lock:
            self.vector_clock.increment()
            msg = create_chat_message(TYPE_CHAT, self.username, self.vector_clock, content)
        try:
            send_tcp_message(self.chat_socket, msg)
        except Exception as e:
            safe_print(f"[Error] 发送失败: {e}")
            self.chat_running = False

    def _send_leave(self):
        """发送离开消息"""
        with self.lock:
            msg = create_chat_message(
                TYPE_LEAVE, self.username, self.vector_clock,
                f"{self.username} left the chat."
            )
        try:
            send_tcp_message(self.chat_socket, msg)
        except:
            pass

    def _receive_loop(self):
        """接收聊天消息"""
        hold_back_queue = []
        try:
            while self.chat_running:
                message = receive_tcp_message(self.chat_socket)
                if message is None:
                    safe_print("[Chat] 服务器断开连接")
                    self.chat_running = False
                    break

                msg_type = message.get('type')
                sender = message.get('sender')
                received_clock = message.get('vector_clock', {})
                content = message.get('content', '')

                with self.lock:
                    if msg_type == TYPE_UPDATE:
                        # Server sent us the full member list (vector clock)
                        self.vector_clock.merge(received_clock)
                        safe_print(f"[Chat] 成员列表已更新")
                        continue
                    
                    if msg_type == TYPE_JOIN:
                        self.vector_clock.add_entry(sender)
                        self.vector_clock.merge(received_clock)
                        safe_print(f">>> {sender} 加入了聊天室 (Debug: VC={received_clock})")
                    elif msg_type == TYPE_CHAT:
                        if self.vector_clock.is_deliveravle(received_clock, sender):
                            self.vector_clock.merge(received_clock)
                            safe_print(f"{sender}: {content} (Debug: VC={received_clock})")
                        else:
                            hold_back_queue.append(message)
                    elif msg_type == TYPE_LEAVE:
                        safe_print(f"<<< {sender} 离开了聊天室 (Debug: VC={received_clock})")

                # 检查hold-back队列
                with self.lock:
                    changed = True
                    while changed:
                        changed = False
                        for msg in list(hold_back_queue):
                            s = msg.get('sender')
                            rc = msg.get('vector_clock', {})
                            if self.vector_clock.is_deliveravle(rc, s):
                                self.vector_clock.merge(rc)
                                safe_print(f"{s}: {msg.get('content', '')} (Debug: VC={rc} [from hold-back])")
                                hold_back_queue.remove(msg)
                                changed = True
                                break

        except Exception as e:
            if self.chat_running:
                safe_print(f"[Error] 接收错误: {e}")
            self.chat_running = False

    # ==========================================
    # 菜单
    # ==========================================
    def show_menu(self):
        """显示主菜单"""
        print("\n" + "=" * 60)
        print("聊天室客户端 - 主菜单")
        print("=" * 60)
        print("(1) 创建聊天室")
        print("(2) 加入聊天室")
        print("(3) 刷新聊天室列表")
        print("(4) 重新查找Leader")
        print("(5) 退出")
        print("=" * 60)

    def run(self):
        """运行客户端"""
        print("=" * 60)
        print("       欢迎使用分布式聊天室客户端")
        print("=" * 60)
        print(f"\n欢迎, {self.username}!")

        # 查找Leader
        if not self.find_leader():
            print("\n无法找到Leader服务器，程序退出")
            return

        # 主循环
        while self.running:
            # 自动刷新聊天室列表
            if self.get_chatroom_list():
                self.display_chatrooms()

            self.show_menu()
            choice = input("\n请选择操作 (1-5): ").strip()

            if choice == '1':
                self.create_chatroom()
            elif choice == '2':
                self.join_chatroom()
            elif choice == '3':
                print("\n正在刷新聊天室列表...")
                if self.get_chatroom_list():
                    self.display_chatrooms()
                    print("✓ 列表已刷新")
                else:
                    print("✗ 刷新失败")
            elif choice == '4':
                self.find_leader()
            elif choice == '5':
                print(f"\n再见, {self.username}!")
                self.running = False
            else:
                print("\n✗ 无效的选择，请输入 1-5")

        print("\n客户端已退出")


def main():
    """主函数"""
    print("=" * 60)
    print("       分布式聊天室客户端")
    print("=" * 60)

    username = input("\n请输入您的用户名: ").strip()
    if not username:
        username = f"User_{os.getpid()}"

    client = ChatClient(username)
    try:
        client.run()
    except KeyboardInterrupt:
        print(f"\n\n再见, {username}!")
    except Exception as e:
        print(f"\n程序错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
