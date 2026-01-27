from multiprocessing import Process, Pipe
from time import sleep

def local_event(pid, vector):
    vector[pid-1] += 1
    print('Process {} performed local event, and its vector clock is {}'.format(pid, vector))
    return vector

def send_event(pipe, pid, vector):
    vector[pid-1] += 1
    pipe.send((pid, vector))
    print('Process {} sent message, and its vector clock is {}'.format(pid, vector))
    return vector

def receive_event(pipe, pid, vector):
    sender_id, sender_vector = pipe.recv()
    vector[pid-1] += 1
    for i in range(len(vector)):
        vector[i] = max(vector[i], sender_vector[i])
    print('Process {} received message from Process {} with vector {}, and its vector clock is {}'.format(pid, sender_id, sender_vector, vector))
    return vector

def process_one(pipe12):
    pid = 1
    vector = [0, 0, 0]
    vector = local_event(pid, vector)
    vector = send_event(pipe12, pid, vector)
    sleep(3)
    vector = local_event(pid, vector)
    vector = receive_event(pipe12, pid, vector)
    vector = local_event(pid, vector)

def process_two(pipe21, pipe23):
    pid = 2
    vector = [0, 0, 0]
    vector = receive_event(pipe21, pid, vector)
    vector = send_event(pipe21, pid, vector)
    vector = send_event(pipe23, pid, vector)
    vector = receive_event(pipe23, pid, vector)

def process_three(pipe32):
    pid = 3
    vector = [0, 0, 0]
    vector = receive_event(pipe32, pid, vector)
    vector = send_event(pipe32, pid, vector)


if __name__ == '__main__':
    pipe12, pipe21 = Pipe()
    pipe23, pipe32 = Pipe()
    process1 = Process(target=process_one, args=(pipe12,))
    process2 = Process(target=process_two, args=(pipe21, pipe23))
    process3 = Process(target=process_three, args=(pipe32,))
    process1.start()
    process2.start()
    process3.start()

    process1.join()
    process2.join()
    process3.join()