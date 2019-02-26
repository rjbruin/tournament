import numpy as np


SIM_UNIF_MAX_SCORE = 3

class FootballMatch(object):

    def __init__(self, teams, score_names=['goals', 'points']):
        self.teams = teams
        self.scores = {}
        self.completed = False
        for score_name in score_names:
            self.scores[score_name] = [0 for t in self.teams]
    
    def simulate(self, method='uniform', ignore_completed=False):
        if self.completed and not ignore_completed:
            raise ValueError("Match already completed!")
        if method == 'uniform':
            # Goals
            self.scores['goals'][0] = np.random.randint(0, SIM_UNIF_MAX_SCORE)
            self.scores['goals'][1] = np.random.randint(0, SIM_UNIF_MAX_SCORE)
        elif method == 'hard_elo':
            diff = (self.teams[0].elo - self.teams[1].elo) // 100
            base_goals = np.random.randint(0, 2)
            # Negative offset compensates for diff going negative
            offset = min(0, min(base_goals + diff, base_goals))
            self.scores['goals'][0] = base_goals + diff - offset
            self.scores['goals'][1] = base_goals - offset
        else:
            raise NotImplementedError("method != uniform")
        # Points
        if self.scores['goals'][0] > self.scores['goals'][1]:
            self.scores['points'][0] = 3
            self.scores['points'][1] = 0
        elif self.scores['goals'][0] < self.scores['goals'][1]:
            self.scores['points'][0] = 0
            self.scores['points'][1] = 3
        else:
            self.scores['points'][0] = 1
            self.scores['points'][1] = 1
        self.completed = True

    def __str__(self):
        if len(self.teams) == 2:
            return "{} {:d} - {:d} {}".format(
                self.teams[0], self.scores['goals'][0],
                self.scores['goals'][1], self.teams[1]
            )
        else:
            raise NotImplementedError("nr teams != 2")