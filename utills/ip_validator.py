"""
IP address validating for MACOS, as MACOS 
 have issues binding to certain IPs. 
"""
import socket
import ipaddress
import logging

logger = logging.getLogger(__name__)


def validate_ip_address(ip_str):
    """
    Validate the legitimacy of an IP address
    
    Args:
        ip_str: IP address string
        
    Returns:
        tuple: (is_valid, error_message)
               is_valid: bool, True indicates valid
               error_message: str, contains error message if invalid
    """
    if not ip_str or not isinstance(ip_str, str):
        return False, "IP address cannot be empty"
    
    ip_str = ip_str.strip()
    
    # 1. Check if IP format is valid
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError as e:
        return False, f"Invalid IP address format: {str(e)}"
    
    # 2. Check if it's a reserved or multicast address (except loopback)
    if ip_obj.is_loopback:
        logger.debug(f"IP {ip_str} is loopback address (for local testing)")
        # Continue validation, don't skip binding test
    elif ip_obj.is_reserved:
        return False, f"IP address {ip_str} is reserved and cannot be used"
    
    if ip_obj.is_multicast:
        return False, f"IP address {ip_str} is multicast address and cannot be used"
    
    # 3. Verify if it can bind to this IP (most important check)
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Test binding with a temporary port
        test_sock.bind((ip_str, 0))
        test_sock.close()
    except OSError as e:
        if ip_obj.is_loopback:
            return False, (f"Loopback address {ip_str} cannot be bound: {str(e)}\n"
                          f"On macOS, you may need to add an alias first:\n"
                          f"  sudo ifconfig lo0 alias {ip_str}\n"
                          f"or use 127.0.0.1")
        else:
            return False, f"Cannot bind to IP address {ip_str}: {str(e)}"
    
    # 4. For non-loopback addresses, check if it's a valid network interface IP
    if not ip_obj.is_loopback:
        try:
            local_ips = get_local_ips()
            if ip_str not in local_ips:
                logger.warning(f"IP {ip_str} is not in the local network interface list")
                logger.warning(f"Available IPs on this machine: {', '.join(local_ips)}")
                return False, (f"IP address {ip_str} does not belong to local network interface.\n"
                              f"Available IPs on this machine: {', '.join(local_ips)}")
        except Exception as e:
            logger.warning(f"Cannot check local network interface: {e}")
    
    return True, ""


def get_local_ips():
    """
    Get all valid IP addresses on this machine
    
    Returns:
        list: IP address list
    """
    local_ips = set()
    
    try:
        # Method 1: Get IP corresponding to hostname
        hostname = socket.gethostname()
        host_ips = socket.gethostbyname_ex(hostname)[2]
        local_ips.update(host_ips)
    except Exception as e:
        logger.debug(f"Cannot get IP via hostname: {e}")
    
    try:
        # Method 2: Get local IP by creating temporary connection
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ips.add(s.getsockname()[0])
        s.close()
    except Exception as e:
        logger.debug(f"Cannot get IP via temporary connection: {e}")
    
    # Add loopback address
    local_ips.add('127.0.0.1')
    
    return sorted(list(local_ips))


def prompt_valid_ip():
    """
    Prompt user to enter a valid IP address until it's legal
    
    Returns:
        str: Valid IP address
    """
    # Display available IP addresses
    print("\n" + "="*50)
    print("Available IP addresses:")
    print("="*50)
    
    local_ips = get_local_ips()
    for i, ip in enumerate(local_ips, 1):
        print(f"  {i}. {ip}")
    
    print("\nLoopback addresses:")
    print("  - 127.0.0.1 (default available)")
    print("  - 127.0.0.x (macOS requires adding alias first: sudo ifconfig lo0 alias 127.0.0.x)")
    print("="*50 + "\n")
    
    while True:
        ip_str = input("Please enter server IP address: ").strip()
        
        is_valid, error_msg = validate_ip_address(ip_str)
        
        if is_valid:
            print(f"[IP Validation] ✓ IP address {ip_str} validation passed")
            return ip_str
        else:
            print(f"[IP Validation] ✗ {error_msg}")
            print("[IP Validation] Please re-enter...")
