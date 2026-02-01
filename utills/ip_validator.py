import socket
import ipaddress
import logging

logger = logging.getLogger(__name__)


def validate_ip_address(ip_str):
    """
    验证IP地址的合法性
    
    Args:
        ip_str: IP地址字符串
        
    Returns:
        tuple: (is_valid, error_message)
               is_valid: bool, True表示有效
               error_message: str, 如果无效则包含错误信息
    """
    if not ip_str or not isinstance(ip_str, str):
        return False, "IP地址不能为空"
    
    ip_str = ip_str.strip()
    
    # 1. 检查IP格式是否有效
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError as e:
        return False, f"IP地址格式无效: {str(e)}"
    
    # 2. 检查是否是回环地址（允许整个127.0.0.0/8段）
    if ip_obj.is_loopback:
        logger.debug(f"IP {ip_str} 是回环地址（本地测试用）")
        # 回环地址直接允许，跳过后续检查
        return True, ""
    
    # 3. 检查是否是保留地址或多播地址
    if ip_obj.is_reserved:
        return False, f"IP地址 {ip_str} 是保留地址，不能使用"
    
    if ip_obj.is_multicast:
        return False, f"IP地址 {ip_str} 是多播地址，不能使用"
    
    # 4. 检查是否是本机的有效网络接口IP
    try:
        local_ips = get_local_ips()
        if ip_str not in local_ips:
            logger.warning(f"IP {ip_str} 不在本机网络接口列表中")
            logger.warning(f"本机可用IP: {', '.join(local_ips)}")
            return False, (f"IP地址 {ip_str} 不属于本机网络接口。\n"
                          f"本机可用IP: {', '.join(local_ips)}")
    except Exception as e:
        logger.warning(f"无法检查本机网络接口: {e}")
    
    # 4. 验证是否可以绑定到该IP
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # 使用一个临时端口测试绑定
        test_sock.bind((ip_str, 0))
        test_sock.close()
    except OSError as e:
        return False, f"无法绑定到IP地址 {ip_str}: {str(e)}"
    
    return True, ""


def get_local_ips():
    """
    获取本机所有有效的IP地址
    
    Returns:
        list: IP地址列表
    """
    local_ips = set()
    
    try:
        # 方法1: 获取主机名对应的IP
        hostname = socket.gethostname()
        host_ips = socket.gethostbyname_ex(hostname)[2]
        local_ips.update(host_ips)
    except Exception as e:
        logger.debug(f"无法通过主机名获取IP: {e}")
    
    try:
        # 方法2: 通过创建临时连接获取本地IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ips.add(s.getsockname()[0])
        s.close()
    except Exception as e:
        logger.debug(f"无法通过临时连接获取IP: {e}")
    
    # 添加回环地址
    local_ips.add('127.0.0.1')
    
    return sorted(list(local_ips))


def prompt_valid_ip():
    """
    提示用户输入有效的IP地址，直到输入合法为止
    
    Returns:
        str: 有效的IP地址
    """
    while True:
        ip_str = input("请输入服务器 IP 地址: ").strip()
        
        is_valid, error_msg = validate_ip_address(ip_str)
        
        if is_valid:
            print(f"[IP验证] ✓ IP地址 {ip_str} 验证通过")
            return ip_str
        else:
            print(f"[IP验证] ✗ {error_msg}")
            print("[IP验证] 请重新输入...")
