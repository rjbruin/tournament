import numpy as np
import functools


@functools.total_ordering
class Team(object):

    def __init__(self, name):
        self.name = name
        self.elo = np.random.randint(800, 1200)
    
    def __str__(self):
        return self.name
    
    def __lt__(self, other):
        return self.elo < other.elo
    
    def __eq__(self, other):
        return self.elo == other.elo