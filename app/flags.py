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


FLAG_CDN = "https://flagcdn.com/w640/{code}.png"
SPECIAL_CODES = {
    "England": "gb-eng",
    "Scotland": "gb-sct",
}


def flag_emoji(team_name: str) -> str:
    if team_name in SPECIAL:
        return SPECIAL[team_name]
    code = ISO2.get(team_name)
    if not code:
        return "\U0001F3F3"  # white flag fallback
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)


def flag_url(team_name: str) -> str:
    """Return a flagcdn.com PNG URL for the given team name, or empty string."""
    code = SPECIAL_CODES.get(team_name) or ISO2.get(team_name, "").lower()
    if not code:
        return ""
    return FLAG_CDN.format(code=code)


# IOC 3-letter country codes (as used by Wikipedia's tennis seeding/draw
# tables) -> ISO-3166-1 alpha-2. Mostly matches ISO 3166-1 alpha-3, but ~20
# IOC codes diverge from it (GER/DEU, SUI/CHE, NED/NLD, POR/PRT, ...).
IOC3_TO_ISO2 = {
    "ALG": "DZ", "ARG": "AR", "ARM": "AM", "AUS": "AU", "AUT": "AT",
    "AZE": "AZ", "BAH": "BS", "BAR": "BB", "BEL": "BE", "BIH": "BA",
    "BLR": "BY", "BOL": "BO", "BRA": "BR", "BUL": "BG", "CAN": "CA",
    "CHI": "CL", "CHN": "CN", "COL": "CO", "CRC": "CR", "CRO": "HR",
    "CUB": "CU", "CYP": "CY", "CZE": "CZ", "DEN": "DK", "DOM": "DO",
    "ECU": "EC", "EGY": "EG", "ESA": "SV", "ESP": "ES", "EST": "EE",
    "FIN": "FI", "FRA": "FR", "GBR": "GB", "GEO": "GE", "GER": "DE",
    "GHA": "GH", "GRE": "GR", "GUA": "GT", "HAI": "HT", "HKG": "HK",
    "HUN": "HU", "INA": "ID", "IND": "IN", "IRI": "IR", "IRL": "IE",
    "ISL": "IS", "ISR": "IL", "ITA": "IT", "JOR": "JO", "JPN": "JP",
    "KAZ": "KZ", "KEN": "KE", "KOR": "KR", "KUW": "KW", "LAT": "LV",
    "LBN": "LB", "LTU": "LT", "LUX": "LU", "MAR": "MA", "MAS": "MY",
    "MDA": "MD", "MEX": "MX", "MGL": "MN", "MKD": "MK", "MNE": "ME",
    "NED": "NL", "NGR": "NG", "NOR": "NO", "NZL": "NZ", "PAK": "PK",
    "PAN": "PA", "PAR": "PY", "PER": "PE", "PHI": "PH", "POL": "PL",
    "POR": "PT", "PUR": "PR", "QAT": "QA", "ROU": "RO", "RSA": "ZA",
    "RUS": "RU", "SEN": "SN", "SGP": "SG", "SLO": "SI", "SRB": "RS",
    "SRI": "LK", "SUI": "CH", "SVK": "SK", "SWE": "SE", "SYR": "SY",
    "THA": "TH", "TPE": "TW", "TUN": "TN", "TUR": "TR", "UAE": "AE",
    "UKR": "UA", "URU": "UY", "USA": "US", "UZB": "UZ", "VEN": "VE",
    "VIE": "VN", "ZIM": "ZW",
}


def flag_emoji_ioc(ioc_code: str | None) -> str:
    """Flag emoji for an IOC 3-letter country code (e.g. tennis entries)."""
    if not ioc_code:
        return "\U0001F3F3"
    code = IOC3_TO_ISO2.get(ioc_code.upper())
    if not code:
        return "\U0001F3F3"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)
