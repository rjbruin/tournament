import numpy as np

from match.match import Match


SIM_UNIF_MAX_SCORE = 3
SIM_SOFT_ELO_SIGMA = 20.

class LoLMatch(Match):
    

    def __init__(self, teams, score_names=['wins']):
        super(LoLMatch, self).__init__(teams, score_names)
        self.home_win = None
    
    def simulate(self, method='uniform', ignore_completed=False):
        if self.completed and not ignore_completed:
            return
        if method == 'uniform':
            self.home_win = bool(np.random.randint(0, 2))
        elif method == 'hard_elo':
            self.home_win = self.teams[0].elo > self.teams[1].elo
        elif method == 'soft_elo':
            diff = float(self.teams[0].elo - self.teams[1].elo) / SIM_SOFT_ELO_SIGMA
            sigmoid = 1. / (1. + np.exp(-diff))
            self.home_win = np.random.random() <= sigmoid
        else:
            raise NotImplementedError("method = {:s}".format(method))
        # Wins
        self.scores['wins'][0] = 1 if self.home_win else 0
        self.scores['wins'][1] = 1 if not self.home_win else 0
        self.completed = True

    def outcome_likelihood(self, home_wins, home, away, method='uniform'):
        if method == 'soft_elo':
            diff = float(home.elo - away.elo) / SIM_SOFT_ELO_SIGMA
            home_wins_prob = 1. / (1. + np.exp(-diff))
            return home_wins_prob if home_wins else 1. - home_wins_prob
        else:
            raise NotImplementedError()

    def __str__(self):
        if len(self.teams) == 2:
            str = "{} {:d} - {:d} {}".format(
                self.teams[0], self.scores['wins'][0],
                self.scores['wins'][1], self.teams[1]
            )
            if self.completed:
                str += " ({:2.0f}%)".format(
                    self.outcome_likelihood(
                        self.home_win,
                        self.teams[0], self.teams[1],
                        method='soft_elo'
                    ) * 100.
                )
            return str
        else:
            raise NotImplementedError("nr teams != 2")