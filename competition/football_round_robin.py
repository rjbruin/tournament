import numpy as np
from abc import ABCMeta, abstractmethod

from competition.round_robin import RoundRobin
from match.footballmatch import FootballMatch
from competition.utils import aggregate_all_scores, standings_table


def football_ordering(scores):
    """
    Arguments:
        scores ([(str, dict)]): list of team names and score dictionaries.
    
    Returns:
        ordering ([tuple]): tuple of things to order by per team.
    """
    return scores[1]['points'], scores[1]['goals']

class FootballRoundRobin(RoundRobin):
    
    def __init__(self, teams, load_from_file=None):
        super(FootballRoundRobin, self).__init__(teams, load_from_file=load_from_file)
        self.match_type = FootballMatch
        self.plan()

    def load_match(self, home, away, home_score, away_score):
        match = FootballMatch([home, away])
        match.scores['goals'][0] = home_score
        match.scores['goals'][1] = away_score
        match.completed = True
        
        # Points
        if match.scores['goals'][0] > match.scores['goals'][1]:
            match.scores['points'][0] = 3
            match.scores['points'][1] = 0
        elif match.scores['goals'][0] < match.scores['goals'][1]:
            match.scores['points'][0] = 0
            match.scores['points'][1] = 3
        else:
            match.scores['points'][0] = 1
            match.scores['points'][1] = 1

        return match

    def standings(self):
        # Aggregate scores
        total_scores = aggregate_all_scores(self.matches, self.teams)
        
        # Order standings
        scores_tuples = total_scores.items()
        standings = sorted(scores_tuples, key=football_ordering, reverse=True)
        return standings

    def __str__(self):
        metrics_format = [
            ("points", "{:3d}   ", "PTS  "),
            ("goals", "{:2d}    ", "G    ")
        ]

        return standings_table(metrics_format, self.standings(), self.teams)