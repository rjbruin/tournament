import numpy as np


SIM_UNIF_MAX_SCORE = 3

class Match(object):
    teams = []
    score = []
    completed = False

    def __init__(self, teams):
        self.teams = teams
        self.score = [0 for t in self.teams]
    
    def simulate(self, method='uniform', ignore_completed=False):
        if self.completed and not ignore_completed:
            raise ValueError("Match already completed!")
        if method == 'uniform':
            self.score[0] = np.random.randint(0, SIM_UNIF_MAX_SCORE)
            self.score[1] = np.random.randint(0, SIM_UNIF_MAX_SCORE)
        else:
            raise NotImplementedError("method != uniform")
        self.completed = True

    def __str__(self):
        if len(self.teams) == 2:
            print("{:s} {:d} - {:d} {:s}".format(
                self.teams[0], self.score[0],
                self.score[1], self.teams[1]
            ))
        else:
            raise NotImplementedError("nr teams != 2")


class Competition(object):
    teams = []
    matches = []
    scores = []
    planned = False

    def __init__(self, teams, comp_type='round robin'):
        self.teams = teams
        self.plan(comp_type)
    
    def plan(self, comp_type, ignore_planned=False):
        if self.planned and not ignore_planned:
            raise ValueError("Competition already planned!")
        if comp_type == 'round robin':
            for home in self.teams:
                for away in self.teams:
                    if home == away:
                        continue
                    self.matches.append(Match([home, away]))
        else:
            raise NotImplementedError("comp type != round robin")
        self.planned = True
    
    def simulate(self, method='uniform'):
        for match in self.matches:
            match.simulate(method=method)
    
    def __str__(self):
        strs = ["Competition:"]
        for i, match in enumerate(self.matches):
            strs.append("{:d}. {:s}".format(
                i, str(match)
            ))
        return "\n".join(strs)