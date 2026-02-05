"""Enabling causal ordering using vector clocks"""

class VectorClock:
    def __init__(self, client_id=None, initial_users=None):
        """
        initialize a vector clock for a lately joined client
        :param client_id: Unique identifier for the client 
        :param initial_users: Initial list of the existing users in the group
        """
        self.client_id = client_id
        self.clock = {}
        if client_id != None:
         self.clock[client_id] = 0
        if initial_users:
            for user in initial_users:
                    self.clock[user] = 0

    def add_entry(self, new_client_id):
        """Add a new entry for a newly joined client"""
        if new_client_id not in self.clock:
            self.clock[new_client_id] = 0

    def increment(self):
        """Increment the vector clock for this client"""
        self.clock[self.client_id] += 1

    def merge(self, received_clock):
         """when receiving a message, merge the received vector clock into the local vector clock"""
         for client, value in received_clock.items():
              value = self.clock.get(client, 0)
              self.clock[client] = max(received_clock.get(client, 0), value)

    def is_deliveravle(self, received_clock, sender_id):
        """Check if a message with the received vector clock is deliverable"""
        if self.clock.get(sender_id, 0) + 1 != received_clock.get(sender_id, 0):
            return False
        
        for client, value in received_clock.items():
             if client == sender_id:
                  continue 
             if received_clock[client] > self.clock[client]:
                  return False 

        return True
    
    def add_entry(self, new_client_id):
        """Add a new entry for a newly joined client"""
        if new_client_id not in self.clock:
            self.clock[new_client_id] = 0
    
    def print_clock(self):
        """print out the vector clocks for debugging"""
        sorted_items = sorted(self.clock.items())
        items_str = ", ".join([f"{k}:{v}" for k, v in sorted_items])
        print( f"<{items_str}>")

    def copy(self):
        """Return a copy of the clock dictionary"""
        return self.clock.copy()
        
        

    

        

    