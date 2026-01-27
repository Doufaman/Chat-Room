#!/usr/bin/env python3
"""同时启动多个客户端进程"""
import subprocess
import sys

if __name__ == '__main__':
    # 启动client1和client2作为子进程
    p1 = subprocess.Popen([sys.executable, 'client1.py', 'ClientA'])
    p2 = subprocess.Popen([sys.executable, 'client2.py', 'ClientB'])
    
    # 等待两个进程完成
    p1.wait()
    p2.wait()
    
    print("\n所有客户端已完成")
