import numpy as np
from abc import ABCMeta, abstractmethod

from competition.competition import Competition
from match.footballmatch import FootballMatch


class RoundRobin(Competition):
    
    def __init__(self, teams, load_from_file=None):
        super(RoundRobin, self).__init__(teams, load_from_file=load_from_file)
    
    def plan(self, ignore_planned=False):
        if self.planned and not ignore_planned:
            raise ValueError("Competition already planned!")
        
        already_planned = np.zeros((len(self.teams), len(self.teams)), dtype='bool')
        home_teams = list(self.teams.values())
        away_teams = list(self.teams.values())
        # Find matches already planned
        for match in self.matches:
            home_index = home_teams.index(match.teams[0])
            away_index = home_teams.index(match.teams[1])
            already_planned[home_index, away_index] = True
        
        # Iterate over all possible matches
        for home in home_teams:
            for away in away_teams:
                # Skip if home team is the same as away team
                if home == away:
                    continue
                # Skip if match is already planned
                home_index = home_teams.index(home)
                away_index = home_teams.index(away)
                if already_planned[home_index, away_index]:
                    continue
                # Plan match
                self.matches.append(self.match_type([home, away]))
                already_planned[home_index, away_index] = True
        self.planned = True
    
    def simulate(self, method='uniform'):
        for match in self.matches:
            match.simulate(method=method)

    def standings(self):
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
        ordering = get_ordering(self.comp_type, self.match_type)
        scores_tuples = total_scores.items()
        standings = sorted(scores_tuples, key=ordering, reverse=True)
        return standings

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