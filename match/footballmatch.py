import numpy as np

from match.match import Match


SIM_UNIF_MAX_SCORE = 3
SIM_SOFT_ELO_SIGMA = 200.

class FootballMatch(Match):
    

    def __init__(self, teams, score_names=['goals', 'points']):
        super(FootballMatch, self).__init__(teams, score_names)
    
    def simulate(self, method='uniform', ignore_completed=False):
        if self.completed and not ignore_completed:
            return
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
        elif method == 'soft_elo':
            diff = float(self.teams[0].elo - self.teams[1].elo) / SIM_SOFT_ELO_SIGMA
            goals = int(np.round(np.random.normal(diff, float(SIM_UNIF_MAX_SCORE))))
            base_goals = int(np.round(np.random.randint(0, 2)))
            # Negative offset compensates for diff going negative
            offset = min(0, min(base_goals + goals, base_goals))
            self.scores['goals'][0] = base_goals + goals - offset
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