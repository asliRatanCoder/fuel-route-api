"""
Place-name normalisation shared by the dataset builder and the runtime
geocoder, so that "St. Louis", "Saint Louis" and "SAINT LOUIS " all resolve to
the same lookup key.
"""

import re

US_STATES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'DC': 'District of Columbia', 'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii',
    'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
    'WI': 'Wisconsin', 'WY': 'Wyoming',
}
_STATE_BY_NAME = {name.lower(): abbr for abbr, name in US_STATES.items()}

_ABBREVIATIONS = {
    'saint': 'st', 'sainte': 'ste', 'fort': 'ft', 'mount': 'mt',
    'north': 'n', 'south': 's', 'east': 'e', 'west': 'w',
}


def normalize_name(name):
    """Lower-case, strip punctuation and fold common abbreviations."""
    name = re.sub(r"[.'’`]", '', name.lower())
    tokens = re.sub(r'[^a-z0-9]+', ' ', name).split()
    return ' '.join(_ABBREVIATIONS.get(token, token) for token in tokens)


def place_key(name, state):
    return f'{normalize_name(name)}|{state.upper()}'


def compact_key(name, state):
    """Key that also ignores spacing: "Mc Calla" == "McCalla", "De Forest" == "DeForest"."""
    return f'{normalize_name(name).replace(" ", "")}|{state.upper()}'


def parse_state(text):
    """Return the two-letter code for a state abbreviation or full name, else None."""
    text = text.strip().rstrip('.')
    if text.upper() in US_STATES:
        return text.upper()
    return _STATE_BY_NAME.get(text.lower())
