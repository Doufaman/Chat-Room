# Not yet included in the plan

from .base import Role

class Backup(Role):
    def run(self):
        print("Observer running observer-specific logic.")

    def shutdown(self):
        print("Observer shutting down.")
