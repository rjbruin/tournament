import numpy as np

from match import FootballMatch


def football_ordering(teams_and_scores):
    """
    Arguments:
        teams_and_scores ([(str, dict)]): list of team names and score dictionaries.
    
    Returns:
        ordering ([tuple]): tuple of things to order by per team.
    """
    return teams_and_scores[1]['points'], teams_and_scores[1]['goals']

class Competition(object):
    teams = []
    matches = []
    scores = []
    planned = False

    def __init__(self, teams, comp_type='round robin'):
        self.teams = {team.name: team for team in teams}
        self.plan(comp_type)
    
    def plan(self, comp_type, ignore_planned=False):
        if self.planned and not ignore_planned:
            raise ValueError("Competition already planned!")
        if comp_type == 'round robin':
            for home in self.teams.values():
                for away in self.teams.values():
                    if home == away:
                        continue
                    self.matches.append(FootballMatch([home, away]))
        else:
            raise NotImplementedError("comp type != round robin")
        self.planned = True
    
    def simulate(self, method='uniform'):
        for match in self.matches:
            match.simulate(method=method)

    def standings(self, ordering=football_ordering):
        # Aggregate scores
        total_scores = {team: {} for team in self.teams}
        for match in self.matches:
            if not match.completed:
                continue
            for score_name in match.scores:
                home, away = [team.name for team in match.teams]
                if score_name not in total_scores[home]:
                    total_scores[home][score_name] = 0
                total_scores[home][score_name] += match.scores[score_name][0]
                if score_name not in total_scores[away]:
                    total_scores[away][score_name] = 0
                total_scores[away][score_name] += match.scores[score_name][1]
        
        # Order standings
        scores_tuples = total_scores.items()
        standings = sorted(scores_tuples, key=ordering, reverse=True)
        return standings

    def show_matches(self):
        strs = ["Competition:"]
        for i, match in enumerate(self.matches):
            strs.append("{:d}. {:s}".format(
                i, str(match)
            ))
        return "\n".join(strs)

    def __str__(self):
        standings = self.standings()
        strs = ["    TEAM             P    G    ELO"]
        for i, (team_name, score) in enumerate(standings):
            strs.append("{:2d}. {:15s} {:2d}   {:2d}    {:3d}".format(
                i+1, str(self.teams[team_name]),
                score['points'],
                score['goals'],
                self.teams[team_name].elo
            ))
        return "\n".join(strs)