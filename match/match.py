import numpy as np
from abc import ABCMeta, abstractmethod


class Match(metaclass=ABCMeta):

    def __init__(self, teams, score_names=['goals', 'points']):
        self.teams = teams
        self.scores = {}
        self.completed = False
        for score_name in score_names:
            self.scores[score_name] = [0 for t in self.teams]
    
    @abstractmethod
    def simulate(self, method=None, ignore_completed=False):
        pass
    
    @abstractmethod
    def __str__(self):
        pass