def aggregate_all_scores(matches, teams):
    total_scores = {team: {} for team in teams}
    for match in matches:
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
    
    return total_scores

def standings_table(metrics_format, standings, teams):
    # Table header
    strs = ["    TEAM            "]
    for _, _, header in metrics_format:
        strs[0] += header

    # Rows
    for i, (team_name, score) in enumerate(standings):
        line_str = "{:2d}. {:15s}".format(i+1, str(teams[team_name]))

        for metric_name, metric_format, _ in metrics_format:
            line_str += metric_format.format(score[metric_name])
        
        # DEBUG
        line_str += "{:3d}".format(teams[team_name].elo)

        strs.append(line_str)
    return "\n".join(strs)