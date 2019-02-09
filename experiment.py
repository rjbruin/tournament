import tournament


if __name__ == '__main__':
    teams = ["Team" + str(i) for i in range(5)]
    competition = tournament.Competition(teams)
    print(competition.show_matches())
    competition.simulate()
    print(competition.show_matches())
    print(competition)