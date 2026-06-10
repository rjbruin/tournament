"""
Team name -> flag emoji helper.

Most flags are derived from the standard ISO-3166-1 alpha-2 "regional
indicator symbol" emoji sequence. England and Scotland don't have ISO
country codes, so they use the special Unicode "tag sequence" flags.
"""

ISO2 = {
    "Spain": "ES",
    "Argentina": "AR",
    "France": "FR",
    "Brazil": "BR",
    "Portugal": "PT",
    "Netherlands": "NL",
    "Germany": "DE",
    "Belgium": "BE",
    "Croatia": "HR",
    "Colombia": "CO",
    "Morocco": "MA",
    "Uruguay": "UY",
    "Switzerland": "CH",
    "Japan": "JP",
    "Austria": "AT",
    "Senegal": "SN",
    "Norway": "NO",
    "USA": "US",
    "South Korea": "KR",
    "Turkey": "TR",
    "Ecuador": "EC",
    "Sweden": "SE",
    "Mexico": "MX",
    "Canada": "CA",
    "Czech Republic": "CZ",
    "Ivory Coast": "CI",
    "Paraguay": "PY",
    "Algeria": "DZ",
    "Bosnia and Herzegovina": "BA",
    "Iran": "IR",
    "Australia": "AU",
    "Ghana": "GH",
    "Egypt": "EG",
    "Tunisia": "TN",
    "South Africa": "ZA",
    "Iraq": "IQ",
    "DR Congo": "CD",
    "Panama": "PA",
    "Uzbekistan": "UZ",
    "Saudi Arabia": "SA",
    "Cape Verde": "CV",
    "Qatar": "QA",
    "Jordan": "JO",
    "Curacao": "CW",
    "Haiti": "HT",
    "New Zealand": "NZ",
}

# Special non-ISO "subdivision" flags using Unicode tag sequences.
SPECIAL = {
    "England": "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
    "Scotland": "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F",
}


def flag_emoji(team_name: str) -> str:
    if team_name in SPECIAL:
        return SPECIAL[team_name]
    code = ISO2.get(team_name)
    if not code:
        return "\U0001F3F3"  # white flag fallback
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)
