from competition import Competition
from team import Team


if __name__ == '__main__':
    teams = [Team("Team" + str(i)) for i in range(5)]
    competition = Competition(teams)
    print(competition.show_matches())
    competition.simulate(method='hard_elo')
    print(competition.show_matches())
    print(competition)