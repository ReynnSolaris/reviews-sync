"""Fetch the five-star Google reviews for both stores and write them to reviews.json.

Run once a day by .github/workflows/sync.yml. The theme's Google reviews section reads the file.
Needs GOOGLE_API_KEY (Places API (New) enabled). One key reads both stores; to use a key per
store, set GOOGLE_API_KEY_1 and GOOGLE_API_KEY_2 instead. Python standard library only.

Google's Places policy forbids saving reviews, so this keeps no archive: each run replaces the
file with what Google returns today (at most 5 reviews per place). Only the place IDs carry over.

    python3 sync.py          fetch and write reviews.json
    python3 sync.py --test   check the filtering without calling Google
"""
import datetime
import json
import os
import sys
import urllib.request

# Theme store number -> what to search Google for, used once to find the place ID.
STORES = {
    '1': 'Diamond R Equipment, 4012 US Hwy 63, Freeburg, MO 65035',
    '2': 'Diamond R Equipment, 19677 N Outer Road, Higginsville, MO 64037',
}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reviews.json')
API = 'https://places.googleapis.com/v1/'


def call(key, path, mask, body=None):
    """GET, or POST when there is a body. Raises on any HTTP error, so a bad run changes nothing."""
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None, headers={
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': key,
        'X-Goog-FieldMask': mask,
    })
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def find_place(key, query):
    # A mask of places.id alone is the free "IDs Only" search.
    found = call(key, 'places:searchText', 'places.id', {'textQuery': query, 'pageSize': 1}).get('places') or []
    if not found:
        raise SystemExit('No Google place found for: ' + query)
    return found[0]['id']


def pick(place):
    """Place Details answer -> what the theme shows: five-star reviews that have text."""
    reviews = []
    for r in place.get('reviews') or []:
        text = ' '.join(((r.get('text') or r.get('originalText') or {}).get('text') or '').split())
        if r.get('rating') != 5 or not text:
            continue
        who = r.get('authorAttribution') or {}
        reviews.append({
            'author': who.get('displayName', ''),
            'author_url': who.get('uri', ''),
            'photo': who.get('photoUri', ''),
            'text': text,
            'when': r.get('relativePublishTimeDescription', ''),
            'url': r.get('googleMapsUri', ''),
        })
    return {
        'place_id': place.get('id', ''),
        'url': (place.get('googleMapsLinks') or {}).get('reviewsUri') or place.get('googleMapsUri', ''),
        'reviews': reviews,
    }


def main():
    try:
        old = json.load(open(OUT)).get('stores', {})
    except (OSError, ValueError):
        old = {}
    stores = {}
    for n, query in STORES.items():
        key = os.environ.get('GOOGLE_API_KEY_' + n) or os.environ['GOOGLE_API_KEY']
        place_id = (old.get(n) or {}).get('place_id') or find_place(key, query)
        place = call(key, 'places/' + place_id, 'id,userRatingCount,googleMapsUri,googleMapsLinks,reviews')
        stores[n] = pick(place)
        # The log tells "Google sent none" apart from "none of them were five-star".
        print('store %s: Google lists %s reviews, sent ratings %s, kept %d (fields: %s)' % (
            n, place.get('userRatingCount'), [r.get('rating') for r in place.get('reviews') or []],
            len(stores[n]['reviews']), ', '.join(sorted(place))))
    # The date changes every day, so every run commits. That keeps GitHub's schedule alive.
    with open(OUT, 'w') as f:
        json.dump({'synced': datetime.date.today().isoformat(), 'stores': stores}, f, indent=2, ensure_ascii=False)
        f.write('\n')


def test():
    got = pick({
        'id': 'abc',
        'googleMapsUri': 'https://maps.example/place',
        'reviews': [
            {'rating': 5, 'text': {'text': ' Great\n\n service  '}, 'authorAttribution': {'displayName': 'A'}},
            {'rating': 4, 'text': {'text': 'Good'}},
            {'rating': 5, 'text': {'text': '   '}},
            {'rating': 5, 'originalText': {'text': 'Solo original'}},
        ],
    })
    assert [r['text'] for r in got['reviews']] == ['Great service', 'Solo original'], got
    assert got['reviews'][0]['author'] == 'A' and got['place_id'] == 'abc'
    assert got['url'] == 'https://maps.example/place'
    assert pick({'googleMapsLinks': {'reviewsUri': 'https://maps.example/reviews'}})['url'] == 'https://maps.example/reviews'
    assert pick({}) == {'place_id': '', 'url': '', 'reviews': []}
    print('ok')


if __name__ == '__main__':
    test() if '--test' in sys.argv else main()
