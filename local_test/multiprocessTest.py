from multiprocessing import Process
import os


def salute(course):
    """Print greeting and process information."""
    print('Hello', course)
    print('Parent process id:', os.getppid())
    print('Process id:', os.getpid())


if __name__ == '__main__':
    # Create a new process
    p = Process(target=salute, args=('DS',))
    
    # Start the process
    p.start()
    
    # Wait for the process to complete
    p.join()