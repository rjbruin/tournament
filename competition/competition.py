import numpy as np
from abc import ABCMeta, abstractmethod

from match.footballmatch import FootballMatch
from match.lolmatch import LoLMatch
import competition


class Competition(metaclass=ABCMeta):
    
    @staticmethod
    def build(match_type='football', comp_type='round_robin'):
        if comp_type == 'round_robin':
            if match_type == 'football':
                return competition.FootballRoundRobin
            elif match_type == 'lol':
                return competition.LoLRoundRobin
        else:
            raise NotImplementedError()
    
    def __init__(self, teams, load_from_file=None):
        self.teams = {team.name: team for team in teams}
        self.matches = []
        self.scores = []
        self.planned = False
        if load_from_file:
            self.load(load_from_file)
    
    def load(self, filename):
        with open(filename) as f:
            for line in f:
                line = line.strip()
                words = line.split(" ")
                home, home_score, _, away_score, away = words
                home = self.teams[home]
                away = self.teams[away]
                self.matches.append(self.load_match(home, away, int(home_score), int(away_score)))

    @abstractmethod
    def load_match(home, away, home_score, away_score):
        pass

    @abstractmethod
    def plan(self, ignore_planned=False):
        pass
    
    @abstractmethod
    def simulate(self, method='uniform'):
        pass

    @abstractmethod
    def standings(self):
        pass

    def show_matches(self):
        strs = ["Competition:"]
        for i, match in enumerate(self.matches):
            strs.append("{:d}. {:s}".format(
                i, str(match)
            ))
        return "\n".join(strs)

    @abstractmethod
    def __str__(self):
        pass