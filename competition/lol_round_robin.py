import numpy as np
from abc import ABCMeta, abstractmethod

from competition.round_robin import RoundRobin
from match.lolmatch import LoLMatch
from competition.utils import aggregate_all_scores, standings_table


def lol_ordering(scores):
    """
    Arguments:
        scores ([(str, dict)]): list of team names and score dictionaries.
    
    Returns:
        ordering ([tuple]): tuple of things to order by per team.
    """
    return scores[1]['wins']

class LoLRoundRobin(RoundRobin):
    
    def __init__(self, teams, load_from_file=None):
        super(LoLRoundRobin, self).__init__(teams, load_from_file=load_from_file)
        self.match_type = LoLMatch
        self.plan()

    def load_match(self, home, away, home_score, away_score):
        match = LoLMatch([home, away])
        match.scores['wins'][0] = home_score
        match.scores['wins'][1] = away_score
        match.completed = True
        match.home_win = home_score > away_score
        return match

    def standings(self):
        # Aggregate scores
        total_scores = aggregate_all_scores(self.matches, self.teams)
        
        # Order standings
        scores_tuples = total_scores.items()
        standings = sorted(scores_tuples, key=lol_ordering, reverse=True)
        return standings

    def __str__(self):
        metrics_format = [
            ("wins", "{:2d}   ", "W    "),
        ]

        return standings_table(metrics_format, self.standings(), self.teams)