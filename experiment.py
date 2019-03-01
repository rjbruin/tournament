"""
Experiment.

Usage:
    experiment.py <competition> <match> [<simulation>]


"""
import docopt

from competition import Competition
from team import Team
from match.lolmatch import LoLMatch
from match.footballmatch import FootballMatch


if __name__ == '__main__':
    args = docopt.docopt(__doc__)
    sim_method = 'hard_elo'
    if args['<simulation>']:
        sim_method = args['<simulation>']

    teams = [Team("Team" + str(i)) for i in range(5)]
    competition = Competition.build(
        comp_type=args['<competition>'],
        match_type=args['<match>']
    )(
        teams,
        load_from_file='input_competitions/test.txt'
    )
    print(competition.show_matches())
    competition.simulate(method=sim_method)
    print(competition.show_matches())
    print(competition)