#!/usr/bin/env python3
"""
scrape_clubs.py — Scrape WWOZ Livewire for tonight and tomorrow, output clubs-schedule.js

Usage:
  python3 scrape_clubs.py
  python3 scrape_clubs.py 2026-04-27 2026-04-28   # custom dates
"""
import sys, re, json, urllib.request
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta

# ── date handling ───────────────────────────────────────────────────────────
today = date.today()
tomorrow = today + timedelta(days=1)
dates = [str(today), str(tomorrow)]
if len(sys.argv) >= 3:
    dates = [sys.argv[1], sys.argv[2]]

DAY_LABELS = {
    dates[0]: f"Tonight ({today.strftime('%a %b %-d')})",
    dates[1]: f"Tomorrow ({tomorrow.strftime('%a %b %-d')})",
}
DAY_SHORTS = {
    dates[0]: today.strftime('%a'),
    dates[1]: tomorrow.strftime('%a'),
}

# ── neighborhood lookup (venue name fragment → neighborhood) ─────────────
NEIGHBORHOODS = {
    # Frenchmen Street
    'spotted cat': 'Frenchmen St', 'snug harbor': 'Frenchmen St',
    'd.b.a': 'Frenchmen St', 'dba': 'Frenchmen St',
    'blue nile': 'Frenchmen St', 'the maison': 'Frenchmen St',
    'maison,': 'Frenchmen St', 'three muses': 'Frenchmen St',
    'bamboula': 'Frenchmen St', 'café negril': 'Frenchmen St',
    'cafe negril': 'Frenchmen St', 'marigny brasserie': 'Frenchmen St',
    'bacchanal': 'Marigny', 'apple barrel': 'Marigny',
    'saturn bar': 'Marigny', 'siberia': 'Marigny',
    '30/90': 'Marigny', '30°': 'Marigny',
    # French Quarter / Bourbon
    'preservation hall': 'French Quarter',
    "fritzel's": 'French Quarter', 'fritzels': 'French Quarter',
    'maison bourbon': 'French Quarter', 'mahogany': 'French Quarter',
    'palm court': 'French Quarter', 'bourbon': 'French Quarter',
    'jazz playhouse': 'French Quarter', 'pat o': 'French Quarter',
    'pat o\'brien': 'French Quarter',
    # Uptown
    'maple leaf': 'Uptown', "tipitina's": 'Uptown', 'tipitinas': 'Uptown',
    'chickie wah wah': 'Uptown', 'le bon temps': 'Uptown',
    'carrollton': 'Uptown', 'columns hotel': 'Uptown',
    # Mid-City / Broadmoor
    'broadside': 'Mid-City', 'gasa gasa': 'Uptown', 'poor boys': 'Mid-City',
    # CBD / Downtown
    'house of blues': 'CBD', 'joy theater': 'CBD',
    'hard rock': 'CBD', 'saenger': 'CBD',
    # Warehouse / Arts District
    'dos jefes': 'Warehouse District',
    # Hotels
    'polo club': 'CBD', 'pontchartrain': 'Garden District',
    'bayou bar': 'Garden District', 'windsor': 'CBD',
    # Other
    'allways': 'Marigny', 'bj\'s lounge': 'Bywater',
    'bjs lounge': 'Bywater', 'buffa': 'Marigny',
    'true south': 'Metairie', 'euclid': 'Marigny',
    'nola brewing': 'Uptown', 'holy diver': 'Mid-City',
    'flagpole': 'Uptown', 'st. roch': 'St. Roch',
    'paulie': 'CBD', 'canoa': 'CBD',
    'louisiana music factory': 'French Quarter',
    'new orleans jazz museum': 'French Quarter',
    'steamboat': 'French Quarter', 'howlin wolf': 'Warehouse District',
    "howlin' wolf": 'Warehouse District', 'tipitina': 'Uptown',
    'no dice': 'Mid-City', 'original nite cap': 'Mid-City',
    'da jump off': 'Mid-City', 'broadside': 'Marigny',
}

NEIGHBORHOOD_TONES = {
    'Frenchmen St':       '#C2410C',  # warm orange
    'Marigny':            '#BE185D',  # magenta
    'Bywater':            '#9333EA',  # purple
    'French Quarter':     '#0369A1',  # blue
    'Uptown':             '#15803D',  # green
    'Mid-City':           '#0F766E',  # teal
    'CBD':                '#7C2D12',  # dark red
    'Garden District':    '#3730A3',  # indigo
    'Warehouse District': '#B45309',  # amber
    'St. Roch':           '#6B21A8',  # violet
    'Metairie':           '#475569',  # slate
    'Other':              '#374151',  # gray
}

def get_neighborhood(venue_name):
    vl = venue_name.lower()
    for fragment, hood in NEIGHBORHOODS.items():
        if fragment in vl:
            return hood
    return 'Other'

def parse_time(raw: str) -> str:
    """Convert '3:00pm' → '15:00', '10:30pm' → '22:30'."""
    raw = raw.strip().lower()
    m = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)', raw)
    if not m:
        m = re.search(r'(\d{1,2})\s*(am|pm)', raw)
        if not m:
            return '20:00'
        h, ampm = int(m.group(1)), m.group(2)
        minutes = 0
    else:
        h, minutes, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    if ampm == 'pm' and h != 12:
        h += 12
    if ampm == 'am' and h == 12:
        h = 0
    return f'{h:02d}:{minutes:02d}'

def estimate_end(start_time: str, venue_shows_for_day: list, current_idx: int) -> str:
    """End = next show start - 10min, or start + 90min."""
    if current_idx + 1 < len(venue_shows_for_day):
        next_start = venue_shows_for_day[current_idx + 1]['start']
        h, m = map(int, next_start.split(':'))
        total = h * 60 + m - 10
        if total <= h * 60 + int(start_time.split(':')[1]):
            total = h * 60 + int(start_time.split(':')[1]) + 90
        return f'{total // 60 % 24:02d}:{total % 60:02d}'
    h, m = map(int, start_time.split(':'))
    end = h * 60 + m + 90
    return f'{end // 60 % 24:02d}:{end % 60:02d}'

def fetch_and_parse(date_str: str, day_id: str):
    url = f'https://www.wwoz.org/calendar/livewire-music?date={date_str}'
    print(f'Fetching {url} ...')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as r:
        html = r.read().decode('utf-8', errors='replace')

    soup = BeautifulSoup(html, 'lxml')
    cal = soup.find('div', class_='livewire-calendar')
    panels = cal.find_all('div', class_='panel-default')

    venues = {}     # slug → {name, neighborhood, shows: []}
    shows = []

    for panel in panels:
        heading = panel.find('div', class_='panel-heading')
        if not heading:
            continue
        org_link = heading.find('a', href=lambda h: h and '/organizations/' in h)
        if not org_link:
            continue

        venue_name = heading.get_text(strip=True)
        # Clean up OUTDOORS annotation
        venue_display = re.sub(r'\s*\(OUTDOORS?\)\s*', '', venue_name).strip()
        outdoor = '(OUTDOORS)' in venue_name.upper() or '(OUTDOOR)' in venue_name.upper()
        org_slug = org_link['href'].split('/organizations/')[-1].strip('/')

        if org_slug not in venues:
            hood = get_neighborhood(venue_display)
            venues[org_slug] = {
                'slug': org_slug,
                'name': venue_display,
                'outdoor': outdoor,
                'neighborhood': hood,
                'tone': NEIGHBORHOOD_TONES.get(hood, NEIGHBORHOOD_TONES['Other']),
            }

        body = panel.find('div', class_='panel-body')
        if not body:
            continue

        for row in body.find_all('div', class_='row'):
            event_link = row.find('a', href=lambda h: h and '/events/' in h)
            if not event_link:
                continue
            artist = event_link.get_text(strip=True)
            event_id = event_link['href'].split('/events/')[-1].strip('/')

            # Extract time from full text
            full_text = row.get_text(separator='|', strip=True)
            time_raw = full_text.split('at')[-1].strip() if 'at' in full_text else ''
            start = parse_time(time_raw)

            shows.append({
                'venue_slug': org_slug,
                'artist': artist,
                'event_id': event_id,
                'start': start,
                'day_id': day_id,
                'day_date': date_str,
            })

    return venues, shows

# ── scrape both days ─────────────────────────────────────────────────────────
all_venues = {}
all_shows = []
day_ids = {}

for i, date_str in enumerate(dates):
    day_id = f'd{i+1}'
    day_ids[date_str] = day_id
    venues, shows = fetch_and_parse(date_str, day_id)
    for slug, v in venues.items():
        if slug not in all_venues:
            all_venues[slug] = v
    all_shows.extend(shows)

print(f'\nTotal venues: {len(all_venues)}')
print(f'Total shows: {len(all_shows)}')

# ── assign end times per venue per day ──────────────────────────────────────
# Group shows by venue+day, sort by start, then estimate ends
from collections import defaultdict
venue_day_shows = defaultdict(list)
for s in all_shows:
    venue_day_shows[(s['venue_slug'], s['day_id'])].append(s)

for key in venue_day_shows:
    venue_day_shows[key].sort(key=lambda s: s['start'])

for s in all_shows:
    key = (s['venue_slug'], s['day_id'])
    group = venue_day_shows[key]
    idx = group.index(s)
    s['end'] = estimate_end(s['start'], group, idx)

# ── write clubs-schedule.js ─────────────────────────────────────────────────
def js_escape(s):
    s = s.replace('\\', '\\\\').replace("'", "\\'").replace('\n', ' ').replace('\r', '')
    return s

out = []
out.append('// NOLA Jazz Clubs schedule')
out.append(f'// Generated by scrape_clubs.py on {date.today()}')
out.append('// Sources: WWOZ Livewire Music Calendar (wwoz.org)')
out.append('')

# VENUES
sorted_venues = sorted(all_venues.values(), key=lambda v: (v['neighborhood'], v['name']))
out.append('window.VENUES = [')
for v in sorted_venues:
    name_esc = js_escape(v['name'])
    slug = v['slug']
    hood = v['neighborhood']
    tone = v['tone']
    outdoor = 'true' if v['outdoor'] else 'false'
    out.append(f"  {{ id: '{slug}', name: '{name_esc}', neighborhood: '{hood}', tone: '{tone}', outdoor: {outdoor} }},")
out.append('];\n')

# DAYS
out.append('window.DAYS = [')
for i, date_str in enumerate(dates):
    day_id = f'd{i+1}'
    label = DAY_LABELS.get(date_str, date_str)
    short = DAY_SHORTS.get(date_str, date_str[:3])
    out.append(f"  {{ id: '{day_id}', date: '{date_str}', label: '{label}', short: '{short}' }},")
out.append('];\n')

# SHOWS
out.append('window.SHOWS = [')
show_id = 1
for s in all_shows:
    sid = f's{show_id:04d}'
    artist = js_escape(s['artist'])
    venue = s['venue_slug']
    day = s['day_id']
    start = s['start']
    end = s['end']
    out.append(f"  {{ id: '{sid}', name: '{artist}', day: '{day}', venue: '{venue}', start: '{start}', end: '{end}', yt: null, verified: false, blurb: '' }},")
    show_id += 1
out.append('];\n')

dest = '/Users/backlit/Downloads/Jazz Festival ScheduleBot/clubs-schedule.js'
with open(dest, 'w') as f:
    f.write('\n'.join(out))
print(f'\nWrote {dest}')

# ── also write artist list for yt search ────────────────────────────────────
artists = list(dict.fromkeys(s['artist'] for s in all_shows))
with open('/tmp/clubs_artists.txt', 'w') as f:
    for a in artists:
        f.write(a + '\n')
print(f'Artist list written to /tmp/clubs_artists.txt ({len(artists)} unique artists)')
